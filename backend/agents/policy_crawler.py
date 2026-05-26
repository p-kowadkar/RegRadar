"""
Policy Crawler — scheduled hourly, verifies compliance control parameters
against live regulatory text and writes detected changes to ClickHouse.

Architecture:
  1. Load regulation record from regradar.regulations
  2. Fetch source URL from latest policy_changes row (fallback to hardcoded map)
  3. Scrape via Nimble → Firecrawl fallback (content < 200 chars = treat as failure)
  4. One Pydantic AI / Gemini 3.5 Flash call to verify thresholds against scraped text
  5. Write one policy_changes row; UPDATE regulations.last_crawled_at + version
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import Model

from backend.agents.base import AGENT_POLICY_CRAWLER, agent_run_context
from backend.integrations.clickhouse_client import get_client
from backend.integrations.vertex_ai import vertex_model
from backend.utils.logging import get_logger

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Fallback source URL map (used when no policy_changes row exists)
# ════════════════════════════════════════════════════════════════

_FALLBACK_URLS: dict[str, str] = {
    "REG-001": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.9",
    "REG-002": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.9",
    "REG-003": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.13",
    "REG-004": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.13",
    "REG-005": "https://www.law.cornell.edu/uscode/text/15/1681c",
    "REG-006": "https://www.law.cornell.edu/uscode/text/15/1681s-2",
    "REG-007": "https://www.law.cornell.edu/uscode/text/15/1681s-2",
}


# ════════════════════════════════════════════════════════════════
# Pydantic models
# ════════════════════════════════════════════════════════════════


class RegulationRecord(BaseModel):
    regulation_id: str
    act: str
    reg_code: str
    control_name: str
    threshold_days: int | None
    threshold_label: str
    trigger_type: str
    version: str
    source_url: str


class PolicyCrawlInput(BaseModel):
    regulation: RegulationRecord
    scraped_text: str


class CrawlVerification(BaseModel):
    threshold_days_confirmed: int | None
    threshold_label_confirmed: str
    control_name_confirmed: str
    is_material_change: bool
    change_summary: str
    change_type: Literal[
        "no_change", "threshold_change", "scope_expansion", "clarification", "content_update"
    ]
    new_version: str
    relevant_excerpt: str


# ════════════════════════════════════════════════════════════════
# Agent
# ════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
You are the Policy Crawler agent for RegRadar, a compliance monitoring system for
consumer credit card issuers. Your job is to verify compliance control parameters
against actual regulatory text.

You receive: a regulation record (the current control definition in our database)
and the scraped text from the official regulation source.

You must find the specific section of text that governs the control and verify:
1. The exact threshold (days, amount, or boolean requirement)
2. The exact triggering condition
3. Whether the current database values match what the regulation actually says

Rules:
- ONLY extract what the text explicitly states. Never invent thresholds.
- If the text does not contain the relevant section, set change_summary to
  "Source text did not contain the relevant section" and change_type to "content_update".
- If threshold_days is null in the current record, only set threshold_days_confirmed
  to a number if the text gives an explicit numeric deadline.
- For version: if is_material_change=True bump the patch version (e.g. "4.0" -> "4.1"),
  otherwise return the same version string unchanged.
- Keep change_summary under 200 characters. Be specific: name the section and the value.
- NEVER hallucinate a regulation citation or dollar amount.
"""

def _make_crawler_agent(model: Model | None = None) -> Agent:
    """Build a Pydantic AI Agent bound to either the singleton model or a BYOK override."""
    return Agent(
        model=model or vertex_model("gemini-3.5-flash"),
        output_type=CrawlVerification,
        system_prompt=_SYSTEM_PROMPT,
    )


# Module-level default agent used by the scheduler path.
crawler_agent = _make_crawler_agent()


# ════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════


