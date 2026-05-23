"""Async ClickHouse client. All data access goes through repositories.py
which uses this client. Don't bypass.

For agents that are sync internally (e.g. impact_analysis), `get_sync_client()`
is exposed as a per-call factory so concurrent worker threads don't share the
same HTTP session (clickhouse-connect rejects overlapping queries on one client).
"""

import os

import clickhouse_connect
from clickhouse_connect.driver.asyncclient import AsyncClient

from backend.utils.logging import get_logger

log = get_logger(__name__)


_ASYNC_CLIENT: AsyncClient | None = None


async def get_client() -> AsyncClient:
    """Async client (lazy-init). Same client used across all repositories."""
    global _ASYNC_CLIENT
    if _ASYNC_CLIENT is None:
        _ASYNC_CLIENT = await clickhouse_connect.get_async_client(
            host=os.environ["CLICKHOUSE_HOST"],
            port=int(os.environ["CLICKHOUSE_PORT"]),
            username=os.environ["CLICKHOUSE_USER"],
            password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
            secure=os.environ.get("CLICKHOUSE_SECURE", "false").lower() == "true",
            database=os.environ.get("CLICKHOUSE_DATABASE", "regradar"),
        )
        log.info("clickhouse.initialized", host=os.environ["CLICKHOUSE_HOST"])
    return _ASYNC_CLIENT


def get_sync_client():
    """Fresh sync client per call.

    Used by agents that are synchronous internally and by FastAPI handlers
    that don't want to manage an event loop. clickhouse-connect's HTTP client
    can't safely be shared across threads, so we always return a new one.
    """
    return clickhouse_connect.get_client(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.environ.get("CLICKHOUSE_PORT", "8443")),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ.get("CLICKHOUSE_PASSWORD", ""),
        secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
        database=os.environ.get("CLICKHOUSE_DATABASE", "regradar"),
    )
