"""Shared security primitives: Cloudflare Turnstile + BYOK + SlowAPI limiter.

Wired into the /api/trigger endpoint (and any future LLM-touching endpoint).
Every guard is config-gated so local dev works with zero setup.
"""
from __future__ import annotations

import os
import uuid
from typing import Annotated, Literal

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from slowapi import Limiter

from backend.utils.env import get_bool
from backend.utils.logging import get_logger

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Cloudflare Turnstile validator
# ════════════════════════════════════════════════════════════════

_TURNSTILE_SITEVERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(
    request: Request,
    cf_turnstile_response: Annotated[
        str | None, Header(alias="cf-turnstile-response")
    ] = None,
) -> bool:
    """FastAPI dep -- validates a Turnstile token against Cloudflare siteverify.

    No-op when TURNSTILE_ENABLED is false (local dev default).
    Raises HTTP 403 when enabled and token is missing/invalid.
    """
    if not get_bool("TURNSTILE_ENABLED", default=False):
        return True

    secret = os.environ.get("TURNSTILE_SECRET_KEY")
    if not secret:
        log.warning("turnstile.no_secret_configured -- allowing request through")
        return True

    if not cf_turnstile_response:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing Turnstile token (cf-turnstile-response header).",
        )

    client_ip = request.client.host if request.client else ""

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            _TURNSTILE_SITEVERIFY,
            data={
                "secret": secret,
                "response": cf_turnstile_response,
                "remoteip": client_ip,
            },
        )
        body = resp.json()

    if not body.get("success"):
        log.warning(
            "turnstile.verification_failed",
            error_codes=body.get("error-codes"),
            ip=client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Turnstile validation failed: {body.get('error-codes')}",
        )

    return True


# ════════════════════════════════════════════════════════════════
# BYOK header extraction
# ════════════════════════════════════════════════════════════════

LLMProvider = Literal["openrouter", "gemini", "anthropic", "openai"]
ScraperProvider = Literal["firecrawl", "nimble"]

_LLM_PROVIDERS: set[str] = {"openrouter", "gemini", "anthropic", "openai"}
_SCRAPER_PROVIDERS: set[str] = {"firecrawl", "nimble"}


class UserKeys(BaseModel):
    """Optional user-provided keys parsed from X-User-* headers.

    Empty when the request didn't include BYOK headers, BYOK is disabled,
    or a header had an unrecognised provider value.
    """

    llm_key: str | None = None
    llm_provider: LLMProvider | None = None
    llm_model: str | None = None  # provider-specific id, e.g. "anthropic/claude-sonnet-4.5" for openrouter
    scraper_key: str | None = None
    scraper_provider: ScraperProvider | None = None

    @property
    def has_llm_key(self) -> bool:
        return bool(self.llm_key and self.llm_provider)

    @property
    def has_scraper_key(self) -> bool:
        return bool(self.scraper_key and self.scraper_provider)


def _norm_provider(value: str | None, allowed: set[str]) -> str | None:
    if not value:
        return None
    v = value.lower().strip()
    return v if v in allowed else None


def extract_user_keys(
    x_user_llm_key: Annotated[str | None, Header()] = None,
    x_user_llm_provider: Annotated[str | None, Header()] = None,
    x_user_llm_model: Annotated[str | None, Header()] = None,
    x_user_scraper_key: Annotated[str | None, Header()] = None,
    x_user_scraper_provider: Annotated[str | None, Header()] = None,
) -> UserKeys:
    """FastAPI dep -- parses the X-User-* BYOK headers into a UserKeys model."""
    if not get_bool("BYOK_ENABLED", default=True):
        return UserKeys()

    return UserKeys(
        llm_key=x_user_llm_key,
        llm_provider=_norm_provider(x_user_llm_provider, _LLM_PROVIDERS),  # type: ignore[arg-type]
        llm_model=(x_user_llm_model.strip() if x_user_llm_model else None) or None,
        scraper_key=x_user_scraper_key,
        scraper_provider=_norm_provider(x_user_scraper_provider, _SCRAPER_PROVIDERS),  # type: ignore[arg-type]
    )


def should_bypass_rate_limit(user_keys: UserKeys) -> bool:
    """True when the request brought a usable BYOK LLM key and bypass is allowed."""
    if not get_bool("BYOK_BYPASS_RATE_LIMIT", default=True):
        return False
    return user_keys.has_llm_key


# ════════════════════════════════════════════════════════════════
# Shared SlowAPI limiter
#
# `smart_key_func` returns a unique key per request when a BYOK header is
# present -> SlowAPI never throttles BYOK users. Demo-pool users get IP-keyed.
# ════════════════════════════════════════════════════════════════


def smart_key_func(request: Request) -> str:
    """Limiter key: per-IP for demo pool, per-request UUID for BYOK users."""
    if get_bool("BYOK_BYPASS_RATE_LIMIT", default=True):
        if request.headers.get("X-User-LLM-Key"):
            return f"byok:{uuid.uuid4()}"
    # Fallback to client IP (X-Forwarded-For aware via SlowAPI's util)
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


limiter = Limiter(
    key_func=smart_key_func,
    default_limits=[],  # only routes explicitly decorated get limited
    headers_enabled=False,  # /api/trigger/budget exposes counts; skip per-response headers
)


# ════════════════════════════════════════════════════════════════
# Daily LLM call budget (hard kill switch)
# ════════════════════════════════════════════════════════════════

# In-process counter, reset at UTC midnight. Fine for single-instance deploys
# (HF Spaces, single Railway dyno). Move to ClickHouse if you scale out.

from datetime import datetime, timezone

_BUDGET_DATE: str | None = None
_BUDGET_COUNT: int = 0


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def check_and_increment_budget() -> None:
    """Raise HTTP 503 if today's demo-pool LLM calls would exceed the budget."""
    global _BUDGET_DATE, _BUDGET_COUNT
    today = _today_utc()
    if today != _BUDGET_DATE:
        _BUDGET_DATE = today
        _BUDGET_COUNT = 0

    from backend.utils.env import get_int

    budget = get_int("DAILY_LLM_CALL_BUDGET", default=500)
    if _BUDGET_COUNT >= budget:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Daily demo-pool LLM budget exhausted ({_BUDGET_COUNT}/{budget}). "
                "Bring your own key via X-User-LLM-Key header to keep using the demo, "
                "or wait until UTC midnight."
            ),
        )
    _BUDGET_COUNT += 1


def current_budget_state() -> dict:
    """Diagnostic helper for /api/health/budget or similar."""
    from backend.utils.env import get_int

    return {
        "date_utc": _BUDGET_DATE or _today_utc(),
        "used": _BUDGET_COUNT,
        "budget": get_int("DAILY_LLM_CALL_BUDGET", default=500),
    }
