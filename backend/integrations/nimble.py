"""Nimble Web Search Agents Platform integration.

Primary scraping path for the Policy Crawler. Hits regulatory sources
(CFPB, FRB, FTC, Federal Register) and returns structured content.

Failover: if a Nimble call raises NimbleError, the caller invokes
firecrawl as the silent fallback (see firecrawl.py).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal

from nimble_python import Nimble
from pydantic import BaseModel

from backend.utils.logging import get_logger

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Output types
# ════════════════════════════════════════════════════════════════


class ScrapedDocument(BaseModel):
    source_url: str
    content_markdown: str
    content_hash: str
    scraped_at: datetime
    scraper_used: Literal["nimble", "firecrawl"]


class SearchResult(BaseModel):
    url: str
    title: str
    snippet: str
    content_markdown: str | None = None


# ════════════════════════════════════════════════════════════════
# Client
# ════════════════════════════════════════════════════════════════


_CLIENT: Nimble | None = None


def _get_client() -> Nimble:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = Nimble(api_key=os.environ["NIMBLE_API_KEY"])
        log.info("nimble.initialized")
    return _CLIENT


def _client_for(api_key: str | None) -> Nimble:
    """Per-request BYOK client. Falls back to the singleton when no override."""
    if api_key:
        return Nimble(api_key=api_key)
    return _get_client()


async def scrape_url(url: str, *, api_key_override: str | None = None) -> ScrapedDocument:
    """Scrape a single URL via Nimble's /extract endpoint.

    Args:
        url: target URL
        api_key_override: optional user-provided Nimble key (BYOK). When set,
            builds a fresh client per request and bills the user's account
            instead of the server's.

    Returns markdown-formatted content.
    Raises NimbleError on failure -- caller decides whether to fall back to Firecrawl.
    """
    try:
        client = _client_for(api_key_override)
        result = await asyncio.to_thread(
            client.extract,
            url=url,
            formats=["markdown"],
            render=False,
        )
        # ExtractResponse: result.data.markdown
        content = (getattr(result.data, "markdown", None) or "") if getattr(result, "data", None) else ""
        h = sha256(content.encode()).hexdigest()
        log.info(
            "nimble.scrape_success",
            url=url,
            content_length=len(content),
            byok=bool(api_key_override),
        )
        return ScrapedDocument(
            source_url=url,
            content_markdown=content,
            content_hash=h,
            scraped_at=datetime.now(timezone.utc),
            scraper_used="nimble",
        )
    except Exception as e:
        log.error("nimble.scrape_failure", url=url, error=str(e))
        raise NimbleError(str(e)) from e


async def search(
    *,
    query: str,
    num_results: int = 5,
    use_answer: bool = False,
) -> list[SearchResult]:
    """Search the web via Nimble's /search endpoint.

    Args:
        query: search query
        num_results: max results
        use_answer: if True, use Nimble's "Answer" mode ($4/1000 vs $1/1000)
    """
    try:
        result = await asyncio.to_thread(
            _get_client().search,
            query=query,
            num_results=num_results,
            answer=use_answer,
        )
        log.info("nimble.search_success", query=query, n=len(result.results))
        return [
            SearchResult(
                url=r.url,
                title=r.title,
                snippet=r.snippet,
                content_markdown=getattr(r, "content_markdown", None),
            )
            for r in result.results
        ]
    except Exception as e:
        log.error("nimble.search_failure", query=query, error=str(e))
        raise NimbleError(str(e)) from e


class NimbleError(Exception):
    """Raised on Nimble scrape/search failure. Triggers Firecrawl fallback."""
    pass
