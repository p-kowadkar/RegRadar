"""
RegRadar agent scheduler.

Runs Policy Crawler (hourly default) + Impact Analysis (60s default) on
fixed intervals. Both agents share the lazy async ClickHouse client from
backend.integrations.clickhouse_client.

Run:
    python -m backend.scheduler
"""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

from backend.utils.env import get_int  # noqa: E402
from backend.utils.logging import configure_logging, get_logger  # noqa: E402
from backend.agents.policy_crawler import crawl_all  # noqa: E402
from backend.agents.impact_analysis import run_impact_analysis_agent  # noqa: E402

configure_logging()
log = get_logger(__name__)


async def crawl_job() -> None:
    """One scheduler tick of the Policy Crawler."""
    started = datetime.now(timezone.utc)
    log.info("scheduler.crawl.start", ts=started.isoformat())
    try:
        results = await crawl_all()
        material = sum(1 for v in results.values() if v and v.is_material_change)
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        log.info(
            "scheduler.crawl.done",
            elapsed_sec=round(elapsed, 2),
            total=len(results),
            material_changes=material,
        )
    except Exception as exc:
        log.error("scheduler.crawl.error", error=str(exc), exc_info=True)


async def impact_analysis_job() -> None:
    """One scheduler tick of the Impact Analysis Agent."""
    started = datetime.now(timezone.utc)
    log.info("scheduler.impact.start", ts=started.isoformat())
    try:
        result = await run_impact_analysis_agent()
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        log.info(
            "scheduler.impact.done",
            elapsed_sec=round(elapsed, 2),
            new_violations=result.new_violations,
            resolved=result.resolved_violations,
            notifications=result.notifications_sent,
        )
    except Exception as exc:
        log.error("scheduler.impact.error", error=str(exc), exc_info=True)


def on_job_event(event):
    if event.exception:
        log.error("scheduler.job_failed", job_id=event.job_id, error=str(event.exception))
    else:
        log.info("scheduler.job_ok", job_id=event.job_id)


async def main() -> None:
    crawl_interval = get_int("WATCHER_SCRAPE_INTERVAL_SECONDS", default=3600)
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
        max_instances=1,  # never overlap -- cursor must advance sequentially
        misfire_grace_time=30,
        next_run_time=datetime.now(timezone.utc),
    )

    scheduler.start()
    log.info(
        "scheduler.running",
        crawl_interval_seconds=crawl_interval,
        impact_interval_seconds=impact_interval,
    )

    # Graceful shutdown on SIGINT / SIGTERM
    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set_result, sig)

    received = await stop
    log.info("scheduler.stopping", signal=getattr(received, "name", str(received)))
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(main())
