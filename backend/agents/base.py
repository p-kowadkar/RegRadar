"""
Shared helpers for all 4 agents (Policy Crawler, Impact Analysis, Auditor, Monitoring).

This file used to host a BaseAgent ABC for the old 6-agent blackboard self-selection
architecture. That design was replaced with Pydantic AI's `Agent` class as the agent
primitive (see docs/AGENTS.md). Pydantic AI gives us:

  - Typed input/output via Pydantic models
  - Tool dispatch via @agent.tool decorator
  - Automatic ddtrace instrumentation (when ddtrace >= 4.8 + pydantic-ai >= 1.63)
  - Native async, FastAPI-native

So there's no ABC needed anymore. Each agent in backend/agents/<name>.py just
instantiates a Pydantic AI Agent with its system prompt and tools.

What stays here:
  - AGENT_IDS constants -- canonical identifiers used by structlog + Datadog
  - run_with_observability() -- decorator that tags every agent run with the
    right trigger_id, agent_id, and Datadog LLM Obs tags. Wraps any agent.run().
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from backend.utils.logging import annotate_llm_span, get_logger

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Canonical agent identifiers
# Used in: structlog fields, Datadog tags, ClickHouse audit_trail rows
# ════════════════════════════════════════════════════════════════

AGENT_POLICY_CRAWLER = "policy_crawler"
AGENT_IMPACT_ANALYSIS = "impact_analysis"
AGENT_AUDITOR = "auditor"
AGENT_MONITORING = "monitoring"

ALL_AGENT_IDS = (
    AGENT_POLICY_CRAWLER,
    AGENT_IMPACT_ANALYSIS,
    AGENT_AUDITOR,
    AGENT_MONITORING,
)


# ════════════════════════════════════════════════════════════════
# Observability wrapper
# Use this around every agent run to ensure consistent Datadog tagging.
# ════════════════════════════════════════════════════════════════


@asynccontextmanager
async def agent_run_context(
    *,
    agent_id: str,
    trigger_id: str,
    extra_tags: dict | None = None,
) -> AsyncIterator[None]:
    """
    Context manager: tags the currently-active ddtrace LLM Obs span with
    agent_id + trigger_id, logs start/end events, and re-raises any exception
    after logging it.

    Usage:
        async with agent_run_context(agent_id="policy_crawler", trigger_id=tid):
            result = await policy_crawler_agent.run(input)
    """
    if agent_id not in ALL_AGENT_IDS:
        raise ValueError(f"Unknown agent_id: {agent_id}. Must be one of {ALL_AGENT_IDS}")

    annotate_llm_span(
        agent_id=agent_id,
        trigger_id=trigger_id,
        extra_tags=extra_tags,
    )
    log.info("agent.run.start", agent=agent_id, trigger_id=trigger_id)

    try:
        yield
    except Exception as e:
        log.error(
            "agent.run.failed",
            agent=agent_id,
            trigger_id=trigger_id,
            error=str(e),
            exception_type=type(e).__name__,
        )
        raise
    else:
        log.info("agent.run.complete", agent=agent_id, trigger_id=trigger_id)
