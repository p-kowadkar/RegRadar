# API.md

Complete FastAPI endpoint and WebSocket protocol specification.

---

## 0. Conventions

- **Base URL** (local dev): `http://localhost:8000`
- **All routes prefixed with `/api/`** except WebSocket which is `/ws/`
- **All responses are JSON** with consistent envelope structure
- **All routes are async**
- **Pydantic v2** for all request/response models
- **CORS** enabled for `http://localhost:5173` (Vite default) and Lovable deployment URL
- **Auth** for hackathon: a single static API key in header `X-API-Key` (we're not building real auth)

---

## 1. Response Envelope

Every response follows this shape:

```python
class APIResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[ErrorDetail] = None
    metadata: dict[str, Any] = {}    # request_id, duration_ms, etc.

class ErrorDetail(BaseModel):
    code: str                         # "INTEGRATION_FAILURE", "NOT_FOUND", etc.
    message: str
    details: dict[str, Any] = {}
```

### Sample Success Response

```json
{
  "success": true,
  "data": {
    "control_id": "CTRL-001",
    "status": "FAILING",
    "breach_count": 214
  },
  "error": null,
  "metadata": {
    "request_id": "req_abc123",
    "duration_ms": 47
  }
}
```

### Sample Error Response

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "CONTROL_NOT_FOUND",
    "message": "Control with ID CTRL-999 does not exist",
    "details": {"control_id": "CTRL-999"}
  },
  "metadata": {
    "request_id": "req_xyz789",
    "duration_ms": 12
  }
}
```

---

## 2. Routes Index

| Method | Path | Purpose | Route File |
|---|---|---|---|
| GET | `/api/health` | Liveness check | `main.py` |
| GET | `/api/health/integrations` | Integration smoke test | `main.py` |
| GET | `/api/company` | Get company profile | `routes_company.py` |
| PUT | `/api/company` | Update company profile | `routes_company.py` |
| POST | `/api/company/data-object` | Add data object → triggers Mapper | `routes_company.py` |
| GET | `/api/graph/stats` | KG stats for KPI cards | `routes_graph.py` |
| GET | `/api/graph/nodes` | List nodes (filterable) | `routes_graph.py` |
| GET | `/api/graph/nodes/{node_id}` | Detail for one node | `routes_graph.py` |
| GET | `/api/graph/edges` | List edges (filterable) | `routes_graph.py` |
| POST | `/api/graph/simulate` | "What if" simulation | `routes_graph.py` |
| GET | `/api/feed` | Regulatory feed (paginated) | `routes_feed.py` |
| GET | `/api/feed/{regulation_id}` | One regulation full detail | `routes_feed.py` |
| GET | `/api/feed/{regulation_id}/versions` | Version history of a reg | `routes_feed.py` |
| GET | `/api/feed/{regulation_id}/diff` | Diff between two versions | `routes_feed.py` |
| GET | `/api/controls` | All controls with status | `routes_controls.py` |
| GET | `/api/controls/{control_id}` | One control detail | `routes_controls.py` |
| POST | `/api/controls/{control_id}/test` | Manually retest | `routes_controls.py` |
| GET | `/api/controls/{control_id}/history` | Test result trend | `routes_controls.py` |
| GET | `/api/monitor/sources` | Source health (Watcher) | `routes_monitor.py` |
| GET | `/api/monitor/agents` | Agent runtime stats | `routes_monitor.py` |
| GET | `/api/monitor/audit-trail` | Recent audit events | `routes_monitor.py` |
| POST | `/api/demo/trigger` | Manually stage a demo event | `routes_demo.py` |
| GET | `/api/demo/scenarios` | List staged scenarios | `routes_demo.py` |
| WS | `/ws/chat` | Bidirectional chat + push | `ws_chat.py` |

---

## 3. Detailed Endpoint Specs

### 3.1 GET `/api/health`

Simple liveness check.

**Response:**
```json
{
  "success": true,
  "data": {"status": "ok", "version": "0.1.0"},
  "error": null,
  "metadata": {"request_id": "..."}
}
```

### 3.2 GET `/api/health/integrations`

Smoke-test every integration. Used by `scripts/verify_env.py` and demo dashboard.

**Response:**
```json
{
  "success": true,
  "data": {
    "vertex_ai": {"status": "ok", "latency_ms": 230},
    "clickhouse": {"status": "ok", "latency_ms": 18},
    "nimble": {"status": "ok", "latency_ms": 412},
    "firecrawl": {"status": "ok", "latency_ms": 380},
    "datadog": {"status": "ok", "latency_ms": 88},
    "luminai": {"status": "degraded", "error": "API key missing"}
  }
}
```

### 3.3 GET `/api/company`

```python
class CompanyProfileResponse(BaseModel):
    company_id: str
    name: str
    type: str
    annual_volume_usd: float
    employee_count: int
    headquarters: str
    sponsor_bank: Optional[str]
    services: list[str]
    data_objects: list[str]
    states_operating_in: list[str]
    customer_segments: list[str]
    portfolios_summary: PortfolioSummary    # see below

