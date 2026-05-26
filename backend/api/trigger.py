"""POST /api/trigger -- demo-on-demand replacement for the always-on scheduler.

Each request:
  1. (optional) validates a Cloudflare Turnstile token
  2. (optional) extracts BYOK X-User-* headers
  3. (optional) rate-limits when no BYOK key is present
  4. enforces a daily kill-switch on demo-pool LLM calls
  5. INSERTs a synthetic event row into ClickHouse so Impact Analysis picks
     it up on its next cycle (or right away if you POST /api/trigger/run-now)

Scenarios mirror the three trigger paths in docs/ARCHITECTURE.md.

Phase 1 status:
  - All guards are wired.
  - BYOK headers are accepted and parsed into UserKeys.
  - Daily budget + rate limit work.
  - Event rows are written; agents will pick them up.

Phase 2 (separate work):
  - Route UserKeys.llm_key + UserKeys.scraper_key through to the actual LLM
    + scraper calls. Today the agent layer still uses the server-side
    singletons; BYOK users get the rate-limit bypass but the LLM call still
    runs against the server's key. Tracked as a TODO in this file.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.api.security import (
    UserKeys,
    check_and_increment_budget,
    current_budget_state,
    extract_user_keys,
    limiter,
    should_bypass_rate_limit,
    verify_turnstile,
)
from backend.agents.policy_crawler import CrawlVerification, crawl_one
from backend.integrations.clickhouse_client import get_client
from backend.integrations.vertex_ai import vertex_model_for_user
from backend.utils.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["trigger"])


# ════════════════════════════════════════════════════════════════
# Request / response models
# ════════════════════════════════════════════════════════════════

Scenario = Literal[
    "schema_enrichment_fcra",  # column populated -> FCRA Section 605 surfaces
    "dispute_filed",            # behavior event -> TILA 30-day + FCRA flag clocks
    "promo_rate_expiry",        # behavior event -> TILA 45-day promo notice
]


class TriggerRequest(BaseModel):
    scenario: Scenario = Field(
        description="Which demo scenario to fire. See docs/ARCHITECTURE.md section 5."
    )
    account_id: str | None = Field(
        default=None,
        description="For behavior scenarios -- which account triggered the event. Auto-picked if omitted.",
    )


class TriggerResponse(BaseModel):
    trigger_id: str
    scenario: str
    started_at: datetime
    used_byok: bool
    used_byok_scraper: bool
    notes: list[str]
    budget: dict


# ════════════════════════════════════════════════════════════════
# Helpers -- pick a representative account for each behavior scenario
# ════════════════════════════════════════════════════════════════


async def _pick_account_for_scenario(client, scenario: Scenario) -> str | None:
    """Return one cc_accounts.account_id matching the scenario's preconditions."""
    if scenario == "dispute_filed":
        rows = list((await client.query(
            "SELECT account_id FROM regradar.cc_accounts "
            "WHERE dispute_filed = false LIMIT 1"
        )).result_rows)
    elif scenario == "promo_rate_expiry":
        rows = list((await client.query(
            "SELECT account_id FROM regradar.cc_accounts "
            "WHERE promo_rate IS NOT NULL "
            "  AND promo_rate_end_date BETWEEN today() AND today() + 45 LIMIT 1"
        )).result_rows)
    else:
        return None
    return rows[0][0] if rows else None


# ════════════════════════════════════════════════════════════════
# Event writers -- one per scenario
# ════════════════════════════════════════════════════════════════


async def _write_schema_enrichment(client, trigger_id: str, now: datetime) -> None:
    """Schema enrichment: original_delinquency_date column populated.

    Writes to BOTH:
      - schema_events: cloud's narrative event log (event_id, asset_id, field_name, ...)
      - asset_changes: what Impact Analysis polls (change_event_id, change_type, ...)
    """
    await client.insert(
        "regradar.schema_events",
        [[
            trigger_id,                         # event_id (we reuse the trigger_id as primary key)
            "credit_card_accounts",             # asset_id
            "column_populated",                 # event_type
            "original_delinquency_date",        # field_name
            now,                                # detected_at
            6000,                               # rows_affected
            False,                              # triggered_impact_analysis (Impact Analysis flips this)
            "",                                 # impact_report_id (filled by Impact Analysis)
        ]],
        column_names=[
            "event_id", "asset_id", "event_type", "field_name",
            "detected_at", "rows_affected", "triggered_impact_analysis", "impact_report_id",
        ],
    )
    await client.insert(
        "regradar.asset_changes",
        [[
            str(uuid.uuid4()),                                  # change_event_id
            "credit_card_accounts.original_delinquency_date",   # asset_id
            "schema_change",                                    # change_type
            now,                                                # changed_at
            "/api/trigger",                                     # changed_by
            "",                                                 # previous_state_hash
            "",                                                 # new_state_hash
            f'{{"trigger_id": "{trigger_id}", "column": "original_delinquency_date", "event": "column_populated"}}',
        ]],
        column_names=[
            "change_event_id", "asset_id", "change_type", "changed_at",
            "changed_by", "previous_state_hash", "new_state_hash", "change_details",
        ],
    )


