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


def _extract_markdown(result: object) -> str:
    """Pull markdown content out of whatever Firecrawl returned.

    v2 returns a Pydantic Document model with .markdown attribute.
    v1 returned a dict {"markdown": "...", ...}.
    Support both shapes defensively so a future SDK bump doesn't re-break us.
    """
    md = getattr(result, "markdown", None)
    if md is None and isinstance(result, dict):
        md = result.get("markdown", "")
    return md or ""


async def scrape_url(url: str, *, api_key_override: str | None = None) -> ScrapedDocument:
    """Same return type as nimble.scrape_url — drop-in fallback.

    Args:
        url: target URL
        api_key_override: optional user-provided Firecrawl key (BYOK)
    """
    try:
        client = _client_for(api_key_override)
        # firecrawl-py v2 uses client.scrape(url, formats=[...]).
        # v1 used client.scrape_url(url, params={"formats": [...]}).
        # Prefer v2; fall back to v1 if the new method isn't there.
        if hasattr(client, "scrape"):
            result = await asyncio.to_thread(
                client.scrape,
                url,
                formats=["markdown"],
            )
        else:
            result = await asyncio.to_thread(
                client.scrape_url,
                url,
                params={"formats": ["markdown"]},
            )
        content = _extract_markdown(result)
        h = sha256(content.encode()).hexdigest()
        log.info(
            "firecrawl.scrape_success",
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
        log.error("firecrawl.scrape_failure", url=url, error=str(e))
        raise