class PortfolioSummary(BaseModel):
    derivatives: dict   # {"count": 3000, "total_notional_usd": 12.8e9}
    bonds: dict
    lending: dict
```

### 3.4 POST `/api/company/data-object`

Adds a new data object to the company profile. **Triggers a `data_object_added` event on the Blackboard.**

```python
class AddDataObjectRequest(BaseModel):
    data_object_id: str           # snake_case
    name: str
    description: str
    classified_as: list[str]      # e.g. ["PII"]
    metadata: dict = {}

class AddDataObjectResponse(BaseModel):
    data_object_id: str
    task_id: str                   # the orchestration task triggered
    estimated_completion_seconds: int
```

The frontend should subscribe to `/ws/chat` and listen for `task_complete` events with this `task_id`.

### 3.5 GET `/api/graph/stats`

```python
class GraphStatsResponse(BaseModel):
    nodes_total: int
    edges_total: int
    nodes_by_type: dict[str, int]
    edges_by_type: dict[str, int]
    most_connected_data_object: str
    most_referenced_regulation: str
```

### 3.6 GET `/api/graph/nodes`

Query params:
- `node_type` (optional, repeatable)
- `search` (text search by name)
- `limit` (default 50, max 500)
- `offset` (default 0)

### 3.7 POST `/api/graph/simulate`

"What if" simulation. Computes new edges WITHOUT persisting.

```python
class SimulationRequest(BaseModel):
    change_type: Literal[
        "add_jurisdiction", "add_data_object", "add_product"
    ]
    payload: dict        # depends on change_type

class SimulationResponse(BaseModel):
    new_edges_simulated: list[ProposedEdge]
    affected_regulations: list[str]
    affected_controls: list[str]
    summary: str
```

Example request:
```json
{
  "change_type": "add_jurisdiction",
  "payload": {"jurisdiction": "eu"}
}
```

### 3.8 GET `/api/feed`

Query params:
- `severity` (CRITICAL | HIGH | MEDIUM | LOW)
- `regulator`
- `topic`
- `since` (ISO 8601 datetime)
- `limit` (default 25, max 100)
- `offset`

```python
class FeedItem(BaseModel):
    regulation_id: str
    title: str
    summary: str
    severity: str
    regulator: list[str]
    jurisdiction: list[str]
    topic: list[str]
    change_type: str
    fetched_at: datetime
    affected_data_objects_count: int
    affected_positions_count: Optional[int]
    has_active_controls: bool

class FeedResponse(BaseModel):
    items: list[FeedItem]
    total: int
    has_more: bool
```

### 3.9 GET `/api/feed/{regulation_id}/diff`

Query params:
- `from_version_id` (optional, default = previous version)
- `to_version_id` (optional, default = latest)

```python
class DiffResponse(BaseModel):
    regulation_id: str
    from_version: VersionMeta
    to_version: VersionMeta
    diff_text: str           # unified diff format
    semantic_summary: str    # LLM-generated diff summary
    threshold_changes: list[ThresholdChange]
