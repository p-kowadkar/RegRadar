"""
BaseAgent -- the contract every agent obeys.

Every agent implements the 3-phase blackboard evaluation:

    Phase 1: hard_filter (rule-based, no LLM)        -> return True to stay silent
    Phase 2: score_relevance (cheap LLM call)        -> return float 0.0-1.0
    Phase 3: classify_claim_type (deterministic)     -> AgentClaim or None

Then if the agent is selected to run:

    execute(blackboard)                              -> writes output to blackboard

USAGE (in a subclass):
    class ClassifierAgent(BaseAgent):
        agent_id = "classifier"
        display_name = "The Classifier"
        model = "gemini-3.5-flash"

        async def score_relevance(self, bb: Blackboard) -> float:
            ...

        async def execute(self, bb: Blackboard) -> None:
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from backend.orchestrator.blackboard import AgentClaim, AgentOutput, Blackboard
from backend.utils.logging import annotate_llm_span, get_logger

log = get_logger(__name__)


class BaseAgent(ABC):
    """Abstract base for all 6 agents."""

    # ─── Subclass MUST set these ──────────────────────────────
    agent_id: str = ""
    display_name: str = ""
    model: str = ""                                    # e.g. "gemini-3.5-flash"

    # ─── Subclass MAY override these ──────────────────────────
    primary_threshold: float = 0.85
    supporting_threshold: float = 0.65
    cross_talk_threshold: float = 0.50
    primary_dependencies: list[str] = []
    supporting_dependencies: list[str] = []

    # ════════════════════════════════════════════════════════
    # Phase 1: hard filter (rule-based, no LLM)
    # ════════════════════════════════════════════════════════

    def hard_filter(self, blackboard: Blackboard) -> bool:
        """
        Return True to STAY SILENT. No LLM call made.
        Override in subclass for cheap rule-based filtering.
        Default: never filter (always proceed to Phase 2).
        """
        return False

    # ════════════════════════════════════════════════════════
    # Phase 2: score relevance (cheap LLM call)
    # ════════════════════════════════════════════════════════

    @abstractmethod
    async def score_relevance(self, blackboard: Blackboard) -> float:
        """
        Score how relevant this trigger is to me. Return float 0.0 - 1.0.
        Subclass implements -- typically a Gemini Flash call.
        """
        ...

    # ════════════════════════════════════════════════════════
    # Phase 3: classify claim type (deterministic)
    # ════════════════════════════════════════════════════════

    def classify_claim_type(
        self,
        score: float,
        blackboard: Blackboard,
    ) -> Optional[AgentClaim]:
        """
        Deterministic mapping from score -> claim type. Return None to stay silent.
        Subclasses rarely need to override this.
        """
        if score < self.cross_talk_threshold:
            return None
        if score >= self.primary_threshold:
            return AgentClaim(
                agent_id=self.agent_id,
                relevance_score=score,
                response_type="primary",
                depends_on=self.primary_dependencies,
                reasoning=f"score={score:.2f} >= primary_threshold={self.primary_threshold}",
            )
        if score >= self.supporting_threshold:
            return AgentClaim(
                agent_id=self.agent_id,
                relevance_score=score,
                response_type="supporting",
                depends_on=self.supporting_dependencies,
                reasoning=f"score={score:.2f} >= supporting_threshold={self.supporting_threshold}",
            )
        return AgentClaim(
            agent_id=self.agent_id,
            relevance_score=score,
            response_type="cross_talk",
            depends_on=[],
            reasoning=f"score={score:.2f} >= cross_talk_threshold={self.cross_talk_threshold}",
        )

    # ════════════════════════════════════════════════════════
    # Execute (only called if selected)
    # ════════════════════════════════════════════════════════

    @abstractmethod
    async def execute(self, blackboard: Blackboard) -> None:
        """
        Do the actual work. Write output to blackboard.write_output(...).
        Called only if the agent's claim was selected by the orchestrator.
        """
        ...

    # ════════════════════════════════════════════════════════
    # Convenience: full lifecycle in one call (for testing)
    # ════════════════════════════════════════════════════════

    async def evaluate(self, blackboard: Blackboard) -> Optional[AgentClaim]:
        """
        Run phases 1-3 and return the claim (or None).
        Most callers will use the orchestrator instead, but this is handy
        for unit tests.
        """
        if self.hard_filter(blackboard):
            log.info(
                "agent.hard_filter_silent",
                agent=self.agent_id,
                trigger_id=blackboard.trigger_id,
            )
            return None

        score = await self.score_relevance(blackboard)
        log.info(
            "agent.relevance_scored",
            agent=self.agent_id,
            trigger_id=blackboard.trigger_id,
            score=score,
        )

        claim = self.classify_claim_type(score, blackboard)
        if claim is None:
            log.info(
                "agent.below_threshold_silent",
                agent=self.agent_id,
                trigger_id=blackboard.trigger_id,
                score=score,
            )
        return claim

    # ════════════════════════════════════════════════════════
    # Helper for subclasses to write outputs cleanly
    # ════════════════════════════════════════════════════════

    def _write_output(
        self,
        blackboard: Blackboard,
        payload: dict,
        started_at: datetime,
        error: Optional[str] = None,
    ) -> None:
        claim = next(
            (c for c in blackboard.get_resolved_order() if c.agent_id == self.agent_id),
            None,
        )
        if claim is None:
            # Fall back to a synthetic claim (shouldn't happen in normal flow)
            claim = AgentClaim(
                agent_id=self.agent_id,
                relevance_score=1.0,
                response_type="primary",
                depends_on=[],
                reasoning="executed without explicit claim",
            )

        output = AgentOutput(
            agent_id=self.agent_id,
            trigger_id=blackboard.trigger_id,
            claim=claim,
            payload=payload,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            error=error,
        )
        blackboard.write_output(output)
        annotate_llm_span(
            agent_id=self.agent_id,
            trigger_id=blackboard.trigger_id,
            claim_id=f"{blackboard.trigger_id}:{self.agent_id}",
        )