async def _write_behavior_event(
    client, trigger_id: str, now: datetime, event_type: str, account_id: str
) -> None:
    """Behavior events (dispute_filed, promo_rate_assigned).

    The cloud doesn't have a behavior_events table, so we write only to
    asset_changes. Impact Analysis polls asset_changes and resolves the
    event_type from change_details JSON.
    """
    await client.insert(
        "regradar.asset_changes",
        [[
            str(uuid.uuid4()),
            f"cc_accounts.{account_id}",
            "classification_change",
            now,
            "/api/trigger",
            "",
            "",
            f'{{"trigger_id": "{trigger_id}", "event_type": "{event_type}", "account_id": "{account_id}"}}',
        ]],
        column_names=[
            "change_event_id", "asset_id", "change_type", "changed_at",
            "changed_by", "previous_state_hash", "new_state_hash", "change_details",
        ],
    )


# ════════════════════════════════════════════════════════════════
# Routes
# ════════════════════════════════════════════════════════════════


@router.get("/trigger/budget")
async def trigger_budget() -> dict:
    """Read-only -- how much demo-pool LLM budget is left today."""
    return current_budget_state()


@router.post("/trigger", response_model=TriggerResponse)
@limiter.limit(os.environ.get("DEMO_API_BURST_LIMIT", "3/minute"))
@limiter.limit(os.environ.get("DEMO_API_RATE_LIMIT", "10/day"))
async def trigger_scenario(
    request: Request,
    payload: TriggerRequest,
    _turnstile_ok: bool = Depends(verify_turnstile),
    user_keys: UserKeys = Depends(extract_user_keys),
) -> TriggerResponse:
    """Fire a demo scenario.

    Guards (in order):
      1. Turnstile token verified (if TURNSTILE_ENABLED).
      2. BYOK headers extracted.
      3. SlowAPI rate limit (skipped when X-User-LLM-Key is present).
      4. Daily kill switch (only when no BYOK key).
      5. INSERT event rows.
    """
    trigger_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    notes: list[str] = []

    if user_keys.has_llm_key:
        notes.append(f"BYOK LLM accepted (provider={user_keys.llm_provider})")
        notes.append("rate limit bypassed; daily budget skipped")
    else:
        notes.append("using server demo pool")

    if user_keys.has_scraper_key:
        notes.append(f"BYOK scraper accepted (provider={user_keys.scraper_provider})")

    client = await get_client()

    # Daily kill switch applies only to demo-pool usage.
    if not should_bypass_rate_limit(user_keys):
        check_and_increment_budget()

    # Write the synthetic event(s) per scenario.
    if payload.scenario == "schema_enrichment_fcra":
        await _write_schema_enrichment(client, trigger_id, now)
        notes.append(
            "wrote schema_events + asset_changes for "
            "credit_card_accounts.original_delinquency_date"
        )
    elif payload.scenario in ("dispute_filed", "promo_rate_expiry"):
        account_id = payload.account_id or await _pick_account_for_scenario(
            client, payload.scenario
        )
        if not account_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"No matching account found for scenario '{payload.scenario}'. "
                    "Run scripts/setup_cc_accounts.py first or pass account_id explicitly."
                ),
            )
        event_type = (
            "dispute_filed" if payload.scenario == "dispute_filed" else "promo_rate_assigned"
        )
        await _write_behavior_event(client, trigger_id, now, event_type, account_id)
        notes.append(
            f"wrote asset_changes for {event_type} on {account_id}"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown scenario '{payload.scenario}'",
        )

    # Note: /api/trigger only inserts an event row -- the Impact Analysis cycle
    # that consumes it is LLM-free (pure SQL evaluators). For actual BYOK LLM
    # passthrough, see POST /api/trigger/crawl below, which runs the Policy
    # Crawler synchronously and routes BYOK keys to the agent + scraper layers.

    log.info(
        "trigger.fired",
        trigger_id=trigger_id,
        scenario=payload.scenario,
        byok_llm=user_keys.has_llm_key,
        byok_scraper=user_keys.has_scraper_key,
    )

    return TriggerResponse(
        trigger_id=trigger_id,
        scenario=payload.scenario,
        started_at=now,
        used_byok=user_keys.has_llm_key,
        used_byok_scraper=user_keys.has_scraper_key,
        notes=notes,
        budget=current_budget_state(),
    )