```

### 3.10 GET `/api/controls`

```python
class ControlSummary(BaseModel):
    control_id: str
    name: str
    current_status: str
    owner_team: str
    last_tested_at: Optional[datetime]
    affected_positions_count: int

class ControlsListResponse(BaseModel):
    controls: list[ControlSummary]
    summary: dict   # {"PASSING": 5, "AT_RISK": 2, "FAILING": 1}
```

### 3.11 POST `/api/controls/{control_id}/test`

Manually retest a control. Synchronous (sub-second).

```python
class ControlTestResponse(BaseModel):
    control_id: str
    status: str
    breach_count: int
    at_risk_count: int
    tested_at: datetime
    sample_breach_ids: list[str]
    execution_time_ms: int
```

### 3.12 GET `/api/monitor/agents`

```python
class AgentRuntimeStats(BaseModel):
    agent_id: str
    display_name: str
    model: str
    total_invocations: int
    silent_count: int
    primary_claims: int
    supporting_claims: int
    cross_talk_claims: int
    avg_latency_ms: float
    tokens_in_total: int
    tokens_out_total: int
    last_invocation_at: Optional[datetime]
    last_error_at: Optional[datetime]

class AgentMonitorResponse(BaseModel):
    agents: list[AgentRuntimeStats]
    chain_health: ChainHealthMetric
```

### 3.13 POST `/api/demo/trigger`

Manually stage a demo event (for use during the pitch).

```python
class DemoTriggerRequest(BaseModel):
    scenario: Literal[
        "cftc_margin_amendment",
        "sec_cyber_disclosure",
        "ofac_sanctions_add",
        "ny_dfs_amendment",
        "cfpb_disclosure_update"
    ]
    artificial_delay_ms: int = 0   # for dramatic effect

class DemoTriggerResponse(BaseModel):
    scenario: str
    task_id: str
    estimated_chain_duration_seconds: int
```

---

## 4. WebSocket Protocol -- `/ws/chat`

### Connection

Client connects with `X-API-Key` header. Server echoes a `connected` event.

```
ws://localhost:8000/ws/chat
```

### Message Envelope

EVERY message (both directions) has this shape:

```typescript
interface WSMessage {
  type: WSMessageType;
  payload: Record<string, any>;
  timestamp: string;            // ISO 8601
  message_id: string;           // UUID
  task_id?: string;             // ties to blackboard
  agent_id?: string;            // sender agent if applicable
}
```

### Inbound Message Types (Client → Server)

| Type | Payload | Purpose |
|---|---|---|
| `user_message` | `{message: string}` | User sends chat message |
| `subscribe` | `{topics: string[]}` | Subscribe to push types |
| `unsubscribe` | `{topics: string[]}` | Unsubscribe |
| `cancel_task` | `{task_id: string}` | Cancel an in-flight task |
| `ping` | `{}` | Keepalive |

### Outbound Message Types (Server → Client)

| Type | Sent When |
|---|---|
| `connected` | Connection established |
| `task_started` | Orchestration begins |
| `agent_claim` | Agent claims a turn |
| `agent_silent` | Agent decides to stay silent (debug) |
| `agent_thinking` | Agent execute() started |
| `agent_response_partial` | Streaming agent token (optional) |
| `agent_response` | Full agent output ready |
| `auditor_verdict` | Auditor decision |
| `task_complete` | Full chain done |
| `task_failed` | Hard failure |
| `proactive_message` | Push from heartbeat/watcher |
| `control_status_changed` | Control updated |
| `system_notification` | UI alert |
| `pong` | Response to ping |

### Sample Flow -- CFTC Demo

```
[Server → Client]
{
  "type": "task_started",
  "task_id": "task_abc123",
  "payload": {
    "trigger_type": "new_regulation",
    "title": "CFTC Margin Requirements Amendment",
    "estimated_duration_seconds": 14
  },
  "timestamp": "2026-05-23T13:00:00.123Z",
  "message_id": "msg_001"
}