async def _get_source_url(client, regulation_id: str) -> str:
    """Return source_url from the most recent policy_changes row; fallback to hardcoded map."""
    rows = list((await client.query(
        "SELECT source_url FROM regradar.policy_changes "
        "WHERE regulation_id = {reg_id:String} "
        "ORDER BY detected_at DESC LIMIT 1",
        parameters={"reg_id": regulation_id},
    )).named_results())
    if rows and rows[0].get("source_url"):
        return rows[0]["source_url"]
    url = _FALLBACK_URLS.get(regulation_id)
    if not url:
        raise ValueError(f"No source URL found for {regulation_id}")
    return url


async def _scrape_regulation(
    source_url: str,
    *,
    scraper_key: str | None = None,
    scraper_provider: str | None = None,
) -> str:
    """Scrape via Nimble; fall back to Firecrawl if content is empty or too short.

    If a BYOK scraper_key is provided, route to that provider directly
    (no fallback) so the user's key is honored end-to-end.
    """
    from backend.integrations import nimble, firecrawl
    from backend.integrations.nimble import NimbleError

    # BYOK path: explicit provider, no silent fallback.
    if scraper_key and scraper_provider:
        provider = scraper_provider.lower().strip()
        if provider == "nimble":
            doc = await nimble.scrape_url(url=source_url, api_key_override=scraper_key)
            return doc.content_markdown
        if provider == "firecrawl":
            doc = await firecrawl.scrape_url(url=source_url, api_key_override=scraper_key)
            return doc.content_markdown
        raise ValueError(f"Unknown BYOK scraper provider: {scraper_provider}")

    # Default path: server keys, Nimble -> Firecrawl fallback.
    try:
        doc = await nimble.scrape_url(url=source_url)
        if len(doc.content_markdown.strip()) < 200:
            raise NimbleError("Content too short, likely blocked")
        return doc.content_markdown
    except NimbleError as e:
        log.warning(
            "crawler.nimble_fallback",
            url=source_url,
            reason=str(e),
        )
        doc = await firecrawl.scrape_url(url=source_url)
        return doc.content_markdown


async def _write_policy_change(
    client,
    regulation_id: str,
    prior_version: str,
    verification: CrawlVerification,
    source_url: str,
) -> None:
    """INSERT one row into regradar.policy_changes and UPDATE regulations."""
    content_hash = hashlib.sha256(verification.relevant_excerpt.encode()).hexdigest()

    await client.insert(
        "regradar.policy_changes",
        [[
            str(uuid.uuid4()),              # change_id
            regulation_id,                  # regulation_id
            verification.change_type,       # change_type
            prior_version,                  # prior_version
            content_hash,                   # new_version (hash of excerpt)
            verification.change_summary,    # change_summary
            verification.is_material_change,  # material
            "",                             # impact_asset_ids
            "",                             # impact_report_id
            source_url,                     # source_url
        ]],
        column_names=[
            "change_id", "regulation_id", "change_type", "prior_version",
            "new_version", "change_summary", "material", "impact_asset_ids",
            "impact_report_id", "source_url",
        ],
    )

    # Stamp last_crawled_at and bump version on the regulations row.
    # SharedMergeTree (ClickHouse Cloud) supports mutations via ALTER UPDATE.
    await client.command(
        "ALTER TABLE regradar.regulations UPDATE "
        "last_crawled_at = now(), version = {ver:String} "
        "WHERE regulation_id = {reg_id:String}",
        parameters={"ver": verification.new_version, "reg_id": regulation_id},
    )


# ════════════════════════════════════════════════════════════════
# Public API
# ════════════════════════════════════════════════════════════════


