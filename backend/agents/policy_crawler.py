"""
Policy Crawler — three skills in sequence, scheduled hourly.

Skill 1: URL Scanner        — Nimble agent fetches raw regulatory text
Skill 2: Condition Extractor — Gemini 2.5-flash extracts structured compliance conditions (1 LLM call)
Skill 3: DB Writer          — updates regradar.regulations + writes regradar.policy_changes

Live ClickHouse schema (cloud):
  regulations   — one row per control; reg_code links URL manifest to DB rows
  policy_changes — one row per detected change; triggers Impact Analysis Agent

Embeddings skipped for now (no target table in cloud schema).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Generator

import clickhouse_connect
import google.generativeai as genai
from nimble_python import Nimble

from backend.utils.env import get as env_get
from backend.utils.logging import get_logger

log = get_logger(__name__)

NIMBLE_AGENT_ID = "regulatory_policy_scraper_2026_05_23_hzyy7i76"

# Maps embedding_key → reg_code stored in regradar.regulations
URL_MANIFEST: list[dict] = [
    {
        "embedding_key": "REG-Z-1026-9G",
        "reg_code": "Reg Z 1026.9(g)",
        "url": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.9",
        "fallback_url": "https://www.consumerfinance.gov/rules-policy/regulations/1026/9/",
        "section": "1026.9(g)",
        "source": "eCFR",
    },
    {
        "embedding_key": "REG-Z-1026-13",
        "reg_code": "Reg Z 1026.13",
        "url": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.13",
        "fallback_url": "https://www.consumerfinance.gov/rules-policy/regulations/1026/13/",
        "section": "1026.13",
        "source": "eCFR",
    },
    {
        "embedding_key": "FCRA-605",
        "reg_code": "FCRA Section 605",
        "url": "https://www.law.cornell.edu/uscode/text/15/1681c",
        "fallback_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1681c",
        "section": "Section 605",
        "source": "Cornell LII",
    },
    {
        "embedding_key": "FCRA-623A",
        "reg_code": "FCRA Section 623(a)",
        "url": "https://www.law.cornell.edu/uscode/text/15/1681s-2",
        "fallback_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1681s-2",
        "section": "Section 623(a)",
        "source": "Cornell LII",
    },
]


# ─── ClickHouse client ────────────────────────────────────────────────────────

def get_ch_client():
    return clickhouse_connect.get_client(
        host=env_get("CLICKHOUSE_HOST"),
        port=int(env_get("CLICKHOUSE_PORT", "8443")),
        username=env_get("CLICKHOUSE_USER", "default"),
        password=env_get("CLICKHOUSE_PASSWORD", ""),
        secure=env_get("CLICKHOUSE_SECURE", "true").lower() == "true",
        database=env_get("CLICKHOUSE_DATABASE", "regradar"),
    )


# ─── Skill 1: URL Scanner (Nimble agent) ─────────────────────────────────────

def _nimble_scrape(url: str) -> dict:
    """Synchronous Nimble agent call. Wrapped in asyncio.to_thread by caller."""
    nimble = Nimble(api_key=env_get("NIMBLE_API_KEY"))
    result = nimble.agent.run(
        agent=NIMBLE_AGENT_ID,
        params={"url": url},
    )
    text = (
        result.get("text")
        or result.get("content")
        or result.get("html_text")
        or ""
    )
    return {
        "text": text,
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


async def scrape_url(url: str) -> dict:
    """Async wrapper — runs the blocking Nimble call in a thread."""
    return await asyncio.to_thread(_nimble_scrape, url)


async def scrape_with_fallback(entry: dict) -> dict:
    """Try primary URL; fall back to secondary on any failure."""
    try:
        result = await scrape_url(entry["url"])
        result["url_used"] = entry["url"]
    except Exception as exc:
        log.warning("nimble.primary_failed", url=entry["url"], error=str(exc))
        result = await scrape_url(entry["fallback_url"])
        result["url_used"] = entry["fallback_url"]
    result.update(entry)
    return result


# ─── Change detection ─────────────────────────────────────────────────────────

def get_regulation_ids_for_reg_code(reg_code: str, ch) -> list[str]:
    """Return all regulation_ids (e.g. REG-001, REG-002) for a given reg_code."""
    result = ch.query(
        "SELECT regulation_id FROM regradar.regulations WHERE reg_code = {reg_code:String}",
        parameters={"reg_code": reg_code},
    )
    return [row[0] for row in result.result_rows]


def get_last_content_hash(regulation_id: str, ch) -> str | None:
    """Return the most recently stored content hash from policy_changes, or None."""
    result = ch.query(
        "SELECT new_version FROM regradar.policy_changes "
        "WHERE regulation_id = {rid:String} "
        "ORDER BY detected_at DESC LIMIT 1",
        parameters={"rid": regulation_id},
    )
    rows = result.result_rows
    return rows[0][0] if rows else None


def has_changed(reg_code: str, new_hash: str, ch) -> bool:
    """Return True if content hash differs from last stored version for any row in this reg_code."""
    regulation_ids = get_regulation_ids_for_reg_code(reg_code, ch)
    if not regulation_ids:
        return True
    last_hash = get_last_content_hash(regulation_ids[0], ch)
    return last_hash != new_hash


# ─── Skill 2: Condition Extractor (Gemini 2.5-flash) ─────────────────────────

_EXTRACTION_SYSTEM_PROMPT = """
You are a regulatory compliance engineer. Your job is to read raw regulatory
text and extract precise, machine-executable compliance conditions.

You must return valid JSON only. No preamble, no markdown, no explanation.

