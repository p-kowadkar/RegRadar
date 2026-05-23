# INTEGRATIONS.md

How each sponsor connects to RegRadar. Every integration is a file in `backend/integrations/`. Every integration is async. Every integration is wrapped in try/except with structured fallbacks.

This is a Level 3 spec. AI tools building this should implement each integration as described, with the exact function signatures, error handling, and observability hooks.

---

## Table of Contents

1. [Vertex AI (Gemini + Check Grounding)](#1-vertex-ai-gemini--check-grounding)
2. [OpenRouter (LLM Fallback)](#2-openrouter-llm-fallback)
3. [ClickHouse (Data Layer)](#3-clickhouse-data-layer)
4. [Nimble (Web Scraping -- Primary)](#4-nimble-web-scraping--primary)
5. [Firecrawl (Web Scraping -- Silent Fallback)](#5-firecrawl-web-scraping--silent-fallback)
6. [Datadog (LLM Observability + Monitoring)](#6-datadog-llm-observability--monitoring)
7. [Luminai (Workflow Execution)](#7-luminai-workflow-execution)
8. [Cross-Cutting: The Integration Contract](#8-cross-cutting-the-integration-contract)

---

## 1. Vertex AI (Gemini + Check Grounding)

**File:** `backend/integrations/vertex_ai.py`

**Purpose:** Sole entry point for all Gemini calls AND the Check Grounding API. Every other module imports from here. Centralization is what lets Datadog auto-instrumentation capture every LLM call uniformly.

### Setup

```bash
pip install --upgrade google-genai google-cloud-discoveryengine
gcloud auth application-default login
gcloud config set project gen-lang-client-0677154031
```

### Environment Variables Used

| Var | Required | Example |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | yes | `gen-lang-client-0677154031` |
| `GOOGLE_CLOUD_LOCATION` | yes | `us-central1` |
| `GOOGLE_GENAI_USE_VERTEXAI` | yes | `True` |
| `GEMINI_API_KEY` | optional | for fast API-key auth in scripts |

### Interface

```python
# backend/integrations/vertex_ai.py
from google import genai
from google.genai import types
from typing import Type, TypeVar
from pydantic import BaseModel
import structlog
import os

log = structlog.get_logger()
T = TypeVar("T", bound=BaseModel)


class VertexAIClient:
    """Singleton wrapper around Gemini + Check Grounding."""
    
    _instance: "VertexAIClient | None" = None
    
    def __init__(self):
        self.client = genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ["GOOGLE_CLOUD_LOCATION"],
        )
        self.fallback_provider = "openrouter"  # see openrouter.py
        log.info("vertex_ai.initialized")
    
    @classmethod
    def get(cls) -> "VertexAIClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def generate(
        self,
        *,
        model: str,                          # e.g. "gemini-3.5-flash"
        prompt: str,
        system_instruction: str | None = None,
        response_schema: Type[T] | None = None,
        thinking_level: str = "medium",      # "low", "medium", "high"
        max_output_tokens: int = 2048,
        agent_id: str | None = None,         # for Datadog tagging
    ) -> str | T:
        """
        Single entry for all Gemini calls.
        
        If response_schema is set, returns parsed Pydantic model.
        Else returns raw string.
        
        Tagged with agent_id for Datadog LLM Obs grouping.
        """
        config_kwargs = {
            "max_output_tokens": max_output_tokens,
            "thinking_config": types.ThinkingConfig(
                thinking_level=thinking_level
            ),
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if response_schema:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = response_schema
        
        try:
            response = await self.client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            log.info("vertex_ai.success",
                     agent=agent_id,
                     model=model,
                     tokens_in=response.usage_metadata.prompt_token_count,
                     tokens_out=response.usage_metadata.candidates_token_count)
            
            if response_schema:
                return response.parsed
            return response.text
        except Exception as e:
            log.error("vertex_ai.failure", agent=agent_id,
                      model=model, error=str(e))
            raise
    
    async def check_grounding(
        self,
        *,
        claim: str,
        sources: list[str],
    ) -> "GroundingResult":
        """
        Vertex AI Check Grounding API.
        Returns whether the claim is supported by the provided sources,
        with per-source confidence scores.
        
        Used exclusively by The Auditor.
        """
        # Implementation uses discoveryengine_v1 GroundedGenerationServiceClient
        # See: https://cloud.google.com/generative-ai-app-builder/docs/check-grounding
        ...
```

### Pydantic Models for Grounding

```python
# In backend/data/models.py
class GroundingCitation(BaseModel):
    source_id: str
    confidence: float
    supporting_text: str


class GroundingResult(BaseModel):
    claim: str
    is_grounded: bool
    overall_confidence: float
    citations: list[GroundingCitation]
```

### Why Singleton

The `VertexAIClient.get()` pattern ensures:
- One `genai.Client` instance per process (avoids socket exhaustion)
- Datadog auto-instrumentation hooks once
- Centralized error handling and logging

### Failure Modes

| Failure | Detection | Action |
|---|---|---|
| Rate limit (429) | exception with code 429 | retry 2x with exponential backoff, then fall back to OpenRouter |
| Quota exceeded | exception with code 8 | log + fall back to OpenRouter immediately |
| Timeout (>30s) | asyncio.TimeoutError | retry once, then fall back |
| Invalid response schema | JSON parse error | re-prompt with stricter instructions, then mark agent output `confidence=0` and continue |

### Datadog Hooks

When `ddtrace-run` is in use (always), the `google-genai` SDK is auto-instrumented. Each call generates an LLM span automatically. The `agent_id` keyword arg is captured as a custom tag via `LLMObs.annotate()` -- see `backend/utils/logging.py`.

---

## 2. OpenRouter (LLM Fallback)

**File:** `backend/integrations/openrouter.py`

**Purpose:** Used ONLY when Vertex AI fails (rate limit, quota, timeout). Never the primary path. Demo never explicitly mentions this -- it's resilience insurance.

### Setup

```bash
pip install openai  # OpenRouter uses OpenAI-compatible API
```

### Environment Variables

| Var | Required | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | yes | from openrouter.ai/keys |
| `OPENROUTER_BASE_URL` | yes | `https://openrouter.ai/api/v1` |

### Interface

```python
# backend/integrations/openrouter.py
from openai import AsyncOpenAI
import os
import structlog

log = structlog.get_logger()


# Model mapping: Vertex AI name → OpenRouter name
MODEL_MAP = {
    "gemini-3.5-flash": "google/gemini-2.5-flash",         # closest match
    "gemini-3.1-pro": "google/gemini-2.5-pro",             # closest match
}


class OpenRouterClient:
    _instance: "OpenRouterClient | None" = None
    
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=os.environ["OPENROUTER_BASE_URL"],
        )
        log.info("openrouter.initialized")
    
    @classmethod
    def get(cls) -> "OpenRouterClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def generate(
        self,
        *,
        model: str,
        prompt: str,
        system_instruction: str | None = None,
        response_format: dict | None = None,
        max_output_tokens: int = 2048,
        agent_id: str | None = None,
    ) -> str:
        """
        Fallback LLM call. Returns raw text only (no Pydantic parsing).
        Parsing happens upstream after retry.
        """
        or_model = MODEL_MAP.get(model, model)
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = await self.client.chat.completions.create(
                model=or_model,
                messages=messages,
                max_tokens=max_output_tokens,
                response_format=response_format,
            )
            log.info("openrouter.fallback_success",
                     agent=agent_id, model=or_model)
            return response.choices[0].message.content
        except Exception as e:
            log.error("openrouter.failure", agent=agent_id, error=str(e))
            raise
```

### Fallback Decision Logic

```python
# Inside vertex_ai.py -- when an exception is caught
from backend.integrations.openrouter import OpenRouterClient

try:
    return await self._call_vertex(...)
except (RateLimitError, QuotaExceededError, asyncio.TimeoutError):
    log.warning("vertex_ai.falling_back_to_openrouter", agent=agent_id)
    return await OpenRouterClient.get().generate(...)
```

---

## 3. ClickHouse (Data Layer)

**File:** `backend/integrations/clickhouse_client.py`

**Purpose:** Sole data layer. KG + portfolios + controls + audit + embeddings -- all here. Never bypass this wrapper.

### Setup

```bash
pip install clickhouse-connect[arrow]
```

### Environment Variables

| Var | Required | Example |
|---|---|---|
| `CLICKHOUSE_HOST` | yes | `xxx.us-east-1.aws.clickhouse.cloud` |
| `CLICKHOUSE_PORT` | yes | `8443` (HTTPS) |
| `CLICKHOUSE_USER` | yes | `default` |
| `CLICKHOUSE_PASSWORD` | yes | secret |
| `CLICKHOUSE_SECURE` | yes | `true` |
| `CLICKHOUSE_DATABASE` | yes | `regradar` |

### Interface

```python
# backend/integrations/clickhouse_client.py
import clickhouse_connect
import os
import structlog
from typing import Any

log = structlog.get_logger()


class ClickHouseClient:
    """Sync + async access to ClickHouse."""
    
    _sync_instance: "ClickHouseClient | None" = None
    _async_client = None
    
    def __init__(self):
        self.sync_client = clickhouse_connect.get_client(
            host=os.environ["CLICKHOUSE_HOST"],
            port=int(os.environ["CLICKHOUSE_PORT"]),
            username=os.environ["CLICKHOUSE_USER"],
            password=os.environ["CLICKHOUSE_PASSWORD"],
            secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
            database=os.environ.get("CLICKHOUSE_DATABASE", "regradar"),
        )
        log.info("clickhouse.initialized",
                 host=os.environ["CLICKHOUSE_HOST"])
    
    @classmethod
    def get_sync(cls) -> "ClickHouseClient":
        if cls._sync_instance is None:
            cls._sync_instance = cls()
        return cls._sync_instance
    
    @classmethod
    async def get_async(cls):
        """Async client (lazy-init)."""
        if cls._async_client is None:
            cls._async_client = await clickhouse_connect.get_async_client(
                host=os.environ["CLICKHOUSE_HOST"],
                port=int(os.environ["CLICKHOUSE_PORT"]),
                username=os.environ["CLICKHOUSE_USER"],
                password=os.environ["CLICKHOUSE_PASSWORD"],
                secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
                database=os.environ.get("CLICKHOUSE_DATABASE", "regradar"),
            )
        return cls._async_client
    
    def query(self, sql: str, params: dict | None = None) -> Any:
        """Sync query for setup / seed data scripts."""
        return self.sync_client.query(sql, parameters=params or {})
    
    async def aquery(self, sql: str, params: dict | None = None) -> Any:
        """Async query for agent execution."""
        client = await self.get_async()
        return await client.query(sql, parameters=params or {})
    
    def insert_df(self, table: str, df) -> None:
        """Bulk insert pandas DataFrame (used by seed scripts)."""
        self.sync_client.insert_df(table, df)
    
    async def ainsert(self, table: str, rows: list[list]) -> None:
        """Async row insert."""
        client = await self.get_async()
        await client.insert(table, rows)
```

### Repository Pattern

All agents query through `backend/data/repositories.py`, NOT directly through `ClickHouseClient`. See `docs/DATA_MODEL.md` for repository function signatures.

### Vector Search Quirk

ClickHouse vector functions require the `Array(Float32)` type. Always cast embeddings:

```sql
-- Correct
SELECT cosineDistance(embedding, [0.1, 0.2, ...]::Array(Float32)) AS dist
FROM kg_nodes ORDER BY dist LIMIT 10;
```

### Connection Pooling

`clickhouse-connect` handles HTTP connection pooling internally. No need for extra config -- the default pool size of 8 is fine for hackathon scope.

---

## 4. Nimble (Web Scraping -- Primary)

**File:** `backend/integrations/nimble.py`

**Purpose:** Primary scraper for The Watcher. Hits SEC EDGAR, CFTC, FINRA, OCC, CFPB, FinCEN, state regulators. Returns structured markdown for Classifier.

### Setup

```bash
pip install nimble-python
```

### Environment Variables

| Var | Required | Notes |
|---|---|---|
| `NIMBLE_API_KEY` | yes | from nimbleway.com dashboard |

5,000 page free trial. After that, $1 per 1,000 pages. We'll use ~500 pages during the hackathon.

### Interface

```python
# backend/integrations/nimble.py
from nimble_python import Nimble
import os
import structlog
from typing import Literal
from backend.data.models import ScrapedDocument

log = structlog.get_logger()


class NimbleClient:
    _instance: "NimbleClient | None" = None
    
    def __init__(self):
        self.client = Nimble(api_key=os.environ["NIMBLE_API_KEY"])
        log.info("nimble.initialized")
    
    @classmethod
    def get(cls) -> "NimbleClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def scrape_url(
        self,
        *,
        url: str,
        parsing_type: Literal["markdown", "html", "json"] = "markdown",
        agent_id: str = "watcher",
    ) -> ScrapedDocument:
        """
        Scrape a single URL. Returns ScrapedDocument.
        Raises NimbleError on failure -- caller decides whether to fall back to Firecrawl.
        """
        try:
            # Note: nimble_python is sync; wrap in asyncio.to_thread
            import asyncio
            result = await asyncio.to_thread(
                self.client.web.scrape,
                url=url,
                parsing_type=parsing_type,
            )
            log.info("nimble.scrape_success",
                     url=url, content_length=len(result.content))
            return ScrapedDocument(
                source_url=url,
                content=result.content,
                content_hash=self._hash(result.content),
                scraped_at=datetime.utcnow(),
                scraper_used="nimble",
            )
        except Exception as e:
            log.error("nimble.scrape_failure", url=url, error=str(e))
            raise NimbleError(str(e)) from e
    
    async def search(
        self,
        *,
        query: str,
        num_results: int = 10,
        deep_search: bool = True,
        parsing_type: str = "markdown",
    ) -> list[ScrapedDocument]:
        """
        Search the web. Used for ad-hoc regulatory lookups by The Mapper.
        """
        import asyncio
        result = await asyncio.to_thread(
            self.client.search,
            query=query,
            num_results=num_results,
            deep_search=deep_search,
            parsing_type=parsing_type,
        )
        return [
            ScrapedDocument(
                source_url=item.url,
                content=item.content if hasattr(item, "content") else item.snippet,
                content_hash=self._hash(item.content if hasattr(item, "content") else item.snippet),
                scraped_at=datetime.utcnow(),
                scraper_used="nimble",
            )
            for item in result.results
        ]
    
    @staticmethod
    def _hash(content: str) -> str:
        import hashlib
        return hashlib.sha256(content.encode()).hexdigest()


class NimbleError(Exception):
    """Raised on Nimble scrape failure -- triggers Firecrawl fallback."""
    pass
```

### Scrape Targets (Hardcoded for Hackathon)

```python
# Used by The Watcher
NIMBLE_SCRAPE_TARGETS = [
    # SEC
    "https://www.sec.gov/news/pressreleases",
    "https://www.sec.gov/rules/proposed.shtml",
    # CFTC
    "https://www.cftc.gov/PressRoom/PressReleases",
    # FINRA
    "https://www.finra.org/rules-guidance/notices",
    # OCC
    "https://occ.gov/news-issuances/bulletins",
    # CFPB
    "https://www.consumerfinance.gov/rules-policy/",
    # FinCEN
    "https://www.fincen.gov/news/news-releases",
    # NY DFS
    "https://www.dfs.ny.gov/industry_guidance",
    # ... ~16 total
]
```

See `docs/SEED_DATA.md` for the complete list.

### Failure → Fallback Trigger

If `NimbleError` is raised, `backend/agents/watcher.py` catches it and immediately tries `FirecrawlClient` for the same URL. The user never sees the failure.

---

## 5. Firecrawl (Web Scraping -- Silent Fallback)

**File:** `backend/integrations/firecrawl.py`

**Purpose:** Silent backup. Never mentioned in the demo. Used only when Nimble fails.

### Setup

```bash
pip install firecrawl-py
```

### Environment Variables

| Var | Required |
|---|---|
| `FIRECRAWL_API_KEY` | yes |

### Interface

```python
# backend/integrations/firecrawl.py
from firecrawl import FirecrawlApp
import os
import structlog
from datetime import datetime
from backend.data.models import ScrapedDocument

log = structlog.get_logger()


class FirecrawlClient:
    _instance: "FirecrawlClient | None" = None
    
    def __init__(self):
        self.app = FirecrawlApp(api_key=os.environ["FIRECRAWL_API_KEY"])
        log.info("firecrawl.initialized")
    
    @classmethod
    def get(cls) -> "FirecrawlClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def scrape_url(self, url: str) -> ScrapedDocument:
        """Same interface as NimbleClient.scrape_url -- drop-in replacement."""
        import asyncio
        try:
            result = await asyncio.to_thread(
                self.app.scrape_url,
                url,
                params={"formats": ["markdown"]},
            )
            log.info("firecrawl.fallback_scrape_success", url=url)
            content = result.get("markdown", "")
            return ScrapedDocument(
                source_url=url,
                content=content,
                content_hash=self._hash(content),
                scraped_at=datetime.utcnow(),
                scraper_used="firecrawl",
            )
        except Exception as e:
            log.error("firecrawl.fallback_failure", url=url, error=str(e))
            raise
    
    @staticmethod
    def _hash(content: str) -> str:
        import hashlib
        return hashlib.sha256(content.encode()).hexdigest()
```

### Watcher Failover Pattern

```python
# Inside backend/agents/watcher.py
from backend.integrations.nimble import NimbleClient, NimbleError
from backend.integrations.firecrawl import FirecrawlClient

async def scrape_with_failover(url: str) -> ScrapedDocument:
    try:
        return await NimbleClient.get().scrape_url(url=url)
    except NimbleError:
        log.warning("watcher.nimble_failed_using_firecrawl", url=url)
        return await FirecrawlClient.get().scrape_url(url)
```

---

## 6. Datadog (LLM Observability + Monitoring)

**File:** `backend/integrations/datadog.py`

**Purpose:** Dual role. (1) LLM Observability for the agent chain -- auto-instrumented via `ddtrace-run`. (2) Custom alerts when governance controls fail or breach.

### Setup

```bash
pip install ddtrace
```

### Environment Variables

| Var | Required | Example |
|---|---|---|
| `DD_API_KEY` | yes | from datadoghq.com → Organization → API Keys |
| `DD_SITE` | yes | `datadoghq.com` (US1) or regional variant |
| `DD_LLMOBS_ENABLED` | yes | `1` |
| `DD_LLMOBS_AGENTLESS_ENABLED` | yes | `1` (no agent process needed) |
| `DD_LLMOBS_ML_APP` | yes | `regradar` |
| `DD_SERVICE` | yes | `regradar-backend` |
| `DD_ENV` | yes | `hackathon` |

### Auto-Instrumentation

The magic happens via `ddtrace-run`:

```bash
ddtrace-run uvicorn backend.main:app --reload
```

This wraps the Python process and auto-instruments:
- `google-genai` SDK (every Gemini call → LLM span)
- `openai` SDK (every OpenRouter call → LLM span)
- `clickhouse_connect` (every query → DB span)
- `fastapi` (every route → HTTP span)
- `httpx` and `aiohttp` (every outbound HTTP → span)

**Result:** Open Datadog's AI Agent Console and see the full Classifier → Mapper → Analyst → Advisor chain with input/output, latencies, token counts, and inter-agent calls.

### Custom Tagging Per Agent

```python
# backend/utils/logging.py
from ddtrace.llmobs import LLMObs

def annotate_llm_span(agent_id: str, claim_id: str | None = None):
    """Adds custom tags to the currently-active LLM span."""
    tags = {"agent": agent_id}
    if claim_id:
        tags["claim_id"] = claim_id
    LLMObs.annotate(tags=tags)
```

Called from inside each agent's `execute()`:

```python
class ClassifierAgent(BaseAgent):
    async def execute(self, blackboard):
        annotate_llm_span(agent_id=self.agent_id,
                          claim_id=blackboard.current_claim_id)
        # ... rest of agent logic
```

### Custom Alerts (for Control Failures)

When The Advisor updates a control and the new test result is FAILING, fire a Datadog alert:

```python
# backend/integrations/datadog.py
from datadog import api as dd_api
from datadog import initialize
import os
import structlog

log = structlog.get_logger()


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
        regulation_title: str,
        affected_position_count: int,
        notional_exposure_usd: float,
        owner_team: str,
        severity: str = "critical",
    ) -> None:
        """Sends a Datadog event when a control breaches."""
        cls.init()
        import asyncio
        await asyncio.to_thread(
            dd_api.Event.create,
            title=f"[RegRadar] Control breach: {control_id}",
            text=(
                f"**{control_name}** is FAILING due to regulation change:\n\n"
                f"**Regulation:** {regulation_title}\n"
                f"**Affected positions:** {affected_position_count}\n"
                f"**Notional exposure:** ${notional_exposure_usd:,.0f}\n"
                f"**Owner:** {owner_team}\n\n"
                f"See impact analysis: http://localhost:5173/controls/{control_id}"
            ),
            tags=[
                f"control:{control_id}",
                f"owner:{owner_team}",
                f"severity:{severity}",
                "service:regradar",
            ],
            alert_type="error" if severity == "critical" else "warning",
        )
        log.info("datadog.alert_sent", control_id=control_id, severity=severity)
```

### What To Show In Demo

1. **AI Agent Console** -- live during the CFTC cascade. Judges see the agent graph rendering.
2. **Events stream** -- the control breach alert appears within 1 second of The Advisor's update.
3. **Trace search** -- pull up a specific trace_id and show the full chain end-to-end.

---

## 7. Luminai (Workflow Execution)

**File:** `backend/integrations/luminai.py`

**Purpose:** The Advisor's action arm. When an action has `workflow_execution=true`, it's dispatched to Luminai, which performs the UI-level automation (filing forms, updating GRC systems, sending notifications).

### Setup

**Important:** Luminai's developer API and SDK details are not publicly documented. The team has access to Luminai's sandbox at the hackathon. Treat this integration as a stub that we'll wire up on-site with Luminai's engineers.

### Environment Variables

| Var | Required | Notes |
|---|---|---|
| `LUMINAI_API_KEY` | yes | provided at hackathon |
| `LUMINAI_BASE_URL` | yes | provided at hackathon |
| `LUMINAI_WORKSPACE_ID` | yes | our sandbox workspace |

### Interface (Stub)

```python
# backend/integrations/luminai.py
import httpx
import os
import structlog
from typing import Any
from backend.data.models import LuminaiSOP, LuminaiExecutionResult

log = structlog.get_logger()


class LuminaiClient:
    _instance: "LuminaiClient | None" = None
    
    def __init__(self):
        self.base_url = os.environ["LUMINAI_BASE_URL"]
        self.api_key = os.environ["LUMINAI_API_KEY"]
        self.workspace_id = os.environ["LUMINAI_WORKSPACE_ID"]
        self.http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=60.0,
        )
        log.info("luminai.initialized")
    
    @classmethod
    def get(cls) -> "LuminaiClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    async def execute_sop(
        self,
        *,
        sop: LuminaiSOP,
        dry_run: bool = True,        # demo default -- sandbox only
    ) -> LuminaiExecutionResult:
        """
        Execute an SOP via Luminai. In dry-run mode (demo default), Luminai
        opens the target site and demonstrates the workflow without
        submitting. Returns execution_id for status polling.
        """
        try:
            response = await self.http.post(
                f"/workspaces/{self.workspace_id}/workflows/execute",
                json={
                    "name": sop.name,
                    "description": sop.description,
                    "steps": sop.steps,
                    "context": sop.context,
                    "dry_run": dry_run,
                },
            )
            response.raise_for_status()
            data = response.json()
            log.info("luminai.execution_started",
                     execution_id=data["execution_id"],
                     dry_run=dry_run)
            return LuminaiExecutionResult(
                execution_id=data["execution_id"],
                status="running",
                preview_url=data.get("preview_url"),
            )
        except httpx.HTTPError as e:
            log.error("luminai.execution_failed", error=str(e))
            raise LuminaiError(str(e)) from e
    
    async def get_execution_status(
        self,
        execution_id: str,
    ) -> LuminaiExecutionResult:
        """Poll execution status. Returns updated result."""
        response = await self.http.get(
            f"/workspaces/{self.workspace_id}/executions/{execution_id}",
        )
        response.raise_for_status()
        data = response.json()
        return LuminaiExecutionResult(**data)


class LuminaiError(Exception):
    pass
```

### Pydantic Models for SOPs

```python
# In backend/data/models.py
class LuminaiSOPStep(BaseModel):
    step_number: int
    action: str                            # human-readable instruction
    target: str | None = None              # URL or app selector
    inputs: dict[str, Any] = Field(default_factory=dict)


class LuminaiSOP(BaseModel):
    name: str                              # e.g. "File SAR with FinCEN"
    description: str                       # for Luminai's UI
    steps: list[LuminaiSOPStep]
    context: dict[str, Any]                # passed to steps (form data, etc.)


class LuminaiExecutionResult(BaseModel):
    execution_id: str
    status: Literal["running", "succeeded", "failed", "needs_human_review"]
    preview_url: str | None = None         # iframe URL for demo
    completed_steps: int = 0
    total_steps: int = 0
    error_message: str | None = None
```

### Demo Wiring

When the demo reaches the "Execute SAR filing" moment:

1. Frontend calls `POST /api/actions/{action_id}/execute`
2. Backend reads The Advisor's saved SOP from ClickHouse
3. Backend calls `LuminaiClient.execute_sop(sop=..., dry_run=True)`
4. Backend returns `preview_url` to frontend
5. Frontend embeds the `preview_url` in an iframe -- judges see Luminai navigating
6. Frontend polls `GET /api/actions/{action_id}/status` every 500ms for updates

### Pre-Demo Setup

The team will pre-define one SOP in Luminai's sandbox **before** the demo:
- **Name:** "File SAR with FinCEN (sandbox demo)"
- **Target:** `https://bsaefiling.fincen.treas.gov/` (sandboxed copy)
- **Steps:** Pre-validated so live execution is deterministic

Don't improvise live. The demo SOP is locked.

---

## 8. Cross-Cutting: The Integration Contract

Every integration in `backend/integrations/` MUST follow these rules:

### Rule 1: Singleton + Lazy Init

```python
class XxxClient:
    _instance: "XxxClient | None" = None
    
    @classmethod
    def get(cls) -> "XxxClient":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
```

### Rule 2: Structured Logging

Every external call logs success and failure with structured fields:

```python
log.info("xxx.action_success", **relevant_fields)
log.error("xxx.action_failure", error=str(e), **relevant_fields)
```

Field names use `<service>.<action>` namespacing (e.g. `nimble.scrape_success`).

### Rule 3: Custom Exception Type

Each integration defines its own exception:

```python
class NimbleError(Exception): pass
class LuminaiError(Exception): pass
class VertexAIError(Exception): pass
# etc.
```

These let upstream code decide which integration's failure triggers which fallback.

### Rule 4: Async-First

All public methods are `async def`. If the underlying SDK is sync (like `nimble-python`), wrap with `asyncio.to_thread()`. Never block the event loop.

### Rule 5: Pydantic Returns

Integrations return Pydantic models, not raw dicts. See `backend/data/models.py` for the catalog.

### Rule 6: Env Var Validation

All required env vars are validated at startup via `backend/utils/env.py`. If a required var is missing, the app refuses to start. This prevents silent failures during demo.

### Rule 7: No Auth Logic Here

Auth tokens come from env vars only. No OAuth flows, no token refresh logic. (Production TODO.)

### Rule 8: Timeouts

Every external HTTP call has an explicit timeout:
- LLM calls: 30s
- Scraping: 60s
- ClickHouse queries: 10s
- Luminai workflows: no timeout (long-running)
- Datadog: 5s

### Rule 9: Retry Policy

Use `tenacity` for retries. Three retries with exponential backoff (1s, 2s, 4s) before falling back or raising:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
)
async def call_with_retry():
    ...
```

### Rule 10: Tests Live Alongside

Each `xxx.py` in `backend/integrations/` has a corresponding `tests/test_xxx.py` with at minimum:
- `test_singleton_returns_same_instance`
- `test_missing_env_var_raises_at_startup`
- `test_basic_call_returns_expected_shape`

Mock external services with `respx` (for httpx) or fixture JSON files.

---

## AI Tool Hints

If you're an AI coding tool building this:

1. **Implement integrations in this order:** ClickHouse → Vertex AI → Nimble → Firecrawl → Datadog → OpenRouter → Luminai. Each builds on the previous.

2. **Write `backend/data/models.py` first.** All integration return types reference it. See `docs/AGENTS.md` for the agent-related models and this file for the integration-related ones.

3. **Don't invent new patterns.** Copy the singleton + lazy-init pattern verbatim. Use the same logging field names. Use the same exception hierarchy.

4. **Test the failover paths.** Have a test that forces Nimble to fail and verifies Firecrawl picks up the same URL. Have a test that forces Vertex AI to 429 and verifies OpenRouter picks up.

5. **Pre-warm before demo.** All singletons should be initialized at app startup, not on first request. Add an `init_integrations()` function called from `lifespan` in `backend/main.py`.
