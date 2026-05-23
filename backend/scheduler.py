"""
Policy Crawler Scheduler

Polls all 4 regulatory URLs on a fixed interval.
Gemini extraction only fires when content hash changes — no wasted LLM calls.

Run:
    python -m backend.scheduler

Interval is controlled by WATCHER_SCRAPE_INTERVAL_SECONDS in .env (default 300).
"""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from dotenv import load_dotenv

load_dotenv()

from backend.utils.env import get_int, get as env_get
from backend.utils.logging import configure_logging, get_logger
from backend.agents.policy_crawler import run_policy_crawler, get_ch_client
from backend.agents.impact_analysis import run_impact_analysis_agent

configure_logging()
log = get_logger(__name__)

_ch_client = None


def get_shared_client():
    """Reuse a single ClickHouse connection across all scheduler runs."""
    global _ch_client
    if _ch_client is None:
        _ch_client = get_ch_client()
    return _ch_client


async def crawl_job():
    """Single scheduler tick — runs the full crawler against all 4 URLs."""
    started = datetime.now(timezone.utc)
    log.info("scheduler.tick.start", ts=started.isoformat())
    try:
        await run_policy_crawler(clickhouse_client=get_shared_client())
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        log.info("scheduler.tick.done", elapsed_sec=round(elapsed, 2))
    except Exception as exc:
        log.error("scheduler.tick.error", error=str(exc), exc_info=True)


async def impact_analysis_job():
    """Single scheduler tick — runs one impact analysis polling cycle."""
    started = datetime.now(timezone.utc)
    log.info("impact_analysis.tick.start", ts=started.isoformat())
    try:
        result = await run_impact_analysis_agent(clickhouse_client=get_shared_client())
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        log.info(
            "impact_analysis.tick.done",
            elapsed_sec=round(elapsed, 2),
            new_violations=result.new_violations,
            resolved=result.resolved_violations,
            notifications=result.notifications_sent,
        )
    except Exception as exc:
        log.error("impact_analysis.tick.error", error=str(exc), exc_info=True)


def on_job_event(event):
    if event.exception:
        log.error("scheduler.job_failed", job_id=event.job_id, error=str(event.exception))
    else:
        log.info("scheduler.job_ok", job_id=event.job_id)


async def main():
    crawl_interval = get_int("WATCHER_SCRAPE_INTERVAL_SECONDS", default=300)
    impact_interval = get_int("IMPACT_AGENT_POLL_INTERVAL_SECONDS", default=60)
    log.info(
        "scheduler.starting",
        crawl_interval_seconds=crawl_interval,
        impact_interval_seconds=impact_interval,
    )

    scheduler = AsyncIOScheduler()
    scheduler.add_listener(on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    scheduler.add_job(
        crawl_job,
        trigger="interval",
        seconds=crawl_interval,
        id="policy_crawler",
        name="Policy Crawler",
        max_instances=1,
        misfire_grace_time=60,
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.add_job(
        impact_analysis_job,
        trigger="interval",
        seconds=impact_interval,
        id="impact_analysis",
        name="Impact Analysis Agent",
        max_instances=1,          # never overlap — cursor must advance sequentially
        misfire_grace_time=30,
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.start()
    log.info("scheduler.running", interval_seconds=interval_seconds)

    # Graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()
    stop = loop.create_future()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set_result, sig)

    received = await stop
    log.info("scheduler.stopping", signal=received.name)
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