For each compliance control in the text, extract:
- control_id: short snake_case identifier
- description: one sentence plain English
- trigger_type: one of [behavior, schema_change, time_based]
- trigger_field: the account field that triggers this check
- trigger_value: the value or condition that fires the trigger
- compliance_conditions: array of {field, operator, value, unit}
- account_scope: array of account types this applies to
- threshold_days: integer if time-based, null otherwise
- sql_condition: the WHERE clause that identifies non-compliant accounts
- controls_covered: array of control names this embedding covers
"""

_EXTRACTION_USER_TEMPLATE = """
Regulation: {regulation_name}
Section: {section}
Embedding key: {embedding_key}

Raw regulatory text:
---
{raw_text}
---

Extract all compliance controls. Map to fields in this credit card account schema:
- account_id, account_type, state
- days_past_due, payment_status
- penalty_rate_applied, penalty_notice_sent_date, rate_change_date
- promo_rate_end_date, promo_notice_sent_date
- dispute_filed, dispute_filed_date, dispute_acknowledged_date, dispute_resolved_date
- bureau_reported_status, bureau_dispute_flag
- original_delinquency_date, charged_off, bureau_still_reporting
- applicable_policies (Array of strings)

Return JSON matching this schema:
{{
  "regulation_id": string,
  "regulation_name": string,
  "section": string,
  "embedding_key": string,
  "version_date": string (ISO date),
  "controls": [
    {{
      "control_id": string,
      "description": string,
      "trigger_type": "behavior" | "schema_change" | "time_based",
      "trigger_field": string,
      "trigger_value": string,
      "compliance_conditions": [
        {{ "field": string, "operator": string, "value": string, "unit": string | null }}
      ],
      "account_scope": [string],
      "threshold_days": integer | null,
      "sql_condition": string,
      "controls_covered": [string]
    }}
  ]
}}
"""


def extract_compliance_conditions(scraped: dict) -> dict:
    """One LLM call per regulation section. Returns structured compliance conditions."""
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("DEEPMIND_API_KEY", "")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0,
        },
        system_instruction=_EXTRACTION_SYSTEM_PROMPT,
    )
    prompt = _EXTRACTION_USER_TEMPLATE.format(
        regulation_name=scraped["reg_code"],
        section=scraped["section"],
        embedding_key=scraped["embedding_key"],
        raw_text=scraped["text"][:8000],
    )
    response = model.generate_content(prompt)
    return json.loads(response.text)


# ─── Skill 3: DB Writer ───────────────────────────────────────────────────────

def update_last_crawled(reg_code: str, ch) -> None:
    """Stamp last_crawled_at on every regulation row for this reg_code."""
    ch.command(
        "ALTER TABLE regradar.regulations UPDATE last_crawled_at = {now:DateTime} "
        "WHERE reg_code = {reg_code:String}",
        parameters={
            "now": datetime.now(timezone.utc).replace(tzinfo=None),
            "reg_code": reg_code,
        },
    )


def write_policy_changes(
    reg_code: str,
    new_hash: str,
    source_url: str,
    conditions: dict,
    ch,
) -> None:
    """Insert one policy_changes row per regulation_id covered by this reg_code."""
    regulation_ids = get_regulation_ids_for_reg_code(reg_code, ch)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for regulation_id in regulation_ids:
        prior_hash = get_last_content_hash(regulation_id, ch) or ""
        rows.append([
            str(uuid.uuid4()),   # change_id
            regulation_id,       # regulation_id
            now,                 # detected_at
            "content_update" if prior_hash else "initial_ingest",  # change_type
            prior_hash,          # prior_version
            new_hash,            # new_version (content hash)
            f"Policy crawled — {len(conditions.get('controls', []))} controls extracted",  # change_summary
            True,                # material
            "",                  # impact_asset_ids
            "",                  # impact_report_id
            source_url,          # source_url
        ])

    ch.insert(
        "regradar.policy_changes",
        rows,
        column_names=[
            "change_id", "regulation_id", "detected_at", "change_type",
            "prior_version", "new_version", "change_summary", "material",
            "impact_asset_ids", "impact_report_id", "source_url",
        ],
    )


# ─── Composed crawler ─────────────────────────────────────────────────────────

async def run_policy_crawler(clickhouse_client=None) -> None:
    """Entry point. Pass an existing ClickHouse client or one is created from env."""
    ch = clickhouse_client or get_ch_client()

    for entry in URL_MANIFEST:
        log.info("crawler.scraping", reg_code=entry["reg_code"])
        scraped = await scrape_with_fallback(entry)

        # Always stamp last_crawled_at
        update_last_crawled(entry["reg_code"], ch)

        if not has_changed(entry["reg_code"], scraped["content_hash"], ch):
            log.info("crawler.no_change", reg_code=entry["reg_code"])
            continue

        log.info("crawler.change_detected", reg_code=entry["reg_code"])

        # One LLM call to extract compliance conditions
        conditions = extract_compliance_conditions(scraped)

        # Write policy_changes for each regulation_id covered by this reg_code
        write_policy_changes(
            entry["reg_code"],
            scraped["content_hash"],
            scraped["url_used"],
            conditions,
            ch,
        )

        regulation_ids = get_regulation_ids_for_reg_code(entry["reg_code"], ch)
        log.info(
            "crawler.stored",
            reg_code=entry["reg_code"],
            regulation_ids=regulation_ids,
            controls=len(conditions.get("controls", [])),
        )


if __name__ == "__main__":
    asyncio.run(run_policy_crawler())
