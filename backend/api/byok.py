"""POST /api/byok/validate/llm  +  POST /api/byok/validate/scraper

Lightweight, cheap validation endpoints for the Settings modal's
"Validate" buttons. Each one:

  1. Reads BYOK headers via extract_user_keys.
  2. Makes ONE minimal call to the chosen provider.
  3. Returns a structured ValidationResult with ok=True/False, a category
     ("auth" | "model" | "network" | "other"), and a human-readable
     message.

Cost guard: these endpoints DO NOT charge against the demo budget, since
they're for verifying user-supplied keys. They DO still go through
Turnstile (when enabled) and SlowAPI (modest cap) to prevent abuse.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from backend.api.security import (
    UserKeys,
    extract_user_keys,
    limiter,
    verify_turnstile,
)
from backend.integrations.vertex_ai import vertex_model_for_user
from backend.utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/byok", tags=["byok"])


# Limit validations to 20/min/IP -- enough for fat-finger key edits,
# tight enough that no one runs a credential stuffer through us.
_VALIDATE_LIMIT = os.environ.get("BYOK_VALIDATE_RATE_LIMIT", "20/minute")


# ════════════════════════════════════════════════════════════════
# Response model
# ════════════════════════════════════════════════════════════════

ErrorCategory = Literal["auth", "model", "network", "missing", "other"]


class ValidationResult(BaseModel):
    ok: bool
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    error_category: ErrorCategory | None = None
    error: str | None = None
    detail: str | None = None  # raw provider message when useful


# ════════════════════════════════════════════════════════════════
# Helpers -- categorize provider errors so the frontend can color/label
# ════════════════════════════════════════════════════════════════


def _categorize_llm_error(exc: BaseException) -> tuple[ErrorCategory, str, str]:
    """Return (category, short message, raw detail) for an LLM-side exception."""
    raw = str(exc)
    lower = raw.lower()
    # Pydantic AI / OpenAI / Google / OpenRouter all share similar HTTP error vocab.
    if "401" in raw or "unauthorized" in lower or "invalid api key" in lower or "invalid_api_key" in lower:
        return "auth", "Invalid API key", raw
    if "403" in raw or "forbidden" in lower:
        return "auth", "Key rejected (forbidden)", raw
    if "404" in raw or "model_not_found" in lower or "model not found" in lower or "does not exist" in lower:
        return "model", "Model not available on this provider", raw
    if "429" in raw or "rate limit" in lower or "rate_limit" in lower:
        return "other", "Provider rate-limited the validation call", raw
    if any(t in lower for t in ["timeout", "timed out", "connection", "network", "name or service"]):
        return "network", "Network error reaching provider", raw
    return "other", type(exc).__name__, raw


def _categorize_scraper_error(exc: BaseException) -> tuple[ErrorCategory, str, str]:
    raw = str(exc)
    lower = raw.lower()
    if "401" in raw or "403" in raw or "unauthorized" in lower or "invalid api key" in lower or "invalid_api_key" in lower:
        return "auth", "Invalid API key", raw
    if "429" in raw or "rate limit" in lower or "quota" in lower or "credit" in lower:
        return "other", "Quota or credit exceeded", raw
    if any(t in lower for t in ["timeout", "timed out", "connection", "network", "name or service"]):
        return "network", "Network error reaching scraper", raw
    if "got an unexpected keyword argument" in lower or "attributeerror" in lower:
        return "other", "Scraper SDK version mismatch (server-side bug)", raw
    return "other", type(exc).__name__, raw


# ════════════════════════════════════════════════════════════════
# /api/byok/validate/llm
# ════════════════════════════════════════════════════════════════


@router.post("/validate/llm", response_model=ValidationResult)
@limiter.limit(_VALIDATE_LIMIT)
async def validate_llm(
    request: Request,
    _turnstile_ok: bool = Depends(verify_turnstile),
    user_keys: UserKeys = Depends(extract_user_keys),
) -> ValidationResult:
    """Send a one-token ping to the user-supplied LLM provider/model/key."""
    if not user_keys.has_llm_key:
        return ValidationResult(
            ok=False,
            error_category="missing",
            error="No LLM key sent",
            detail="Include X-User-LLM-Key + X-User-LLM-Provider headers.",
        )

    started = time.perf_counter()

    try:
        model = vertex_model_for_user(
            api_key=user_keys.llm_key,  # type: ignore[arg-type]
            provider=user_keys.llm_provider,  # type: ignore[arg-type]
            model_name=user_keys.llm_model,
        )
    except ValueError as e:
        return ValidationResult(
            ok=False,
            provider=user_keys.llm_provider,
            error_category="model",
            error="Provider/model configuration rejected",
            detail=str(e),
        )

    # Use Pydantic AI directly with a tiny prompt -- single token output,
    # forces a real round-trip but costs ~$0.0001.
    from pydantic_ai import Agent

    probe = Agent(model=model, system_prompt="Reply with exactly: ok")

    try:
        result = await asyncio.wait_for(probe.run("ping"), timeout=15.0)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        out = (getattr(result, "output", None) or "").strip()
        log.info(
            "byok.validate.llm_ok",
            provider=user_keys.llm_provider,
            model=user_keys.llm_model,
            latency_ms=elapsed_ms,
            output_len=len(out),
        )
        return ValidationResult(
            ok=True,
            provider=user_keys.llm_provider,
            model=user_keys.llm_model or "(default)",
            latency_ms=elapsed_ms,
        )
    except asyncio.TimeoutError:
        return ValidationResult(
            ok=False,
            provider=user_keys.llm_provider,
            error_category="network",
            error="Provider didn't respond within 15s",
        )
    except Exception as e:
        category, message, raw = _categorize_llm_error(e)
        log.warning(
            "byok.validate.llm_failed",
            provider=user_keys.llm_provider,
            model=user_keys.llm_model,
            category=category,
            error=raw[:300],
        )
        return ValidationResult(
            ok=False,
            provider=user_keys.llm_provider,
            model=user_keys.llm_model or "(default)",
            error_category=category,
            error=message,
            detail=raw[:500],
        )


# ════════════════════════════════════════════════════════════════
# /api/byok/validate/scraper
# ════════════════════════════════════════════════════════════════

# Use a deliberately tiny, reliably-available target so the test is cheap
# and predictable. example.com is the canonical "always up" page.
_PROBE_URL = "https://example.com"


@router.post("/validate/scraper", response_model=ValidationResult)
@limiter.limit(_VALIDATE_LIMIT)
async def validate_scraper(
    request: Request,
    _turnstile_ok: bool = Depends(verify_turnstile),
    user_keys: UserKeys = Depends(extract_user_keys),
) -> ValidationResult:
    """Scrape https://example.com using the BYOK scraper key/provider."""
    if not user_keys.has_scraper_key:
        return ValidationResult(
            ok=False,
            error_category="missing",
            error="No scraper key sent",
            detail="Include X-User-Scraper-Key + X-User-Scraper-Provider headers.",
        )

    started = time.perf_counter()
    provider = user_keys.scraper_provider

    try:
        if provider == "firecrawl":
            from backend.integrations import firecrawl as fc
            doc = await asyncio.wait_for(
                fc.scrape_url(_PROBE_URL, api_key_override=user_keys.scraper_key),
                timeout=20.0,
            )
        elif provider == "nimble":
            from backend.integrations import nimble as nb
            doc = await asyncio.wait_for(
                nb.scrape_url(_PROBE_URL, api_key_override=user_keys.scraper_key),
                timeout=20.0,
            )
        else:
            return ValidationResult(
                ok=False,
                error_category="model",
                error=f"Unknown scraper provider: {provider}",
            )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        content_len = len(doc.content_markdown or "")
        log.info(
            "byok.validate.scraper_ok",
            provider=provider,
            latency_ms=elapsed_ms,
            content_length=content_len,
        )
        if content_len < 50:
            return ValidationResult(
                ok=False,
                provider=provider,
                latency_ms=elapsed_ms,
                error_category="other",
                error=f"Scrape succeeded but returned only {content_len} chars",
                detail="Provider key works but the response was suspiciously short.",
            )
        return ValidationResult(
            ok=True,
            provider=provider,
            latency_ms=elapsed_ms,
        )

    except asyncio.TimeoutError:
        return ValidationResult(
            ok=False,
            provider=provider,
            error_category="network",
            error="Scraper didn't respond within 20s",
        )
    except Exception as e:
        category, message, raw = _categorize_scraper_error(e)
        log.warning(
            "byok.validate.scraper_failed",
            provider=provider,
            category=category,
            error=raw[:300],
        )
        return ValidationResult(
            ok=False,
            provider=provider,
            error_category=category,
            error=message,
            detail=raw[:500],
        )
