"""
Policy Crawler — three skills in sequence, scheduled hourly.

Skill 1: URL Scanner        — Nimble agent fetches raw regulatory text
Skill 2: Condition Extractor — Gemini 2.5-flash extracts structured compliance conditions (1 LLM call)
Skill 3: Embedding Generator — text-embedding-004 chunks + stores vectors in ClickHouse

Only fires downstream (Skills 2 & 3) when content hash has changed.
Writes a policy_changes event on change → triggers the Impact Analysis Agent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Generator

import google.generativeai as genai
from nimble_python import Nimble

from backend.utils.env import get as env_get
from backend.utils.logging import get_logger

log = get_logger(__name__)

NIMBLE_AGENT_ID = "regulatory_policy_scraper_2026_05_23_hzyy7i76"

URL_MANIFEST: list[dict] = [
    {
        "embedding_key": "REG-Z-1026-9G",
        "regulation_id": "TILA-REG-Z-1026-9-G",
        "url": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.9",
        "fallback_url": "https://www.consumerfinance.gov/rules-policy/regulations/1026/9/",
        "section": "1026.9(g)",
        "source": "eCFR",
    },
    {
        "embedding_key": "REG-Z-1026-13",
        "regulation_id": "TILA-REG-Z-1026-13",
        "url": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.13",
        "fallback_url": "https://www.consumerfinance.gov/rules-policy/regulations/1026/13/",
        "section": "1026.13",
        "source": "eCFR",
    },
    {
        "embedding_key": "FCRA-605",
        "regulation_id": "FCRA-15-USC-1681C",
        "url": "https://www.law.cornell.edu/uscode/text/15/1681c",
        "fallback_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1681c",
        "section": "Section 605",
        "source": "Cornell LII",
    },
    {
        "embedding_key": "FCRA-623A",
        "regulation_id": "FCRA-15-USC-1681S-2",
        "url": "https://www.law.cornell.edu/uscode/text/15/1681s-2",
        "fallback_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1681s-2",
        "section": "Section 623(a)",
        "source": "Cornell LII",
    },
]

# ─── Skill 1: URL Scanner (Nimble agent) ─────────────────────────────────────

def _nimble_scrape(url: str) -> dict:
    """Synchronous Nimble agent call. Wrapped in asyncio.to_thread by caller."""
    nimble = Nimble(api_key=env_get("NIMBLE_API_KEY"))
    result = nimble.agent.run(
        agent=NIMBLE_AGENT_ID,
        params={"url": url},
    )
    # result is a dict; extract text from whichever key the agent returns
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


def has_changed(regulation_id: str, new_hash: str, clickhouse_client) -> bool:
    """Return True if content hash differs from last stored version."""
    row = clickhouse_client.query(
        "SELECT content_hash FROM regulatory_documents "
        "WHERE policy_id = %(rid)s "
        "ORDER BY published_date DESC LIMIT 1",
        {"rid": regulation_id},
    ).first_row
    if not row:
        return True
    return row[0] != new_hash


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
    genai.configure(api_key=env_get("GOOGLE_GENAI_API_KEY", os.environ.get("DEEPMIND_API_KEY", "")))
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0,
        },
        system_instruction=_EXTRACTION_SYSTEM_PROMPT,
    )
    prompt = _EXTRACTION_USER_TEMPLATE.format(
        regulation_name=scraped["regulation_id"],
        section=scraped["section"],
        embedding_key=scraped["embedding_key"],
        raw_text=scraped["text"][:8000],
    )
    response = model.generate_content(prompt)
    return json.loads(response.text)


# ─── Skill 3: Embedding Generator (text-embedding-004) ───────────────────────

def chunk_policy_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64,
) -> Generator[str, None, None]:
    """Split on paragraph boundaries then by token budget."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    current_chunk: list[str] = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para.split())
        if current_size + para_size > chunk_size and current_chunk:
            yield " ".join(current_chunk)
            overlap_text = current_chunk[-1] if current_chunk else ""
            current_chunk = [overlap_text, para]
            current_size = len(overlap_text.split()) + para_size
        else:
            current_chunk.append(para)
            current_size += para_size

    if current_chunk:
        yield " ".join(current_chunk)


