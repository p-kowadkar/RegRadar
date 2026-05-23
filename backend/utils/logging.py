"""
Structured logging via structlog + Datadog LLM Observability tagging.

Every log line is JSON. Datadog ingests these as searchable fields.
LLM spans get custom tags via `annotate_llm_span()`.

USAGE:
    from backend.utils.logging import configure_logging, get_logger, annotate_llm_span
    configure_logging()                                     # call once at startup
    log = get_logger()
    log.info("classifier.start", regulation_id="abc123")
    annotate_llm_span(agent_id="classifier", trigger_id="t_001")
"""

import logging
import sys
from typing import Any

import structlog


def configure_logging(level: str = "INFO") -> None:
    """
    Configure structlog + stdlib logging to emit JSON.
    Call once at app startup BEFORE any other module logs.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Stdlib config -- emits to stderr, no formatting (structlog handles)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _add_dd_trace_context,                   # inject dd.trace_id, dd.span_id
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structlog logger. Use at module top: log = get_logger(__name__)."""
    return structlog.get_logger(name)


def annotate_llm_span(
    *,
    agent_id: str,
    trigger_id: str | None = None,
    claim_id: str | None = None,
    extra_tags: dict[str, Any] | None = None,
) -> None:
    """
    Add custom tags to the currently-active Datadog LLM Obs span.

    Called from inside each agent's execute() method.
    """
    try:
        from ddtrace.llmobs import LLMObs
    except ImportError:
        # ddtrace not installed (dev without tracing) -- no-op
        return

    tags: dict[str, Any] = {"agent": agent_id}
    if trigger_id:
        tags["trigger_id"] = trigger_id
    if claim_id:
        tags["claim_id"] = claim_id
    if extra_tags:
        tags.update(extra_tags)

    try:
        LLMObs.annotate(tags=tags)
    except Exception:
        # If no span is active or LLMObs is disabled, silently skip
        pass


def _add_dd_trace_context(logger, method_name, event_dict):
    """
    Processor: injects current Datadog trace_id and span_id into log entries.
    Datadog UI uses these to correlate logs with traces.
    """
    try:
        from ddtrace import tracer
        span = tracer.current_span()
        if span:
            event_dict["dd.trace_id"] = str(span.trace_id)
            event_dict["dd.span_id"] = str(span.span_id)
    except Exception:
        pass
    return event_dict
