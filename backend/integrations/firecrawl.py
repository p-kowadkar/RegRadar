"""Firecrawl silent fallback. Used only when Nimble fails."""

import asyncio
import os
from datetime import datetime, timezone
from hashlib import sha256

from firecrawl import FirecrawlApp

from backend.integrations.nimble import ScrapedDocument
from backend.utils.logging import get_logger

log = get_logger(__name__)


_CLIENT: FirecrawlApp | None = None


def _get_client() -> FirecrawlApp:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = FirecrawlApp(api_key=os.environ["FIRECRAWL_API_KEY"])
        log.info("firecrawl.initialized")
    return _CLIENT


def _client_for(api_key: str | None) -> FirecrawlApp:
    """Per-request BYOK client. Falls back to the singleton when no override."""
    if api_key:
        return FirecrawlApp(api_key=api_key)
    return _get_client()


async def scrape_url(url: str, *, api_key_override: str | None = None) -> ScrapedDocument:
    """Same return type as nimble.scrape_url — drop-in fallback.

    Args:
        url: target URL
        api_key_override: optional user-provided Firecrawl key (BYOK)
    """
    try:
        client = _client_for(api_key_override)
        result = await asyncio.to_thread(
            client.scrape_url,
            url,
            params={"formats": ["markdown"]},
        )
        content = result.get("markdown", "")
        h = sha256(content.encode()).hexdigest()
        log.info(
            "firecrawl.fallback_scrape_success",
            url=url,
            content_length=len(content),
            byok=bool(api_key_override),
        )
        return ScrapedDocument(
            source_url=url,
            content_markdown=content,
            content_hash=h,
            scraped_at=datetime.now(timezone.utc),
            scraper_used="firecrawl",
        )
    except Exception as e:
        log.error("firecrawl.fallback_failure", url=url, error=str(e))
        raise
