"""
The Blackboard -- shared state across agents in a single trigger lifecycle.

For each trigger (user message OR proactive event), one Blackboard instance is
created. All agents read from it, evaluate their relevance, post claims to it,
and write their final outputs back to it.

Single-process, in-memory. Multi-process would need Redis pub/sub.

USAGE:
    bb = Blackboard(trigger_id="t_001", trigger_type="user_message",
                    payload={...})
    bb.add_claim(AgentClaim(...))
    resolved = bb.resolve_claims()
    bb.write_output("classifier", output)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ════════════════════════════════════════════════════════════════
# Data Models
# ════════════════════════════════════════════════════════════════


class TriggerEvent(BaseModel):
    """The originating event that started this blackboard."""

    trigger_id: str = Field(default_factory=lambda: f"t_{uuid.uuid4().hex[:12]}")
    trigger_type: Literal[
        "user_message",
        "new_regulation",
        "reg_amended",
        "deadline_near",
        "coverage_gap",
        "data_object_added",
        "reg_conflict",
    ]
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentClaim(BaseModel):
    """An agent's claim that it wants to respond to the trigger."""

    agent_id: str                              # e.g. "classifier"
    relevance_score: float                     # 0.0 - 1.0
    response_type: Literal["primary", "supporting", "cross_talk"]
    depends_on: list[str] = Field(default_factory=list)
    reasoning: str = ""                        # for debugging


class AgentOutput(BaseModel):
    """What an agent produces. Generic envelope -- payload is agent-specific."""

    agent_id: str
    trigger_id: str
    claim: AgentClaim
    payload: dict[str, Any]                    # Pydantic-typed in caller, dict here
    started_at: datetime
    completed_at: datetime
    error: Optional[str] = None


# ════════════════════════════════════════════════════════════════
# The Blackboard
# ════════════════════════════════════════════════════════════════


class Blackboard:
    """
    In-memory blackboard for a single trigger lifecycle.

    Thread-safe? No -- relies on asyncio single-event-loop semantics.
    Multi-process? No -- one instance per Python process.
    """

    def __init__(
        self,
        *,
        trigger_id: str | None = None,
        trigger_type: str = "user_message",
        payload: dict[str, Any] | None = None,
    ):
        self.event = TriggerEvent(
            trigger_id=trigger_id or f"t_{uuid.uuid4().hex[:12]}",
            trigger_type=trigger_type,
            payload=payload or {},
        )
        self._claims: list[AgentClaim] = []
        self._resolved_order: list[AgentClaim] = []
        self._outputs: dict[str, AgentOutput] = {}
        self._auditor_verdict: Optional[str] = None

    # ─── Read accessors ────────────────────────────────────────

    @property
    def trigger_id(self) -> str:
        return self.event.trigger_id

    @property
    def trigger_type(self) -> str:
        return self.event.trigger_type

    @property
    def payload(self) -> dict[str, Any]:
        return self.event.payload

    def get_output(self, agent_id: str) -> Optional[AgentOutput]:
        """Get a specific agent's output if it has completed."""
        return self._outputs.get(agent_id)

    def get_outputs(self) -> dict[str, AgentOutput]:
        """All completed agent outputs."""
        return dict(self._outputs)

    def has_output_from(self, agent_id: str) -> bool:
        return agent_id in self._outputs

    # ─── Claim management ─────────────────────────────────────

    def add_claim(self, claim: AgentClaim) -> None:
        """Agent posts a claim during the eval phase."""
        self._claims.append(claim)

    def get_claims(self) -> list[AgentClaim]:
        """All raw claims (before resolution)."""
        return list(self._claims)

    def resolve_claims(self, max_per_message: int = 3) -> list[AgentClaim]:
        """
        Apply conflict resolution rules and return the ordered list of agents
        that will actually execute.

        Rules:
        - Sort by (response_type priority, relevance_score desc)
        - Only 1 primary (the highest scoring)
        - Up to 1 supporting, 1 cross_talk (in addition to primary)
        - Total capped at max_per_message
        - Dependencies must execute first (topological order applied AFTER cap)
        """
        if not self._claims:
            self._resolved_order = []
            return []

        # Type priority: primary > supporting > cross_talk
        type_priority = {"primary": 0, "supporting": 1, "cross_talk": 2}

        # Sort and keep best
        sorted_claims = sorted(
            self._claims,
            key=lambda c: (type_priority[c.response_type], -c.relevance_score),
        )

        # Enforce: only 1 primary, only 1 supporting, only 1 cross_talk
        kept: list[AgentClaim] = []
        seen_types: set[str] = set()
        for claim in sorted_claims:
            if claim.response_type in seen_types:
                continue
            kept.append(claim)
            seen_types.add(claim.response_type)
            if len(kept) >= max_per_message:
                break

        # Apply dependency ordering
        ordered = _topological_sort(kept, all_claims=self._claims)
        self._resolved_order = ordered
        return ordered

    def get_resolved_order(self) -> list[AgentClaim]:
        return list(self._resolved_order)

    # ─── Output management ────────────────────────────────────

    def write_output(self, output: AgentOutput) -> None:
        """An agent has completed and written its output."""
        self._outputs[output.agent_id] = output

    def set_auditor_verdict(self, verdict: str) -> None:
        self._auditor_verdict = verdict

    def get_auditor_verdict(self) -> Optional[str]:
        return self._auditor_verdict

    # ─── Serialization (for WebSocket streaming) ──────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_id": self.event.trigger_id,
            "trigger_type": self.event.trigger_type,
            "payload": self.event.payload,
            "claims": [c.model_dump() for c in self._claims],
            "resolved_order": [c.model_dump() for c in self._resolved_order],
            "outputs": {k: v.model_dump() for k, v in self._outputs.items()},
            "auditor_verdict": self._auditor_verdict,
        }


# ════════════════════════════════════════════════════════════════
# Topological Sort (dependency ordering)
# ════════════════════════════════════════════════════════════════


def _topological_sort(
    claims_to_order: list[AgentClaim],
    all_claims: list[AgentClaim],
) -> list[AgentClaim]:
    """
    Order claims so that depends_on relationships are honored.

    Dependencies referring to agents NOT in claims_to_order are ignored
    (they didn't claim, so we don't wait on them).

    Raises ValueError on cycle.
    """
    valid_ids = {c.agent_id for c in claims_to_order}
    deps: dict[str, set[str]] = {
        c.agent_id: {d for d in c.depends_on if d in valid_ids}
        for c in claims_to_order
    }

    result: list[AgentClaim] = []
    visited: set[str] = set()
    visiting: set[str] = set()
    by_id = {c.agent_id: c for c in claims_to_order}

    def visit(agent_id: str) -> None:
        if agent_id in visited:
            return
        if agent_id in visiting:
            raise ValueError(f"Dependency cycle detected at {agent_id}")
        visiting.add(agent_id)
        for dep in deps.get(agent_id, set()):
            visit(dep)
        visiting.remove(agent_id)
        visited.add(agent_id)
        result.append(by_id[agent_id])

    # Visit in original priority order so within independent groups the
    # higher-relevance claim still comes first.
    for claim in claims_to_order:
        visit(claim.agent_id)

    return result
