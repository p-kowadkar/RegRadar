# INTEGRATIONS.md

How each external service connects to RegRadar. Every integration is a file in `backend/integrations/`. Every integration is async, singleton + lazy-init, structured-logged, and Pydantic-typed on the boundary.

---

## Table of Contents

1. [Vertex AI -- Gemini + Check Grounding](#1-vertex-ai----gemini--check-grounding)
2. [OpenRouter -- LLM Fallback](#2-openrouter----llm-fallback)
3. [ClickHouse -- Data Layer](#3-clickhouse----data-layer)
4. [Nimble -- Web Search Agents (primary scraping)](#4-nimble----web-search-agents-primary-scraping)
5. [Firecrawl -- Silent Fallback Scraper](#5-firecrawl----silent-fallback-scraper)
6. [Datadog -- LLM Observability + Control Alerts](#6-datadog----llm-observability--control-alerts)
7. [Senso -- Publish to cited.md](#7-senso----publish-to-citedmd)
8. [x402 -- USDC Micropayments for Compliance Briefs](#8-x402----usdc-micropayments-for-compliance-briefs)
9. [Cross-Cutting: The Integration Contract](#9-cross-cutting-the-integration-contract)

---

## 1. Vertex AI -- Gemini + Check Grounding

**File:** `backend/integrations/vertex_ai.py`

**Purpose:** Sole entry point for Pydantic AI's Vertex provider AND the Check Grounding API. Every other module imports from here. Centralization is what lets ddtrace auto-instrumentation capture every LLM call uniformly.

### Setup

```bash
pip install --upgrade pydantic-ai google-genai google-cloud-discoveryengine
gcloud auth application-default login
gcloud config set project gen-lang-client-0677154031
```

### Environment Variables Used

| Var | Required | Example |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | yes | `gen-lang-client-0677154031` |
| `GOOGLE_CLOUD_LOCATION` | yes | `us-central1` |
| `GOOGLE_GENAI_USE_VERTEXAI` | yes | `True` |
| `GEMINI_MODEL_DEFAULT` | no | default `gemini-3.5-flash` |
| `GEMINI_MODEL_REASONING` | no | default `gemini-3.1-pro` (used by Auditor) |
| `GEMINI_EMBEDDING_MODEL` | no | default `gemini-embedding-001` |
| `GEMINI_API_KEY` | no | for quick scripts (ADC preferred for app) |

### Interface

```python
# backend/integrations/vertex_ai.py
"""Vertex AI integration: Pydantic AI model wrapper + embeddings + Check Grounding."""

from __future__ import annotations

import os
from typing import Any

from google import genai
from google.cloud import discoveryengine_v1
from pydantic import BaseModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google_vertex import GoogleVertexProvider

from backend.utils.logging import get_logger

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Pydantic AI provider (lazy singleton)
# ════════════════════════════════════════════════════════════════

_PROVIDER: GoogleVertexProvider | None = None
_GENAI_CLIENT: genai.Client | None = None
_GROUNDING_CLIENT: discoveryengine_v1.GroundedGenerationServiceAsyncClient | None = None


def _get_provider() -> GoogleVertexProvider:
    """Pydantic AI's Vertex provider. Used to build typed agents."""
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = GoogleVertexProvider(
            project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
            region=os.environ["GOOGLE_CLOUD_LOCATION"],
        )
        log.info("vertex_ai.provider_initialized")
    return _PROVIDER


def vertex_model(model_name: str | None = None) -> GoogleModel:
    """
    Returns a Pydantic AI GoogleModel for a Vertex AI Gemini model.

    Args:
        model_name: e.g. "gemini-3.5-flash" or "gemini-3.1-pro".
                    Defaults to env var GEMINI_MODEL_DEFAULT.
    """
    model_name = model_name or os.environ.get("GEMINI_MODEL_DEFAULT", "gemini-3.5-flash")
    return GoogleModel(model_name=model_name, provider=_get_provider())


# ════════════════════════════════════════════════════════════════
# Direct google-genai client (for embeddings + grounded search)
# Used outside Pydantic AI agents -- e.g., the Policy Crawler's
# regulation-text embedding step.
# ════════════════════════════════════════════════════════════════


def _get_genai_client() -> genai.Client:
    global _GENAI_CLIENT
    if _GENAI_CLIENT is None:
        _GENAI_CLIENT = genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ["GOOGLE_CLOUD_LOCATION"],
        )
        log.info("vertex_ai.genai_client_initialized")
    return _GENAI_CLIENT


async def embed_text(
    *,
    text: str,
    model: str | None = None,
    output_dim: int = 768,
) -> list[float]:
    """
    Embed text via gemini-embedding-001 with Matryoshka truncation.

    output_dim must be one of: 768, 1536, 3072 (the natively-supported
    Matryoshka prefixes).
    """
    model = model or os.environ.get("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    client = _get_genai_client()
    response = await client.aio.models.embed_content(
        model=model,
        contents=text,
        config={"output_dimensionality": output_dim},
    )
    return response.embeddings[0].values


# ════════════════════════════════════════════════════════════════
# Vertex AI Check Grounding (the Auditor's spine)
# ════════════════════════════════════════════════════════════════


class GroundingCitation(BaseModel):
    source_id: str
    confidence: float
    supporting_text: str


class GroundingResult(BaseModel):
    claim: str
    is_grounded: bool
    overall_confidence: float
    citations: list[GroundingCitation]


async def check_grounding(*, claim: str, sources: list[str]) -> GroundingResult:
    """
    Call the Vertex AI Check Grounding API to verify a claim against sources.

    Returns a confidence score in [0, 1] and per-citation supporting text.
    Used exclusively by the Auditor agent.

    See: https://cloud.google.com/generative-ai-app-builder/docs/check-grounding
    """
    global _GROUNDING_CLIENT
    if _GROUNDING_CLIENT is None:
        _GROUNDING_CLIENT = discoveryengine_v1.GroundedGenerationServiceAsyncClient()

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    parent = f"projects/{project}/locations/global"

    request = discoveryengine_v1.CheckGroundingRequest(
        grounding_config=f"{parent}/groundingConfigs/default_grounding_config",
        answer_candidate=claim,
        facts=[
            discoveryengine_v1.GroundingFact(
                fact_text=src,
                attributes={"source_id": f"src_{i}"},
            )
            for i, src in enumerate(sources)
        ],
        grounding_spec=discoveryengine_v1.CheckGroundingSpec(citation_threshold=0.6),
    )

    response = await _GROUNDING_CLIENT.check_grounding(request=request)
    log.info(
        "vertex_ai.grounding_check",
        confidence=response.support_score,
        is_grounded=response.support_score >= 0.65,
        n_citations=len(response.cited_chunks),
    )
    return GroundingResult(
        claim=claim,
        is_grounded=response.support_score >= 0.65,
        overall_confidence=response.support_score,
        citations=[
            GroundingCitation(
                source_id=c.sources[0].source_id if c.sources else "unknown",
                confidence=getattr(c, "score", 0.0),
                supporting_text=getattr(c, "text", ""),
            )
            for c in response.cited_chunks
        ],
    )
```

### Why Pydantic AI Vertex provider (not raw `google-genai`)

Pydantic AI wraps `google-genai` and adds:
- Typed input/output via Pydantic models
- Tool calling via `@agent.tool` decorator
- Native async support
- ddtrace auto-instrumentation hooks
- Conversation history management

Each of the 3 LLM-using agents (`policy_crawler`, `impact_analysis`, `auditor`) is a Pydantic AI `Agent` instance using `vertex_model(...)` as its underlying model. See [AGENTS.md](AGENTS.md) for the full agent definitions.

### Failure modes & fallback

| Failure | Detection | Action |
|---|---|---|
| Rate limit (429) | `google.api_core.exceptions.ResourceExhausted` | Retry 2x w/ exp backoff, then fall back to OpenRouter |
| Quota exceeded | `ResourceExhausted` w/ quota code | Log + fall back to OpenRouter immediately |
| Timeout (>30s) | `asyncio.TimeoutError` | Retry once, then fall back |
| Invalid response schema | Pydantic `ValidationError` | Re-prompt with stricter instructions, then mark agent output `confidence=0` |

Pydantic AI handles structured-output parsing automatically; if Gemini's JSON doesn't validate against the declared `output_type`, it auto-retries with the schema in the prompt.

### Datadog hooks

`ddtrace>=4.8` auto-instruments `pydantic-ai>=1.63` AND `google-genai>=2.0`. Every agent run becomes an LLM Obs span. Every tool call becomes a child span. Pydantic AI agents show as nodes in the AI Agent Console. No manual instrumentation required.

---

## 2. OpenRouter -- LLM Fallback

**File:** `backend/integrations/openrouter.py`

**Purpose:** Used ONLY when Vertex AI fails (rate limit, quota, timeout). Never the primary path. The demo never mentions OpenRouter -- it's resilience insurance.

### Setup

```bash
# OpenRouter uses OpenAI-compatible API; openai SDK already in requirements.txt
```

### Environment Variables

| Var | Required | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | yes | From [openrouter.ai/keys](https://openrouter.ai/keys) |
| `OPENROUTER_BASE_URL` | no | Default `https://openrouter.ai/api/v1` |

### Interface

```python
# backend/integrations/openrouter.py
"""OpenRouter fallback. Used only when Vertex AI rate-limits or times out."""

import os
from openai import AsyncOpenAI
from backend.utils.logging import get_logger

log = get_logger(__name__)


# Vertex AI name -> OpenRouter name
MODEL_MAP = {
    "gemini-3.5-flash": "google/gemini-3.5-flash",
    "gemini-3.1-pro": "google/gemini-3.1-pro",
}


_CLIENT: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = AsyncOpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        )
        log.info("openrouter.initialized")
    return _CLIENT


async def generate_fallback(
    *,
    model: str,
    system_prompt: str | None,
    user_prompt: str,
    max_tokens: int = 2048,
    response_format: dict | None = None,
) -> str:
    """
    Fallback LLM call. Returns raw text only (no Pydantic parsing).
    Parsing happens upstream in the Pydantic AI agent that's wrapping the fallback.
    """
    or_model = MODEL_MAP.get(model, model)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    response = await _get_client().chat.completions.create(
        model=or_model,
        messages=messages,
        max_tokens=max_tokens,
        response_format=response_format,
    )
    log.info("openrouter.fallback_success", model=or_model, tokens=response.usage.total_tokens)
    return response.choices[0].message.content
```

### Fallback decision logic

Wrap each agent run with a try/except that intercepts Vertex AI rate-limit / quota / timeout errors and re-runs via OpenRouter. See `backend/agents/policy_crawler.py` and others for the exact pattern.

---

## 3. ClickHouse -- Data Layer

**File:** `backend/integrations/clickhouse_client.py`

**Purpose:** Sole data layer. Credit card accounts + embeddings + policy_changes + schema_events + behavior_events + impact_reports + auditor_verdicts + compliance_scans + published_briefs + dd_alerts + x402_fetches -- all here.

### Setup

```bash
pip install "clickhouse-connect[arrow]>=0.8.0"   # 0.8+ for 25.8 vector_similarity index
```

### Environment Variables

| Var | Required | Example |
|---|---|---|
| `CLICKHOUSE_HOST` | yes | `localhost` or `xxx.us-east-1.aws.clickhouse.cloud` |
| `CLICKHOUSE_PORT` | yes | `8123` (HTTP) or `8443` (HTTPS Cloud) |
| `CLICKHOUSE_USER` | yes | `default` |
| `CLICKHOUSE_PASSWORD` | no | empty for local |
| `CLICKHOUSE_SECURE` | no | `false` for local, `true` for Cloud |
| `CLICKHOUSE_DATABASE` | no | default `regradar` |

### Interface

```python
# backend/integrations/clickhouse_client.py
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
```

### Vector search quirk (25.8+)

The `vector_similarity` index type with HNSW is GA in ClickHouse 25.8. Two things you must do:

1. **Cast the query vector to `Array(Float32)`** -- otherwise the index isn't used:

```sql
SELECT cosineDistance(embedding, [0.1, 0.2, ...]::Array(Float32)) AS dist
FROM policy_embeddings ORDER BY dist LIMIT 5;
```

2. **Don't use deprecated index types.** ClickHouse 25.8 removed `annoy` and `usearch` -- use only `TYPE vector_similarity('hnsw', '<distance>', <dim>)`:

```sql
ALTER TABLE policy_embeddings
ADD INDEX embedding_hnsw_idx embedding
TYPE vector_similarity('hnsw', 'cosineDistance', 768)
GRANULARITY 1;
```

### Connection pooling

`clickhouse-connect` handles HTTP connection pooling internally. Default pool size of 8 is fine for hackathon scope.

---

## 4. Nimble -- Web Search Agents (primary scraping)

**File:** `backend/integrations/nimble.py`

**Purpose:** Primary regulatory scraper for the Policy Crawler. Hits CFPB, FRB, FTC, Federal Register, state regulators. Returns structured content.

### Why Nimble specifically

Nimble raised a $47M Series B in Feb 2026 and repositioned from "scraping API" to **Web Search Agents Platform** -- competing with Exa, Tavily, Parallel. Their pitch: AI agents searching the web in real-time with verification + structured output. This is exactly our use case for the Policy Crawler. The platform offers:

- `/search` -- $1 per 1,000 search inputs
- `/search` with `answer=true` -- $4 per 1,000 (LLM-grounded reasoning over results)
- `/extract` -- structured data from any URL
- `/crawl` -- multi-page expansion from a seed URL
- `/map` -- domain tree for discovery

### Setup

```bash
pip install "nimble-sdk>=1.0.0"
```

### Environment Variables

| Var | Required | Notes |
|---|---|---|
| `NIMBLE_API_KEY` | yes | From [nimbleway.com](https://www.nimbleway.com) dashboard |

### Interface

```python
# backend/integrations/nimble.py
"""Nimble Web Search Agents Platform integration.

Primary scraping path for the Policy Crawler. Hits regulatory sources
(CFPB, FRB, FTC, Federal Register) and returns structured content.

Failover: if a Nimble call raises NimbleError, the caller invokes
FirecrawlClient as the silent fallback (see firecrawl.py).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal

from nimble_sdk import Nimble                     # the Series B SDK
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


async def scrape_url(url: str) -> ScrapedDocument:
    """
    Scrape a single URL via Nimble's /extract endpoint.
    Returns markdown-formatted content.

    Raises NimbleError on failure -- caller decides whether to fall back to Firecrawl.
    """
    try:
        # Nimble SDK is sync; wrap in to_thread
        result = await asyncio.to_thread(
            _get_client().extract,
            url=url,
            output_format="markdown",
        )
        content = result.content or ""
        h = sha256(content.encode()).hexdigest()
        log.info("nimble.scrape_success", url=url, content_length=len(content))
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
    """
    Search the web via Nimble's /search endpoint.

    Args:
        query: search query, 1-6 words usually best
        num_results: max results
        use_answer: if True, use Nimble's "Answer" mode ($4/1000 instead of $1/1000)
                    which returns grounded reasoning over results. Use sparingly.
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
```

### Scrape targets

```python
# Used by backend/agents/policy_crawler.py
NIMBLE_TARGETS = [
    # CFPB -- the primary regulator for credit card consumer protection
    ("https://www.consumerfinance.gov/rules-policy/final-rules/", "CFPB"),
    ("https://www.consumerfinance.gov/rules-policy/notices-opportunities-comment/", "CFPB"),
    # FRB -- the Federal Reserve issues TILA interpretations
    ("https://www.federalreserve.gov/supervisionreg/srletters/srletters.htm", "FRB"),
    # FTC -- co-enforces FCRA with CFPB
    ("https://www.ftc.gov/legal-library/browse/cases-proceedings/business-blog", "FTC"),
    # Federal Register -- the authoritative source of final rules
    ("https://www.federalregister.gov/agencies/consumer-financial-protection-bureau", "Federal Register"),
    # ~10 targets total. Keeps the demo's scrape volume small enough to stay within Nimble free tier.
]
```

### Failure → fallback trigger

If `NimbleError` is raised, `backend/agents/policy_crawler.py` catches it and immediately tries `FirecrawlClient` for the same URL. The user (and the demo audience) never sees the failure.

---

## 5. Firecrawl -- Silent Fallback Scraper

**File:** `backend/integrations/firecrawl.py`

**Purpose:** Silent backup for Nimble. Never mentioned in the demo. Used only when Nimble fails.

### Setup

```bash
pip install "firecrawl-py>=1.6.7"
```

### Environment Variables

| Var | Required |
|---|---|
| `FIRECRAWL_API_KEY` | yes |

### Interface

```python
# backend/integrations/firecrawl.py
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


async def scrape_url(url: str) -> ScrapedDocument:
    """Same return type as nimble.scrape_url -- drop-in fallback."""
    try:
        result = await asyncio.to_thread(
            _get_client().scrape_url,
            url,
            params={"formats": ["markdown"]},
        )
        content = result.get("markdown", "")
        h = sha256(content.encode()).hexdigest()
        log.info("firecrawl.fallback_scrape_success", url=url, content_length=len(content))
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
```

### Failover pattern

```python
# Inside backend/agents/policy_crawler.py
from backend.integrations import nimble, firecrawl

async def scrape_with_failover(url: str):
    try:
        return await nimble.scrape_url(url)
    except nimble.NimbleError:
        log.warning("scrape.nimble_failed_falling_back_to_firecrawl", url=url)
        return await firecrawl.scrape_url(url)
```

---

## 6. Datadog -- LLM Observability + Control Alerts

**File:** `backend/integrations/datadog.py`

**Purpose:** Dual role. (1) LLM Observability + AI Agent Monitoring auto-instrumented via `ddtrace-run`. (2) Custom Datadog Events when control breaches occur.

### Setup

```bash
pip install "ddtrace>=4.8.0"
```

The 4.8+ requirement is critical -- it auto-instruments both `pydantic-ai>=1.85` AND `google-genai>=2.0`. Older versions (2.x, 3.x) instrument `google-genai` but miss Pydantic AI tool calls.

### Environment Variables

| Var | Required | Example |
|---|---|---|
| `DD_API_KEY` | yes | From Datadog → Organization → API Keys |
| `DD_SITE` | yes | `datadoghq.com` (US1) or `us3.datadoghq.com`, etc. |
| `DD_LLMOBS_ENABLED` | yes | `1` |
| `DD_LLMOBS_AGENTLESS_ENABLED` | yes | `1` (no agent process needed) |
| `DD_LLMOBS_ML_APP` | yes | `regradar` |
| `DD_SERVICE` | no | default `regradar-backend` |
| `DD_ENV` | no | default `hackathon` |

### Auto-instrumentation

Everything happens via `ddtrace-run`:

```bash
ddtrace-run uvicorn backend.main:app --reload
```

This auto-instruments:
- `pydantic-ai` agent runs → LLM spans tagged with agent name
- `pydantic-ai` tool calls → child spans tagged with tool name
- `google-genai` SDK → underlying LLM call spans
- `clickhouse-connect` → DB spans
- `fastapi` routes → HTTP spans
- `httpx`/`aiohttp` → outbound spans (Nimble, Senso, Firecrawl, OpenRouter)

In Datadog's AI Agent Console you see:
- A node per Pydantic AI agent (`policy_crawler`, `impact_analysis`, `auditor`)
- Edges showing tool calls and inter-agent handoffs
- Per-agent latency, token cost, error rate
- Click a trigger_id, see the full chain end-to-end

### Custom tagging per trigger

```python
# backend/utils/logging.py
from ddtrace.llmobs import LLMObs

def annotate_llm_span(*, agent_id: str, trigger_id: str, extra_tags: dict | None = None):
    """Tags the active LLM Obs span. Call at top of every agent run."""
    tags = {"agent": agent_id, "trigger_id": trigger_id}
    if extra_tags:
        tags.update(extra_tags)
    LLMObs.annotate(tags=tags)
```

Called from `backend/agents/base.py`'s `agent_run_context()` context manager.

### Control breach alerts (separate from LLM Obs)

When the Auditor approves an Impact Report containing a control flip to FAILING, post a Datadog Event:

```python
# backend/integrations/datadog.py
"""Custom Datadog Events for control breaches. Separate from LLM Obs."""

import os
from datadog import api as dd_api
from datadog import initialize

from backend.utils.logging import get_logger

log = get_logger(__name__)


class DatadogAlerter:
    _initialized: bool = False

    @classmethod
    def init(cls):
        if cls._initialized:
            return
        initialize(
            api_key=os.environ["DD_API_KEY"],
            api_host=f"https://api.{os.environ['DD_SITE']}",
        )
        cls._initialized = True

    @classmethod
    async def send_control_breach_alert(
        cls,
        *,
        control_id: str,
        control_name: str,
        regulation_section: str,
        affected_account_count: int,
        affected_balance_usd: float,
        owner_team: str,
        cited_md_url: str | None = None,
        source: str = "event_driven",
        severity: str = "critical",
    ) -> None:
        cls.init()
        import asyncio
        body = (
            f"**{control_name}** is FAILING.\n\n"
            f"**Regulation:** {regulation_section}\n"
            f"**Affected accounts:** {affected_account_count:,}\n"
            f"**Balance exposure:** ${affected_balance_usd:,.2f}\n"
            f"**Owner:** {owner_team}\n"
            f"**Source:** {source}\n"
        )
        if cited_md_url:
            body += f"\n**Grounded brief:** {cited_md_url}\n"

        await asyncio.to_thread(
            dd_api.Event.create,
            title=f"[RegRadar] {control_id} FAILING",
            text=body,
            tags=[
                f"control:{control_id}",
                f"owner:{owner_team}",
                f"severity:{severity}",
                f"source:{source}",
                "service:regradar",
            ],
            alert_type="error" if severity == "critical" else "warning",
        )
        log.info("datadog.control_breach_alert_sent", control_id=control_id, severity=severity)
```

### What to show in demo

1. **AI Agent Console** -- live during the cascade. Judges see Policy Crawler, Impact Analysis, Auditor nodes light up.
2. **Events stream** -- the control breach alert appears within 1 second of the Auditor approving.
3. **Trace drill-down** -- click a trigger_id, see the full chain with token counts and latencies.

---

## 7. Senso -- Publish to cited.md

**File:** `backend/integrations/senso.py`

**Purpose:** When the Auditor approves an Impact Report, generate a structured agent-native compliance brief and publish it to `cited.md/regradar/<slug>` via Senso. **This is the action that closes the Senso prize loop -- ingestion alone doesn't qualify; publishing does.**

### Background

[Senso](https://senso.ai) is a Y Combinator W24 company building the "context layer for AI agents." Their thesis: AI agents need a curated, version-controlled knowledge base of verified business truth. They run [cited.md](https://cited.md) -- an open, agent-native domain where experts publish structured context that agents can cite.

Their prize at this hackathon (3K credits) requires using their content generation APIs to publish content to cited.md. We do exactly that: after the Auditor approves an Impact Report, we generate a grounded compliance brief and publish.

### Setup

No official Python SDK. We call the REST API directly via `httpx`.

### Environment Variables

| Var | Required | Default |
|---|---|---|
| `SENSO_API_KEY` | yes | From [docs.senso.ai](https://docs.senso.ai) after signup |
| `SENSO_BASE_URL` | no | `https://apiv2.senso.ai` |
| `SENSO_PUBLISH_NAMESPACE` | no | `regradar` (appears in `cited.md/regradar/...`) |

### Interface

```python
# backend/integrations/senso.py
"""Senso integration: publish grounded compliance briefs to cited.md."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, Field

from backend.utils.logging import get_logger

log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Brief schema
# ════════════════════════════════════════════════════════════════


class ProvenanceMetadata(BaseModel):
    generated_by_agent: str
    auditor_approved: bool
    auditor_confidence: float
    trigger_id: str
    source_regulation_sections: list[str]
    generated_at: datetime


class ComplianceBrief(BaseModel):
    title: str
    handle: str = Field(default_factory=lambda: os.environ.get("SENSO_PUBLISH_NAMESPACE", "regradar"))
    slug: str
    body_markdown: str
    tags: list[str]
    provenance: ProvenanceMetadata
    related_regulation_id: str
    affected_account_count: int
    affected_balance_usd: float
    suggested_remediation: list[str]


class PublishedBrief(BaseModel):
    senso_id: str
    cited_md_url: str
    published_at: datetime


# ════════════════════════════════════════════════════════════════
# Client
# ════════════════════════════════════════════════════════════════


_HTTP: httpx.AsyncClient | None = None


def _get_http() -> httpx.AsyncClient:
    global _HTTP
    if _HTTP is None:
        _HTTP = httpx.AsyncClient(
            base_url=os.environ.get("SENSO_BASE_URL", "https://apiv2.senso.ai"),
            headers={
                "X-API-Key": os.environ["SENSO_API_KEY"],
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
        log.info("senso.initialized", base_url=os.environ.get("SENSO_BASE_URL"))
    return _HTTP


async def ingest_content(*, title: str, body_markdown: str, tags: list[str]) -> str:
    """
    POST /content/file -- ingest raw markdown content into Senso's knowledge base.
    Returns the content_id, which is then used in /generate to publish.
    """
    http = _get_http()
    files = {
        "file": ("brief.md", body_markdown.encode("utf-8"), "text/markdown"),
    }
    data = {
        "title": title,
        "tags": ",".join(tags),
    }
    # /content/file uses multipart, not JSON
    response = await http.post(
        "/content/file",
        files=files,
        data=data,
        headers={"X-API-Key": os.environ["SENSO_API_KEY"]},   # no Content-Type override
    )
    response.raise_for_status()
    payload = response.json()
    log.info("senso.ingest_success", content_id=payload["id"])
    return payload["id"]


async def publish_brief(brief: ComplianceBrief) -> PublishedBrief:
    """
    Full publish flow:
      1. POST /content/file -- ingest the brief markdown
      2. POST /generate -- compose the cited.md page with our brief as context
      3. POST /publish -- ship to cited.md/<namespace>/<slug>
    """
    http = _get_http()

    # 1. Ingest
    content_id = await ingest_content(
        title=brief.title,
        body_markdown=brief.body_markdown,
        tags=brief.tags,
    )

    # 2. Generate (Senso composes the public page from our content + their template)
    gen_payload = {
        "prompt": (
            f"Compose a cited.md article for regulatory professionals. "
            f"Use the ingested brief as the primary source. Preserve all numerical "
            f"claims and regulatory section citations verbatim. Add a 'How to verify' "
            f"section at the end pointing back to the source regulation URL."
        ),
        "source_content_ids": [content_id],
        "destination": "cited_md",
        "namespace": brief.handle,
        "slug": brief.slug,
        "tags": brief.tags,
        "metadata": brief.provenance.model_dump(mode="json"),
    }
    gen_response = await http.post("/generate", json=gen_payload)
    gen_response.raise_for_status()
    gen_data = gen_response.json()
    log.info("senso.generate_success", senso_id=gen_data["id"])

    # 3. Publish (in apiv2 the generate step often auto-publishes; if not, call /publish)
    if gen_data.get("status") != "published":
        publish_response = await http.post(f"/content/{gen_data['id']}/publish")
        publish_response.raise_for_status()

    cited_md_url = f"https://cited.md/{brief.handle}/{brief.slug}"
    log.info("senso.publish_success", cited_md_url=cited_md_url)
    return PublishedBrief(
        senso_id=gen_data["id"],
        cited_md_url=cited_md_url,
        published_at=datetime.now(timezone.utc),
    )


async def search_published_briefs(query: str, top_k: int = 5) -> list[dict]:
    """
    POST /search -- semantic search across all our published briefs.
    Useful for the frontend's 'find similar past violations' feature.
    """
    http = _get_http()
    response = await http.post(
        "/search",
        json={"query": query, "top_k": top_k, "namespace": os.environ.get("SENSO_PUBLISH_NAMESPACE", "regradar")},
    )
    response.raise_for_status()
    return response.json()["results"]
```

### Demo wiring

1. Auditor approves an Impact Report → `safe_to_publish = true`
2. `backend/orchestrator/publish_alert.py` calls `senso.publish_brief(brief)`
3. The returned `cited_md_url` is stored in `published_briefs` table + included in the Datadog alert body
4. Frontend renders the URL as a clickable link in the chat stream

### Failure modes

| Failure | Action |
|---|---|
| Ingest fails (5xx) | Retry once with backoff; if still failing, log + skip publish but continue Datadog alert |
| Generate fails | Retry once; if still failing, fall back to direct ingest-only (no public URL) |
| Publish fails | The content is ingested + generated; mark as 'pending_publish' in published_briefs |

Senso failure should NEVER block the Datadog alert. The cascade continues.

---

## 8. x402 -- USDC Micropayments for Compliance Briefs

**File:** `backend/integrations/x402_pay.py`

**Purpose:** The `/api/compliance-brief/{reg_id}` endpoint is gated by x402. Other agents pay $0.001 USDC on Base to fetch our structured compliance briefs.

### Background

[x402](https://x402.org) is Coinbase's HTTP-native payment protocol. It uses the long-unused HTTP 402 "Payment Required" status code to enable instant USDC payments over HTTP. Settlement happens on Base in ~200ms at sub-cent fees. As of May 2026: 169M+ transactions, $50M+ volume, used by AWS Bedrock AgentCore Payments, Cloudflare, etc.

The Devpost showcase rules say: *"Monetize it with agent payment rails (x402, MPP, CDP, agentic.market)."* x402 closes that loop in 10 demo seconds.

### Setup

```bash
pip install "x402>=0.4.0" "coinbase-cdp>=1.0.0"
```

### Environment Variables

| Var | Required | Default / Example |
|---|---|---|
| `X402_FACILITATOR_URL` | no | `https://x402.org/facilitator` (Coinbase-hosted) |
| `X402_NETWORK` | no | `base` (mainnet) or `base-sepolia` (testnet for safer demos) |
| `X402_RECIPIENT_ADDRESS` | yes for paid mode | Our wallet to receive USDC |
| `X402_PRICE_USDC_PER_BRIEF` | no | `0.001` ($0.001 per fetch) |
| `CDP_API_KEY_ID` | optional | From Coinbase Developer Portal |
| `CDP_API_KEY_SECRET` | optional | for advanced wallet ops |

### Interface

```python
# backend/integrations/x402_pay.py
"""x402 payment gate for the /compliance-brief/{reg_id} endpoint.

When an external agent requests a brief, the server returns 402 with payment
requirements. The agent signs a USDC transfer authorization and retries. The
x402 facilitator (Coinbase) verifies + settles on Base. Server returns the brief.
"""

import os
from decimal import Decimal

from fastapi import FastAPI, Request, HTTPException
from x402.fastapi import x402_protected, X402Config

from backend.utils.logging import get_logger

log = get_logger(__name__)


def get_x402_config() -> X402Config:
    """Build the x402 config from env vars."""
    return X402Config(
        facilitator_url=os.environ.get("X402_FACILITATOR_URL", "https://x402.org/facilitator"),
        network=os.environ.get("X402_NETWORK", "base"),
        recipient_address=os.environ.get("X402_RECIPIENT_ADDRESS", ""),
        token_symbol="USDC",
    )


def brief_price_usdc() -> Decimal:
    """Per-fetch price for /compliance-brief/{reg_id}."""
    return Decimal(os.environ.get("X402_PRICE_USDC_PER_BRIEF", "0.001"))
```

### Route protection

```python
# backend/api/routes_brief.py
from fastapi import APIRouter
from x402.fastapi import x402_protected

from backend.integrations.x402_pay import get_x402_config, brief_price_usdc
from backend.data import repositories as repo

router = APIRouter()


@router.get("/api/compliance-brief/{reg_id}")
@x402_protected(
    price=brief_price_usdc,
    config=get_x402_config,
    description="One RegRadar compliance brief in structured JSON, citation-grounded.",
)
async def get_compliance_brief(reg_id: str):
    """
    Returns the latest published compliance brief for a regulation_id.
    Gated by x402: requires $0.001 USDC payment via the X-PAYMENT header.

    Flow for an unauthenticated request:
      1. Server returns 402 Payment Required + payment requirements in X-PAYMENT-RESPONSE
      2. Client signs USDC transfer authorization (EIP-3009)
      3. Client retries with X-PAYMENT header containing the signed payload
      4. x402 middleware verifies via Coinbase facilitator
      5. On success, this route executes and returns the brief
    """
    brief = await repo.get_latest_published_brief(reg_id)
    if not brief:
        raise HTTPException(status_code=404, detail="No published brief for that regulation")

    # Record the paid fetch for our internal stats
    await repo.write_x402_fetch(
        brief_id=brief["brief_id"],
        amount_usdc=float(brief_price_usdc()),
    )

    return brief
```

### Demo flow (the closing 10 seconds)

```bash
# In a terminal next to the laptop, just before the close:
curl -i https://regradar.demo/api/compliance-brief/fcra_605

# Returns:
#   HTTP/1.1 402 Payment Required
#   X-PAYMENT-RESPONSE: {"network":"base","amount":"0.001","token":"USDC",...}
#
# Then with an x402-enabled client (e.g., `x402-curl`):
x402-curl https://regradar.demo/api/compliance-brief/fcra_605
# (Signs payment, retries, gets the brief JSON in <2 seconds)
```

The visual is: "this URL costs $0.001 to fetch" → terminal shows the payment → brief returned. The audience sees the future of agentic commerce in real time.

### Demo safety: use testnet

Use `X402_NETWORK=base-sepolia` (Base testnet) for the demo to avoid actual USDC outflows. The protocol behavior is identical; only the chain is different. Switch back to `base` after the hackathon.

### Failure modes

| Failure | Action |
|---|---|
| Facilitator unreachable | Return 503 + log; the brief stays gated |
| Payment signature invalid | Return 402 with new requirements; standard x402 behavior |
| Onchain confirmation delayed | x402 middleware handles polling; if >10s, return 504 |

---

## 9. Cross-Cutting: The Integration Contract

Every file in `backend/integrations/` MUST follow these rules.

### Rule 1: Singleton + Lazy Init

Module-level `_CLIENT` variable, getter function builds it on first call.

### Rule 2: Structured Logging

Every external call logs success and failure with structured fields:

```python
log.info("service.action_success", **relevant_fields)
log.error("service.action_failure", error=str(e), **relevant_fields)
```

Field namespace: `<service>.<action>` (e.g., `nimble.scrape_success`, `senso.publish_success`).

### Rule 3: Custom Exception Per Integration

```python
class NimbleError(Exception): pass
class SensoError(Exception): pass
class X402Error(Exception): pass
```

Upstream code uses the exception type to decide fallback path.

### Rule 4: Async-First

All public methods are `async def`. Sync SDKs (Nimble, Firecrawl, ClickHouse-connect sync mode) get wrapped with `asyncio.to_thread()`.

### Rule 5: Pydantic Returns

Integrations return Pydantic models, not raw dicts. See each integration's own model definitions.

### Rule 6: Env Var Validation

All required env vars are listed in `backend/utils/env.py::REQUIRED_VARS`. App refuses to start if any is missing.

### Rule 7: No Auth Logic Here

Auth tokens come from env vars. No OAuth refresh, no token rotation. (Production TODO.)

### Rule 8: Timeouts

- LLM calls: 30s
- Scraping: 60s
- ClickHouse queries: 10s
- Senso ingest/generate: 30s
- Senso search: 5s
- x402 verify: 10s
- Datadog event POST: 5s

### Rule 9: Retry With Tenacity

Three retries with exponential backoff (1s, 2s, 4s) before falling back or raising:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=4))
async def call_with_retry():
    ...
```

### Rule 10: Pre-warm at Startup

Every singleton's `_get_client()` is called once from `backend/main.py::lifespan` so the first user request doesn't pay the init cost.

---

## AI Tool Hints

If you're an AI tool building these:

1. **Implement in this order:** ClickHouse → Vertex AI → Nimble → Firecrawl → Datadog → Senso → x402 → OpenRouter. Each builds on the previous.

2. **Write `backend/data/models.py` first.** All integration return types reference Pydantic models defined there.

3. **Don't invent new patterns.** Copy the singleton + lazy-init pattern verbatim from `vertex_ai.py`. Copy logging field conventions verbatim.

4. **Test failover paths.** Have a test that forces Nimble to raise NimbleError and verifies Firecrawl picks up the same URL with the same return type.

5. **Use base-sepolia for x402 during development.** Switch to base mainnet only just before the demo (and back to sepolia immediately after).

6. **Pre-warm Senso ingest on startup.** Senso's first-request latency is ~3s due to cold start. Make a dummy `/search` call in `lifespan` to warm it.

7. **For Datadog auto-instrumentation to work,** the entry point MUST be `ddtrace-run uvicorn ...`. Not `python -m uvicorn ...` -- that bypasses ddtrace.