async def crawl_one(
    regulation_id: str,
    *,
    llm_model: Model | None = None,
    scraper_key: str | None = None,
    scraper_provider: str | None = None,
) -> CrawlVerification | None:
    """Crawl a single regulation. Returns None if scraping failed entirely.

    BYOK overrides:
      llm_model: replace the default crawler_agent's model with one bound to
                 the user's LLM key (built via vertex_model_for_user).
      scraper_key + scraper_provider: route Nimble/Firecrawl through the
                 user's scraper key directly (no fallback chain).
    """
    agent = crawler_agent if llm_model is None else _make_crawler_agent(llm_model)

    async with agent_run_context(agent_id=AGENT_POLICY_CRAWLER, trigger_id=regulation_id):
        client = await get_client()

        # 1. Load regulation record
        rows = list((await client.query(
            "SELECT regulation_id, act, reg_code, control_name, threshold_days, "
            "threshold_label, trigger_type, version "
            "FROM regradar.regulations WHERE regulation_id = {reg_id:String}",
            parameters={"reg_id": regulation_id},
        )).named_results())
        if not rows:
            log.error("crawler.regulation_not_found", regulation_id=regulation_id)
            return None
        row = rows[0]

        # 2. Resolve source URL
        source_url = await _get_source_url(client, regulation_id)

        # 3. Scrape (Nimble → Firecrawl, or BYOK provider when specified)
        try:
            text = await _scrape_regulation(
                source_url,
                scraper_key=scraper_key,
                scraper_provider=scraper_provider,
            )
        except Exception as e:
            log.error("crawler.scrape_failed", regulation_id=regulation_id, error=str(e))
            await _write_policy_change(
                client,
                regulation_id,
                row["version"],
                CrawlVerification(
                    threshold_days_confirmed=row["threshold_days"],
                    threshold_label_confirmed=row["threshold_label"],
                    control_name_confirmed=row["control_name"],
                    is_material_change=False,
                    change_summary="Scrape failed — source URL unreachable",
                    change_type="content_update",
                    new_version=row["version"],
                    relevant_excerpt="",
                ),
                source_url,
            )
            return None

        # 4. LLM verification
        reg_record = RegulationRecord(
            regulation_id=regulation_id,
            act=row["act"],
            reg_code=row["reg_code"],
            control_name=row["control_name"],
            threshold_days=row["threshold_days"],
            threshold_label=row["threshold_label"],
            trigger_type=row["trigger_type"],
            version=row["version"],
            source_url=source_url,
        )
        result = await agent.run(
            PolicyCrawlInput(
                regulation=reg_record, scraped_text=text[:8000]
            ).model_dump_json()
        )
        verification = result.output

        # 5. Write policy_change row + update regulations
        await _write_policy_change(client, regulation_id, row["version"], verification, source_url)

        log.info(
            "crawler.regulation_done",
            regulation_id=regulation_id,
            material=verification.is_material_change,
            change_type=verification.change_type,
            summary=verification.change_summary,
        )
        return verification


async def crawl_all() -> dict[str, CrawlVerification | None]:
    """Crawl all 7 regulations sequentially. Returns dict of regulation_id -> result."""
    client = await get_client()
    rows = list((await client.query(
        "SELECT regulation_id FROM regradar.regulations ORDER BY regulation_id",
    )).named_results())
    reg_ids = [r["regulation_id"] for r in rows]

    results: dict[str, CrawlVerification | None] = {}
    for reg_id in reg_ids:
        results[reg_id] = await crawl_one(reg_id)
        await asyncio.sleep(1)
    return results


async def policy_crawler_loop() -> None:
    """Scheduled hourly loop. Called from backend/main.py lifespan."""
    log.info("crawler.loop_started", interval_seconds=3600)
    while True:
        log.info("crawler.cycle_start")
        try:
            results = await crawl_all()
            material_count = sum(
                1 for v in results.values() if v and v.is_material_change
            )
            log.info(
                "crawler.cycle_done",
                total=len(results),
                material_changes=material_count,
            )
        except Exception as e:
            log.error("crawler.cycle_failed", error=str(e))
        await asyncio.sleep(3600)


if __name__ == "__main__":
    # One-shot crawl across all regulations. Use scheduler.py for the loop.
    async def _main() -> None:
        results = await crawl_all()
        material = sum(1 for v in results.values() if v and v.is_material_change)
        log.info(
            "crawler.standalone_done",
            total=len(results),
            material_changes=material,
        )

    asyncio.run(_main())