[Server → Client]
{
  "type": "agent_claim",
  "task_id": "task_abc123",
  "agent_id": "the_classifier",
  "payload": {
    "response_type": "primary",
    "relevance_score": 0.95
  },
  ...
}

[Server → Client]
{
  "type": "agent_response",
  "task_id": "task_abc123",
  "agent_id": "the_classifier",
  "payload": {
    "output": { /* ClassifierOutput */ },
    "duration_ms": 3000
  },
  ...
}

// ... more agent_response messages

[Server → Client]
{
  "type": "control_status_changed",
  "task_id": "task_abc123",
  "payload": {
    "control_id": "CTRL-001",
    "old_status": "PASSING",
    "new_status": "FAILING",
    "breach_count": 214
  },
  ...
}

[Server → Client]
{
  "type": "auditor_verdict",
  "task_id": "task_abc123",
  "agent_id": "the_auditor",
  "payload": {
    "verdict": "approved",
    "warnings": [],
    "citations_verified": 7
  },
  ...
}

[Server → Client]
{
  "type": "task_complete",
  "task_id": "task_abc123",
  "payload": {
    "duration_ms": 13800,
    "agents_spoken": ["the_classifier", "the_mapper", "the_analyst", "the_advisor"]
  },
  ...
}
```

### Proactive Push Example

When a regulation is detected outside of any user-initiated task:

```
[Server → Client]
{
  "type": "proactive_message",
  "task_id": "task_xyz789",
  "payload": {
    "trigger_type": "new_regulation",
    "preview": "New SEC cybersecurity disclosure rule detected -- 4 of your data objects affected.",
    "severity": "HIGH"
  },
  ...
}
```

The frontend then opens the task in chat view, showing the cascade as it streams.

---

## 5. WebSocket Connection Manager

```python
# backend/api/ws_chat.py

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, Set
import structlog
import asyncio

log = structlog.get_logger()


class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, WebSocket] = {}     # user_id -> ws
        self.subscriptions: Dict[str, Set[str]] = {}  # user_id -> topics

    async def connect(self, user_id: str, ws: WebSocket):
        await ws.accept()
        self.active[user_id] = ws
        self.subscriptions[user_id] = set([
            "task_*", "proactive_message",
            "control_status_changed", "system_notification"
        ])
        log.info("ws_connected", user_id=user_id)

    def disconnect(self, user_id: str):
        self.active.pop(user_id, None)
        self.subscriptions.pop(user_id, None)
        log.info("ws_disconnected", user_id=user_id)

    async def send_to_user(self, user_id: str, message: dict):
        ws = self.active.get(user_id)
        if ws is None:
            log.warning("ws_send_failed_no_user", user_id=user_id)
            return
        try:
            await ws.send_json(message)
        except Exception as e:
            log.warning("ws_send_failed", user_id=user_id, error=str(e))
            self.disconnect(user_id)

    async def broadcast(self, message: dict, topic_filter: str | None = None):
        """Send to all subscribers (for hackathon: just send to all)."""
        await asyncio.gather(*[
            self.send_to_user(uid, message)
            for uid in list(self.active.keys())
        ])


# Singleton
manager = ConnectionManager()


@router.websocket("/ws/chat")
async def websocket_endpoint(ws: WebSocket, x_api_key: str = Header(None)):
    if x_api_key != settings.API_KEY:
        await ws.close(code=4001, reason="Unauthorized")
        return
    
    user_id = "default_user"  # hackathon: single-user demo
    await manager.connect(user_id, ws)
    
    try:
        # Send initial state
        await manager.send_to_user(user_id, {
            "type": "connected",
            "payload": {"user_id": user_id, "subscriptions": list(manager.subscriptions[user_id])},
            "timestamp": now_iso(),
            "message_id": uuid7(),
        })
        
        while True:
            raw = await ws.receive_json()
            msg_type = raw.get("type")
            
            if msg_type == "ping":
                await manager.send_to_user(user_id, {
                    "type": "pong", "payload": {}, "timestamp": now_iso(),
                    "message_id": uuid7(),
                })
            elif msg_type == "user_message":
                # Spawn orchestration task
                asyncio.create_task(handle_user_message(user_id, raw["payload"]))
            elif msg_type == "subscribe":
                manager.subscriptions[user_id].update(raw["payload"]["topics"])
            elif msg_type == "unsubscribe":
                manager.subscriptions[user_id].difference_update(raw["payload"]["topics"])
            elif msg_type == "cancel_task":
                await cancel_task(raw["payload"]["task_id"])
            else:
                log.warning("ws_unknown_message_type", type=msg_type)
    
    except WebSocketDisconnect:
        manager.disconnect(user_id)
    except Exception as e:
        log.error("ws_handler_error", error=str(e), user_id=user_id)
        manager.disconnect(user_id)