# ════════════════════════════════════════════════════════════════
# POST /api/trigger/crawl -- end-to-end BYOK demo
#
# Synchronously runs the Policy Crawler on a single regulation.
# When BYOK headers are present, the user's keys flow all the way through:
#   X-User-LLM-Key      -> vertex_model_for_user -> Pydantic AI Agent
#   X-User-Scraper-Key  -> nimble/firecrawl.scrape_url(api_key_override=...)
# ════════════════════════════════════════════════════════════════


class CrawlRequest(BaseModel):
    regulation_id: str = Field(
        default="REG-005",
        description="Which regulation to crawl. Default REG-005 (FCRA Section 605).",
    )


class CrawlResponse(BaseModel):
    trigger_id: str
    regulation_id: str
    started_at: datetime
    elapsed_seconds: float
    used_byok: bool
    used_byok_scraper: bool
    notes: list[str]
    budget: dict
    result: CrawlVerification | None


@router.post("/trigger/crawl", response_model=CrawlResponse)
@limiter.limit(os.environ.get("DEMO_API_BURST_LIMIT", "3/minute"))
@limiter.limit(os.environ.get("DEMO_API_RATE_LIMIT", "10/day"))
async def trigger_crawl(
    request: Request,
    payload: CrawlRequest,
    _turnstile_ok: bool = Depends(verify_turnstile),
    user_keys: UserKeys = Depends(extract_user_keys),
) -> CrawlResponse:
    """Run the Policy Crawler on one regulation, end-to-end, with BYOK passthrough.

    This is where BYOK actually saves money: the user's LLM + scraper keys
    are routed to the actual API calls (not just rate-limit bypass).
    """
    trigger_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc)
    notes: list[str] = []

    # Demo-pool kill switch -- skipped for BYOK users.
    if not should_bypass_rate_limit(user_keys):
        check_and_increment_budget()
        notes.append("using server demo pool (LLM + scraper)")
    else:
        notes.append(
            f"BYOK LLM key routed to provider={user_keys.llm_provider}; "
            "demo budget skipped"
        )

    # Build the per-request LLM model from BYOK headers (None = use singleton).
    llm_model = None
    if user_keys.has_llm_key:
        try:
            llm_model = vertex_model_for_user(
                api_key=user_keys.llm_key,  # type: ignore[arg-type]
                provider=user_keys.llm_provider,  # type: ignore[arg-type]
                model_name=user_keys.llm_model,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if user_keys.llm_model:
            notes.append(f"BYOK LLM model={user_keys.llm_model}")

    # Scraper key passthrough.
    if user_keys.has_scraper_key:
        notes.append(
            f"BYOK scraper key routed to provider={user_keys.scraper_provider}"
        )

    try:
        verification = await crawl_one(
            payload.regulation_id,
            llm_model=llm_model,
            scraper_key=user_keys.scraper_key,
            scraper_provider=user_keys.scraper_provider,
        )
    except Exception as e:
        log.error(
            "trigger.crawl_failed",
            regulation_id=payload.regulation_id,
            error=str(e),
            byok_llm=user_keys.has_llm_key,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Crawl failed: {type(e).__name__}: {e}",
        )

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    if verification is None:
        notes.append("crawl returned None (regulation not found or scrape failed)")
    else:
        notes.append(
            f"crawl OK -- change_type={verification.change_type}, "
            f"material={verification.is_material_change}"
        )

    log.info(
        "trigger.crawl_done",
        trigger_id=trigger_id,
        regulation_id=payload.regulation_id,
        elapsed_sec=round(elapsed, 2),
        byok_llm=user_keys.has_llm_key,
        byok_scraper=user_keys.has_scraper_key,
    )

    return CrawlResponse(
        trigger_id=trigger_id,
        regulation_id=payload.regulation_id,
        started_at=started,
        elapsed_seconds=round(elapsed, 2),
        used_byok=user_keys.has_llm_key,
        used_byok_scraper=user_keys.has_scraper_key,
        notes=notes,
        budget=current_budget_state(),
        result=verification,
    )
