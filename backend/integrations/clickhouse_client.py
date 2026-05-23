"""Async ClickHouse client. All data access goes through repositories.py
which uses this client. Don't bypass."""

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