def generate_embedding(text: str) -> list[float]:
    """Single embedding call. Returns 768-dim vector."""
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document",
        title="Regulatory policy text",
    )
    return result["embedding"]


def embed_and_store(scraped: dict, conditions: dict, clickhouse_client) -> int:
    """Chunk policy text, generate embeddings, insert into ClickHouse. Returns chunk count."""
    chunks = list(chunk_policy_text(scraped["text"]))
    rows = []
    for i, chunk in enumerate(chunks):
        embedding = generate_embedding(chunk)
        rows.append({
            "policy_id":      conditions["regulation_id"],
            "source":         scraped["source"],
            "section":        scraped["section"],
            "chunk_index":    i,
            "chunk_text":     chunk,
            "embedding":      embedding,
            "content_hash":   scraped["content_hash"],
            "version":        conditions["version_date"],
            "published_date": datetime.now(timezone.utc),
        })
    clickhouse_client.insert("regulatory_documents", rows)
    return len(rows)


# ─── Downstream writes ────────────────────────────────────────────────────────

def store_policy_conditions(conditions: dict, ch) -> None:
    for control in conditions["controls"]:
        ch.execute(
            "INSERT INTO governance_controls "
            "(control_id, regulation_id, title, description, "
            " query_template, threshold, owner, frequency, active) VALUES",
            [{
                "control_id":     control["control_id"],
                "regulation_id":  conditions["regulation_id"],
                "title":          control["description"],
                "description":    control["description"],
                "query_template": control["sql_condition"],
                "threshold":      0,
                "owner":          "Compliance Team",
                "frequency":      "daily",
                "active":         True,
            }],
        )


def write_policy_change_event(regulation_id: str, conditions: dict, ch) -> None:
    ch.execute(
        "INSERT INTO policy_changes "
        "(policy_id, new_version, change_summary, processed) VALUES",
        [{
            "policy_id":      regulation_id,
            "new_version":    conditions["version_date"],
            "change_summary": f"Policy updated — {len(conditions['controls'])} controls extracted",
            "processed":      False,
        }],
    )


# ─── Composed crawler ────────────────────────────────────────────────────────

async def run_policy_crawler(clickhouse_client=None) -> None:
    """
    Entry point. Pass an existing ClickHouse client or one will be created
    from env vars.
    """
    import clickhouse_connect

    ch = clickhouse_client or clickhouse_connect.get_client(
        host=env_get("CLICKHOUSE_HOST"),
        port=int(env_get("CLICKHOUSE_PORT", "8123")),
        username=env_get("CLICKHOUSE_USER"),
        password=env_get("CLICKHOUSE_PASSWORD", ""),
        database=env_get("CLICKHOUSE_DATABASE", "regradar"),
    )

    for entry in URL_MANIFEST:
        log.info("crawler.scraping", regulation_id=entry["regulation_id"])
        scraped = await scrape_with_fallback(entry)

        if not has_changed(entry["regulation_id"], scraped["content_hash"], ch):
            log.info("crawler.no_change", regulation_id=entry["regulation_id"])
            continue

        log.info("crawler.change_detected", regulation_id=entry["regulation_id"])

        conditions = extract_compliance_conditions(scraped)
        chunk_count = embed_and_store(scraped, conditions, ch)
        store_policy_conditions(conditions, ch)
        write_policy_change_event(entry["regulation_id"], conditions, ch)

        log.info(
            "crawler.stored",
            regulation_id=entry["regulation_id"],
            chunks=chunk_count,
            controls=len(conditions["controls"]),
        )


if __name__ == "__main__":
    asyncio.run(run_policy_crawler())