async def handle_user_message(user_id: str, payload: dict):
    """Create blackboard, run orchestration, stream results."""
    from backend.orchestrator.orchestrator import Orchestrator
    
    orchestrator = Orchestrator()
    blackboard = orchestrator.create_blackboard(
        trigger_type="user_message",
        trigger_payload=payload,
        user_id=user_id,
    )
    
    # Notify task started
    await manager.send_to_user(user_id, {
        "type": "task_started",
        "task_id": blackboard.task_id,
        "payload": {"trigger_type": "user_message"},
        ...
    })
    
    # Run with streaming hook
    await orchestrator.orchestrate(
        blackboard,
        stream_callback=lambda msg: manager.send_to_user(user_id, msg)
    )
    
    # Final
    await manager.send_to_user(user_id, {
        "type": "task_complete",
        "task_id": blackboard.task_id,
        ...
    })
```

---

## 6. Error Codes Reference

| Code | HTTP Status | When |
|---|---|---|
| `UNAUTHORIZED` | 401 | Missing or invalid X-API-Key |
| `NOT_FOUND` | 404 | Resource doesn't exist |
| `VALIDATION_ERROR` | 422 | Pydantic validation failed |
| `INTEGRATION_FAILURE` | 502 | Sponsor integration down |
| `CONTROL_NOT_FOUND` | 404 | Specific control doesn't exist |
| `REGULATION_NOT_FOUND` | 404 | Specific regulation doesn't exist |
| `TASK_NOT_FOUND` | 404 | Task ID unknown |
| `AGENT_TIMEOUT` | 504 | Agent execution exceeded budget |
| `AUDITOR_REJECTED_FINAL` | 503 | Auditor rejected after max retries |
| `RATE_LIMIT_EXCEEDED` | 429 | API quota hit |
| `INTERNAL_ERROR` | 500 | Catchall |

---

## 7. FastAPI Configuration

```python
# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog

from backend.config import settings
from backend.logging_setup import configure_logging
from backend.orchestrator.heartbeat import HeartbeatService

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup + shutdown."""
    configure_logging()
    log.info("regradar_starting")
    
    # Start heartbeat
    heartbeat = HeartbeatService()
    heartbeat_task = asyncio.create_task(heartbeat.run())
    app.state.heartbeat = heartbeat
    app.state.heartbeat_task = heartbeat_task
    
    yield
    
    # Shutdown
    log.info("regradar_shutting_down")
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="RegRadar API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        settings.FRONTEND_URL,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Register routes
from backend.api import (
    routes_company, routes_graph, routes_feed,
    routes_controls, routes_monitor, routes_demo, ws_chat,
)
app.include_router(routes_company.router, prefix="/api/company", tags=["company"])
app.include_router(routes_graph.router, prefix="/api/graph", tags=["graph"])
app.include_router(routes_feed.router, prefix="/api/feed", tags=["feed"])
app.include_router(routes_controls.router, prefix="/api/controls", tags=["controls"])
app.include_router(routes_monitor.router, prefix="/api/monitor", tags=["monitor"])
app.include_router(routes_demo.router, prefix="/api/demo", tags=["demo"])
app.include_router(ws_chat.router)


@app.get("/api/health")
async def health():
    return {"success": True, "data": {"status": "ok", "version": "0.1.0"}}
```

---

Read [FRONTEND.md](FRONTEND.md) next.
