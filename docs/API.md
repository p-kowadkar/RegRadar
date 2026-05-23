# API.md

Complete FastAPI endpoint and WebSocket protocol specification for the 4-agent architecture.

---

## 0. Conventions

- **Base URL** (local dev): `http://localhost:8000`
- **All routes prefixed with `/api/`** except WebSocket (`/ws/`)
- **All responses are JSON** with the consistent envelope below
- **All routes are async**, all I/O is Pydantic-validated
- **CORS** enabled for `http://localhost:5173` (Vite default)
- **Auth** for the hackathon: a single static API key in header `X-API-Key` -- production auth is TODO
- **`/api/compliance-brief/{reg_id}` is x402-gated** -- see [INTEGRATIONS.md section 8](INTEGRATIONS.md#8-x402----usdc-micropayments-for-compliance-briefs)

---

## 1. Response Envelope

```python
class APIResponse(BaseModel):
    success: bool
    data: Any | None = None
    error: ErrorDetail | None = None
    metadata: dict = {}                    # request_id, duration_ms, etc.

class ErrorDetail(BaseModel):
    code: str                              # "VALIDATION_ERROR", "INTEGRATION_FAILURE", etc.
    message: str
    details: dict = {}
```

### Success

```json
{
  "success": true,
  "data": {"control_id": "CTRL-FCRA-STALE-DATA", "status": "FAILING", "breach_count": 1247},
  "error": null,
  "metadata": {"request_id": "req_abc123", "duration_ms": 47}
}
```

### Error

```json
{
  "success": false,
  "data": null,
  "error": {"code": "CONTROL_NOT_FOUND", "message": "...", "details": {"control_id": "CTRL-XYZ"}},
  "metadata": {"request_id": "req_xyz", "duration_ms": 12}
}
```

---

## 2. Routes Index

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness |
| GET | `/api/health/integrations` | Per-integration smoke test |
| GET | `/api/issuer` | Get Pinecrest Bank profile |
| GET | `/api/controls` | All 6 controls with current status |
| GET | `/api/controls/{control_id}` | One control detail + recent scans |
| GET | `/api/controls/{control_id}/history` | Time series of scan results |
| POST | `/api/controls/{control_id}/recheck` | Manually run a control's SQL now |
| GET | `/api/accounts/sample` | Sample of credit_card_accounts (for UI) |
| GET | `/api/accounts/{account_id}` | One account's full record |
| GET | `/api/regulations` | List loaded regulations |
| GET | `/api/regulations/{reg_id}` | One regulation + its compliance_conditions |
| GET | `/api/triggers` | Recent triggers (events) |
| GET | `/api/triggers/{trigger_id}` | Full trigger chain: impact_report + auditor_verdict + published_brief |
| GET | `/api/agents/status` | Current state of 4 agents |
| GET | `/api/audit-trail` | Recent audit events (paginated) |
| GET | `/api/published-briefs` | Briefs published to cited.md |
| GET | `/api/compliance-brief/{reg_id}` | **x402-gated.** Returns the structured brief for one regulation. |
| POST | `/api/internal/trigger` | Demo trigger -- inject a schema_event / behavior_event / policy_change |
| POST | `/api/internal/scenarios/{scenario}` | Convenience: load + fire a named demo scenario |
| GET | `/api/internal/scenarios` | List available demo scenarios |
| WS | `/ws/stream` | Bidirectional stream of trigger updates |

---

## 3. Detailed Endpoint Specs

### 3.1 GET `/api/health`

```json
{"success": true, "data": {"status": "ok", "version": "0.2.0"}, "metadata": {...}}
```

### 3.2 GET `/api/health/integrations`

Smoke-tests every integration. Used by the dashboard's "system health" panel and by `scripts/smoke_test.py`.

```json
{
  "success": true,
  "data": {
    "vertex_ai_gemini_flash": {"status": "ok", "latency_ms": 230, "model": "gemini-3.5-flash"},
    "vertex_ai_gemini_pro": {"status": "ok", "latency_ms": 410, "model": "gemini-3.1-pro"},
    "vertex_ai_grounding": {"status": "ok", "latency_ms": 180},
    "vertex_ai_embeddings": {"status": "ok", "latency_ms": 120, "model": "gemini-embedding-001"},
    "clickhouse": {"status": "ok", "latency_ms": 18, "version": "25.8.1"},
    "nimble": {"status": "ok", "latency_ms": 412, "credits_remaining": 4520},
    "firecrawl": {"status": "ok", "latency_ms": 380},
    "datadog": {"status": "ok", "latency_ms": 88, "llmobs_enabled": true},
    "senso": {"status": "ok", "latency_ms": 240, "namespace": "regradar"},
    "x402": {"status": "ok", "facilitator": "x402.org", "network": "base-sepolia"},
    "openrouter": {"status": "ok", "latency_ms": 520}
  }
}
```

### 3.3 GET `/api/issuer`

```python
class IssuerProfileResponse(BaseModel):
    company_id: str                        # "pinecrest_bank_demo"
    name: str
    type: str
    annual_volume_usd: float
    active_accounts: int
    states_operating_in: str | list[str]
    products: list[str]
    regulators: list[str]                  # ["CFPB", "FRB", "FDIC", "FTC"]
    applicable_regimes: list[str]          # ["TILA_Regulation_Z", "FCRA"]
    portfolio_snapshot: PortfolioSnapshot
```

```python
class PortfolioSnapshot(BaseModel):
    total_accounts: int
    total_balance_usd: float
    by_product: dict[str, int]             # {"standard": 35000, "rewards": 10000, ...}
    by_state_top10: list[tuple[str, int]]
    disputes_active: int
    penalty_rates_active: int
    bureau_reported: int
```

### 3.4 GET `/api/controls`

```python
class ControlSummary(BaseModel):
    control_id: str
    name: str
    related_regulation_section: str        # "12 CFR 1026.9(g)"
    status: Literal["PASSING", "WARNING", "FAILING", "UNTESTED"]
    breach_count: int
    breach_balance_usd: float
    last_tested_at: datetime | None
    owner_team: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class ControlsListResponse(BaseModel):
    controls: list[ControlSummary]
    summary: dict[str, int]                # {"PASSING": 3, "WARNING": 1, "FAILING": 2}
    last_full_sweep_at: datetime
```

### 3.5 GET `/api/controls/{control_id}`

Same fields as `ControlSummary` plus:

```python
class ControlDetail(ControlSummary):
    description: str
    check_sql: str                         # the actual SQL the Monitoring Agent runs
    sample_breach_account_ids: list[str]   # up to 20
    recent_scans: list[ScanResult]         # last 30 scans


class ScanResult(BaseModel):
    scan_id: str
    scanned_at: datetime
    scan_source: Literal["daily_monitoring", "event_driven", "manual"]
    result: Literal["PASS", "WARN", "FAIL"]
    breach_count: int
    at_risk_count: int
    breach_balance_usd: float
```

### 3.6 POST `/api/controls/{control_id}/recheck`

Manually re-run a control's `check_sql`. Synchronous, sub-second.

Request body: `{}` (no params).

Response: `ScanResult` (defined above).

### 3.7 GET `/api/accounts/sample`

Query params: `limit` (default 20, max 100), `product_type`, `state`, `has_dispute`, `has_penalty_rate`, `bureau_mismatch_only`.

Returns a sample of `credit_card_accounts` for UI display.

```python
class AccountSummary(BaseModel):
    account_id: str
    state: str
    product_type: str
    credit_limit_usd: float
    balance_usd: float
    payment_status: str
    bureau_reported_status: str | None
    dispute_filed: bool
    promo_rate: float | None
    promo_rate_end_date: date | None
    promo_notice_sent_date: date | None
    penalty_rate_applied: bool
    original_delinquency_date: date | None
```

### 3.8 GET `/api/regulations`

```python
class RegulationSummary(BaseModel):
    regulation_id: str                     # "tila_reg_z" | "fcra"
    title: str
    regulator: str
    regulation_section_top: str            # "12 CFR 1026" | "15 USC 1681"
    n_conditions_extracted: int
    n_controls: int
    last_seen_at: datetime
```

### 3.9 GET `/api/regulations/{reg_id}`

```python
class RegulationDetail(RegulationSummary):
    source_url: str
    content_markdown: str
    compliance_conditions: list[ComplianceConditionDetail]
    controls: list[ControlSummary]


class ComplianceConditionDetail(BaseModel):
    condition_id: str
    regulation_section: str
    condition_kind: str
    field_required: str
    operator: str
    threshold_value: str
    threshold_unit: str
    severity: str
    citation_text: str
    extracted_at: datetime
```

### 3.10 GET `/api/triggers`

Query params: `limit` (default 20), `trigger_type` (`policy_change` | `schema_event` | `behavior_event`), `since` (ISO 8601).

```python
class TriggerSummary(BaseModel):
    trigger_id: str
    trigger_type: Literal["policy_change", "schema_event", "behavior_event"]
    occurred_at: datetime
    processed: bool
    processed_at: datetime | None
    impact_report_id: str | None
    auditor_verdict: str | None            # "approved" | "approved_with_warnings" | "rejected"
    published_brief_url: str | None
    affected_controls: list[str]
```

### 3.11 GET `/api/triggers/{trigger_id}`

Full chain detail for one trigger:

```python
class TriggerDetail(BaseModel):
    trigger_id: str
    trigger_type: str
    payload: dict                          # the original event row
    occurred_at: datetime
    impact_report: ImpactReportFull | None
    auditor_verdict: AuditorVerdictFull | None
    published_brief: PublishedBriefSummary | None
    dd_alerts: list[DDAlertSummary]
    audit_trail: list[AuditTrailEntry]


class ImpactReportFull(BaseModel):
    trigger_id: str
    affected_controls: list[ControlUpdate]
    total_breach_count: int
    total_at_risk_count: int
    total_balance_at_risk_usd: float
    citations: list[str]
    suggested_remediation: list[str]
    reasoning: str
    generated_at: datetime
    llm_model_used: str                    # "gemini-3.5-flash"
    llm_tokens_in: int
    llm_tokens_out: int


class AuditorVerdictFull(BaseModel):
    trigger_id: str
    verdict: Literal["approved", "approved_with_warnings", "rejected"]
    overall_confidence: float
    claims_audited: list[ClaimAudit]
    warnings: list[str]
    rejection_reasons: list[str]
    safe_to_publish: bool
    safe_to_alert: bool
    audited_at: datetime
    llm_model_used: str                    # "gemini-3.1-pro" + "check-grounding"
```

### 3.12 GET `/api/agents/status`

```python
class AgentStatus(BaseModel):
    agent_id: Literal["policy_crawler", "impact_analysis", "auditor", "monitoring"]
    display_name: str
    activation_mode: Literal["scheduled_hourly", "event_driven", "post_impact_analysis", "scheduled_daily"]
    model: str | None                      # null for monitoring (zero LLM)
    last_run_at: datetime | None
    last_run_status: Literal["success", "failed", "in_progress"] | None
    total_runs_today: int
    total_llm_tokens_today: int
    avg_latency_ms: float | None


class AgentsStatusResponse(BaseModel):
    agents: list[AgentStatus]
    event_poller_lag_ms: int               # how far behind the poller is
    unprocessed_events: int                # backlog in policy_changes/schema_events/behavior_events
```

### 3.13 GET `/api/published-briefs`

```python
class PublishedBriefSummary(BaseModel):
    brief_id: str
    title: str
    slug: str
    cited_md_url: str                      # "https://cited.md/regradar/fcra-605-stale-data-2026-05-23"
    related_regulation_id: str
    affected_account_count: int
    published_at: datetime
    fetch_count: int                       # total reads
    paid_fetch_count: int                  # via x402
    total_usdc_earned: float
```

### 3.14 GET `/api/compliance-brief/{reg_id}` -- x402-gated

**This endpoint requires x402 payment.** Returns 402 if no valid `X-PAYMENT` header.

Successful response (after payment):

```python
class ComplianceBriefResponse(BaseModel):
    reg_id: str
    title: str
    body_markdown: str
    related_regulation_section: str
    affected_account_count: int
    affected_balance_usd: float
    suggested_remediation: list[str]
    provenance: ProvenanceMetadata         # auditor_approved, auditor_confidence, etc.
    cited_md_url: str                      # for reference
```

See [INTEGRATIONS.md section 8](INTEGRATIONS.md#8-x402----usdc-micropayments-for-compliance-briefs) for the x402 flow.

### 3.15 POST `/api/internal/trigger`

The demo trigger. Inserts a row directly into `policy_changes`, `schema_events`, or `behavior_events`. The Impact Analysis poll worker picks it up within 500ms.

Request:

```python
class TriggerRequest(BaseModel):
    trigger_type: Literal["policy_change", "schema_event", "behavior_event"]
    payload: dict                          # shape depends on trigger_type; see below


# For schema_event:
{
  "trigger_type": "schema_event",
  "payload": {
    "event_type": "column_populated",
    "table_name": "credit_card_accounts",
    "column_name": "original_delinquency_date",
    "event_payload_json": {"migration_id": "mig_demo_2026_05_23", "rows_populated": 6240}
  }
}

# For behavior_event:
{
  "trigger_type": "behavior_event",
  "payload": {
    "event_type": "dispute_filed",
    "account_id": "acct_002847",
    "event_payload_json": {"dispute_amount_usd": 1289.42, "merchant": "PERSEUS ONLINE LLC", "reason": "unauthorized_charge"}
  }
}

# For policy_change (rare in demo -- usually the Policy Crawler writes these):
{
  "trigger_type": "policy_change",
  "payload": {
    "regulation_id": "tila_reg_z",
    "new_version_id": "synthetic_v_demo_2026_05_23",
    "is_material_change": true,
    "change_summary": "Hypothetical CFPB amendment: promo notice extended from 45 to 60 days"
  }
}
```

Response:

```python
class TriggerResponse(BaseModel):
    trigger_id: str
    trigger_type: str
    inserted_at: datetime
    estimated_pickup_lag_ms: int           # ~500
```

### 3.16 POST `/api/internal/scenarios/{scenario}`

Convenience wrapper around `/api/internal/trigger`. Loads `seed/demo_events.json` and fires the named scenario:

- `schema_enrichment_fcra` -- the headline demo beat
- `dispute_filed_cross_trigger` -- the secondary demo beat
- `policy_change_tila_promo_notice` -- backup scenario

Response: same `TriggerResponse` as above.

### 3.17 GET `/api/internal/scenarios`

Returns the demo scenario catalog from `seed/demo_events.json`.

```python
class DemoScenario(BaseModel):
    scenario: str
    label: str
    kind: Literal["policy_change", "schema_event", "behavior_event"]
    expected_breach_count: int | None
    expected_controls_to_fail: list[str] | None
    expected_demo_duration_seconds: int


class DemoScenariosResponse(BaseModel):
    scenarios: list[DemoScenario]
```

---

## 4. WebSocket Protocol -- `/ws/stream`

Bidirectional stream. The frontend subscribes; the server pushes updates as triggers process. No conversational chat -- just live agent status updates.

### Connection

```
ws://localhost:8000/ws/stream
```

Headers: `X-API-Key: <static-demo-key>`

Server echoes a `connected` event on accept.

### Message Envelope

```typescript
interface WSMessage {
  type: WSMessageType;
  payload: Record<string, any>;
  timestamp: string;                       // ISO 8601
  message_id: string;                      // UUID
  trigger_id?: string;                     // present for trigger-scoped messages
  agent_id?: AgentId;                      // present for agent-scoped messages
}

type AgentId = "policy_crawler" | "impact_analysis" | "auditor" | "monitoring";

type WSMessageType =
  | "connected"
  | "trigger_received"                     // a new row appeared in events table
  | "agent_started"                        // Impact Analysis or Auditor began running
  | "agent_tool_call"                      // one of the agent's tools fired
  | "agent_completed"                      // Impact Analysis or Auditor finished
  | "control_status_changed"               // a control flipped status
  | "brief_published"                      // Senso publish succeeded
  | "datadog_alert_sent"                   // control breach alert fired
  | "x402_fetch_succeeded"                 // someone paid + fetched a brief
  | "trigger_complete"                     // full chain done
  | "trigger_failed"                       // hard failure
  | "pong";
```

### Sample flow -- schema_enrichment_fcra demo

```
[Client → Server]
POST /api/internal/scenarios/schema_enrichment_fcra
< { "trigger_id": "trg_abc123", ... }

[Server → Client] (over WS)
{
  "type": "trigger_received",
  "trigger_id": "trg_abc123",
  "payload": {
    "trigger_type": "schema_event",
    "table": "credit_card_accounts",
    "column": "original_delinquency_date"
  },
  "timestamp": "..."
}

[Server → Client]
{
  "type": "agent_started",
  "trigger_id": "trg_abc123",
  "agent_id": "impact_analysis",
  "payload": {"model": "gemini-3.5-flash"}
}

[Server → Client]
{
  "type": "agent_tool_call",
  "trigger_id": "trg_abc123",
  "agent_id": "impact_analysis",
  "payload": {
    "tool": "query_accounts",
    "args": {"where_clause": "bureau_reported = true AND ...", "params": {...}}
  }
}

[Server → Client]
{
  "type": "agent_completed",
  "trigger_id": "trg_abc123",
  "agent_id": "impact_analysis",
  "payload": {
    "impact_report_id": "imp_xyz",
    "total_breach_count": 1247,
    "total_balance_at_risk_usd": 1975000,
    "affected_controls": ["CTRL-FCRA-STALE-DATA"]
  }
}

[Server → Client]
{
  "type": "control_status_changed",
  "trigger_id": "trg_abc123",
  "payload": {
    "control_id": "CTRL-FCRA-STALE-DATA",
    "old_status": "PASSING",
    "new_status": "FAILING",
    "breach_count": 1247
  }
}

[Server → Client]
{
  "type": "agent_started",
  "trigger_id": "trg_abc123",
  "agent_id": "auditor",
  "payload": {"model": "gemini-3.1-pro"}
}

[Server → Client]
{
  "type": "agent_completed",
  "trigger_id": "trg_abc123",
  "agent_id": "auditor",
  "payload": {
    "verdict": "approved",
    "overall_confidence": 0.92,
    "claims_audited": 7,
    "safe_to_publish": true,
    "safe_to_alert": true
  }
}

[Server → Client]
{
  "type": "brief_published",
  "trigger_id": "trg_abc123",
  "payload": {
    "brief_id": "brf_qwe",
    "cited_md_url": "https://cited.md/regradar/fcra-605-stale-data-2026-05-23"
  }
}

[Server → Client]
{
  "type": "datadog_alert_sent",
  "trigger_id": "trg_abc123",
  "payload": {
    "alert_id": "dda_rty",
    "control_id": "CTRL-FCRA-STALE-DATA",
    "severity": "critical"
  }
}

[Server → Client]
{
  "type": "trigger_complete",
  "trigger_id": "trg_abc123",
  "payload": {
    "duration_ms": 6420,
    "agents_run": ["impact_analysis", "auditor"],
    "actions_taken": ["control_updated", "brief_published", "datadog_alerted"]
  }
}
```

### Inbound from client

| Type | Payload | Purpose |
|---|---|---|
| `subscribe` | `{topics: ["trigger.*"]}` | Subscribe to specific message types (default: all) |
| `unsubscribe` | `{topics: [...]}` | Unsubscribe |
| `ping` | `{}` | Keepalive every 30s |

---

## 5. WebSocket Connection Manager

```python
# backend/api/ws_stream.py
"""WebSocket stream for live trigger updates."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Header, WebSocket, WebSocketDisconnect

from backend.utils.logging import get_logger

log = get_logger(__name__)
router = APIRouter()


class StreamManager:
    """Singleton broadcasting manager."""

    def __init__(self):
        self.connections: dict[str, WebSocket] = {}

    async def connect(self, client_id: str, ws: WebSocket):
        await ws.accept()
        self.connections[client_id] = ws
        log.info("ws.connected", client_id=client_id)

    def disconnect(self, client_id: str):
        self.connections.pop(client_id, None)
        log.info("ws.disconnected", client_id=client_id)

    async def broadcast(self, message: dict):
        """Send to all connected clients. Drop failed ones."""
        dead = []
        for cid, ws in self.connections.items():
            try:
                await ws.send_json(message)
            except Exception as e:
                log.warning("ws.send_failed", client_id=cid, error=str(e))
                dead.append(cid)
        for cid in dead:
            self.disconnect(cid)


stream = StreamManager()


def emit(*, type_: str, payload: dict, trigger_id: str | None = None, agent_id: str | None = None):
    """Fire-and-forget broadcast. Called from agent runs + orchestrator."""
    msg = {
        "type": type_,
        "payload": payload,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message_id": str(uuid.uuid4()),
    }
    if trigger_id:
        msg["trigger_id"] = trigger_id
    if agent_id:
        msg["agent_id"] = agent_id
    asyncio.create_task(stream.broadcast(msg))


@router.websocket("/ws/stream")
async def websocket_endpoint(ws: WebSocket, x_api_key: str | None = Header(None)):
    # Hackathon auth: single static key from env
    import os
    if x_api_key != os.environ.get("APP_DEMO_API_KEY", "regradar-demo"):
        await ws.close(code=4001, reason="Unauthorized")
        return

    client_id = str(uuid.uuid4())
    await stream.connect(client_id, ws)

    try:
        # Send connected event
        await ws.send_json({
            "type": "connected",
            "payload": {"client_id": client_id},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message_id": str(uuid.uuid4()),
        })

        while True:
            raw = await ws.receive_json()
            msg_type = raw.get("type")
            if msg_type == "ping":
                await ws.send_json({
                    "type": "pong",
                    "payload": {},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message_id": str(uuid.uuid4()),
                })
            elif msg_type in ("subscribe", "unsubscribe"):
                # For hackathon: all clients get all events; ignore subscribe filtering
                pass
            else:
                log.warning("ws.unknown_msg_type", type=msg_type)
    except WebSocketDisconnect:
        stream.disconnect(client_id)
    except Exception as e:
        log.error("ws.handler_error", error=str(e), client_id=client_id)
        stream.disconnect(client_id)
```

Agent code calls `emit(...)` directly:

```python
# Inside backend/agents/impact_analysis.py
from backend.api.ws_stream import emit

async def run_impact_analysis(input):
    emit(type_="agent_started", trigger_id=input.trigger_id,
         agent_id="impact_analysis", payload={"model": "gemini-3.5-flash"})
    ...
    emit(type_="agent_completed", trigger_id=input.trigger_id,
         agent_id="impact_analysis",
         payload={"impact_report_id": report_id, "total_breach_count": breach_count, ...})
```

---

## 6. Error Codes

| Code | HTTP Status | When |
|---|---|---|
| `UNAUTHORIZED` | 401 | Missing or invalid X-API-Key |
| `PAYMENT_REQUIRED` | 402 | x402 payment required (compliance-brief route) |
| `NOT_FOUND` | 404 | Resource doesn't exist |
| `VALIDATION_ERROR` | 422 | Pydantic validation failed |
| `INTEGRATION_FAILURE` | 502 | External service down |
| `CONTROL_NOT_FOUND` | 404 | Control ID unknown |
| `REGULATION_NOT_FOUND` | 404 | Regulation ID unknown |
| `TRIGGER_NOT_FOUND` | 404 | Trigger ID unknown |
| `AGENT_TIMEOUT` | 504 | Agent execution exceeded budget |
| `AUDITOR_REJECTED_FINAL` | 503 | Auditor rejected after max retries |
| `RATE_LIMIT_EXCEEDED` | 429 | Upstream API quota hit |
| `INTERNAL_ERROR` | 500 | Catchall |

---

## 7. FastAPI Configuration

```python
# backend/main.py
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.utils import env
env.validate()                             # raises if any required var missing

from backend.utils.logging import configure_logging, get_logger
from backend.integrations.clickhouse_client import get_client as get_ch
from backend.integrations.vertex_ai import _get_provider, _get_genai_client
from backend.integrations.nimble import _get_client as get_nimble
from backend.integrations.senso import _get_http as get_senso
from backend.orchestrator.event_poller import event_poller_loop
from backend.agents.policy_crawler import policy_crawler_loop
from backend.agents.monitoring import monitoring_loop

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm all integrations + start background loops."""
    configure_logging()
    log.info("regradar.starting")

    # Pre-warm singletons
    await get_ch()
    _get_provider()
    _get_genai_client()
    get_nimble()
    get_senso()

    # Background loops
    tasks = [
        asyncio.create_task(policy_crawler_loop(), name="policy_crawler_loop"),
        asyncio.create_task(event_poller_loop(), name="event_poller_loop"),
        asyncio.create_task(monitoring_loop(), name="monitoring_loop"),
    ]
    app.state.background_tasks = tasks
    log.info("regradar.background_loops_started", n=len(tasks))

    yield

    log.info("regradar.shutting_down")
    for t in tasks:
        t.cancel()
    for t in tasks:
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(title="RegRadar", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=env.get_list("APP_CORS_ORIGINS"),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from backend.api import (
    routes_health, routes_issuer, routes_controls, routes_accounts,
    routes_regulations, routes_triggers, routes_agents,
    routes_published_briefs, routes_brief_x402, routes_internal, ws_stream,
)
app.include_router(routes_health.router)
app.include_router(routes_issuer.router)
app.include_router(routes_controls.router)
app.include_router(routes_accounts.router)
app.include_router(routes_regulations.router)
app.include_router(routes_triggers.router)
app.include_router(routes_agents.router)
app.include_router(routes_published_briefs.router)
app.include_router(routes_brief_x402.router)        # x402-gated
app.include_router(routes_internal.router)          # demo trigger
app.include_router(ws_stream.router)
```

---

## AI Tool Hints

1. **Build routes in this order:** health → issuer → controls → accounts → regulations → triggers → agents → internal/trigger → published-briefs → compliance-brief (x402) → ws_stream. Each builds on the previous's models.

2. **`/api/internal/trigger` is the demo controller.** Test it first with curl before wiring the frontend.

3. **WebSocket emission uses fire-and-forget tasks.** Don't await `broadcast()` from inside agent code -- it would block the agent run.

4. **The x402-gated route MUST sit in its own router file** (`routes_brief_x402.py`) so the middleware decorator doesn't accidentally bleed onto other routes.

5. **All Pydantic models in this file should live in `backend/data/models.py`** as a single catalog. Routes import from there. Don't redefine inline.
