# ARCHITECTURE.md

System architecture, data flow, and core patterns for RegRadar.

---

## 1. The Big Picture

```
┌──────────────────────────────────────────────────────────────────┐
│                  FRONTEND (React + TypeScript)                    │
│  Dashboard │ Group Chat │ Knowledge Graph │ Controls Board        │
└──────────────────────────┬───────────────────────────────────────┘
                           │ WebSocket /ws/chat   +   REST /api/*
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                ORCHESTRATOR (FastAPI, Python 3.11)                │
│                                                                   │
│  ┌────────────────────────┐    ┌────────────────────────────┐    │
│  │ Blackboard             │    │ Heartbeat / Watcher        │    │
│  │ (in-memory shared      │    │ (asyncio scheduled         │    │
│  │  state + claims)       │    │  pollers)                  │    │
│  └─────────────┬──────────┘    └────────────┬───────────────┘    │
│                │                             │                    │
│  ┌─────────────▼─────────────────────────────▼──────────────┐    │
│  │  AGENT POOL (asyncio)                                     │    │
│  │  Watcher → Classifier → Mapper → Analyst → Advisor        │    │
│  │  + Auditor (runs alongside all)                           │    │
│  └─────────────────────────┬──────────────────────────────────┘   │
│                            │                                       │
│  ┌─────────────────────────▼──────────────────────────────────┐   │
│  │  LLM-AS-JUDGE: The Auditor                                 │   │
│  │  Vertex AI Check Grounding + Gemini 3.1 Pro                │   │
│  └────────────────────────────────────────────────────────────┘   │
└────┬──────────────┬───────────────┬──────────────────┬────────────┘
     │              │               │                  │
┌────▼────┐   ┌─────▼──────┐   ┌────▼──────┐   ┌──────▼──────┐
│ClickHse │   │   Nimble   │   │ Datadog   │   │   Luminai   │
│         │   │  Firecrawl │   │           │   │             │
│ KG +    │   │  scraping  │   │ LLM Obs + │   │ Workflow    │
│ vectors │   │            │   │ control   │   │ execution   │
│ portfo- │   │            │   │ monitoring│   │ (SAR, GRC   │
│ lios +  │   │            │   │           │   │  updates)   │
│ controls│   │            │   │           │   │             │
└─────────┘   └────────────┘   └───────────┘   └─────────────┘
```

---

## 2. Core Pattern: The Blackboard

### What it is

A shared in-memory `Blackboard` object that holds the current state of a "task" (either a user message or a proactive event). Agents READ the blackboard, decide independently if they should respond, and either claim a turn or stay silent.

### Why not a router?

A traditional router has a single function that maps inputs → agents. Adding/removing agents means changing the router. Edge cases force `if/else` chains.

The blackboard pattern:
- Agents self-select (no central decision)
- Adding an agent = adding a new agent class, zero changes elsewhere
- Adding the SAME agent in multiple contexts (e.g. The Classifier in both reg events AND user questions) means zero code duplication
- The Auditor runs alongside the others, not at a fixed pipeline position

### The Data Structure

```python
# backend/orchestrator/blackboard.py

from pydantic import BaseModel
from datetime import datetime
from typing import Any, Optional

class Blackboard(BaseModel):
    """Shared state for one orchestration cycle."""

    # The trigger
    task_id: str                          # UUID
    trigger_type: Literal[
        "user_message", "new_regulation", "reg_amended",
        "deadline_approaching", "coverage_gap", "data_object_added",
        "regulatory_conflict"
    ]
    trigger_payload: dict[str, Any]       # The originating event
    user_id: Optional[str] = None
    created_at: datetime

    # Company context (snapshot at task start)
    company_profile: dict[str, Any]       # NovaPay profile
    
    # Agent outputs accumulate here
    classifier_output: Optional["ClassifierOutput"] = None
    mapper_output: Optional["MapperOutput"] = None
    analyst_output: Optional["AnalystOutput"] = None
    advisor_output: Optional["AdvisorOutput"] = None
    auditor_output: Optional["AuditorOutput"] = None

    # Claims from agents who want to speak
    active_claims: list["AgentClaim"] = []

    # Final output ordering after resolution
    ordered_responses: list[str] = []     # agent IDs in delivery order

    # Audit metadata
    chain_complete: bool = False
    chain_duration_ms: Optional[float] = None
```

### Agent Claims

```python
class AgentClaim(BaseModel):
    """An agent's declaration: I have something worth saying."""

    agent_id: str                          # "the_classifier"
    relevance_score: float                 # 0.0 - 1.0
    response_type: Literal["primary", "supporting", "cross_talk"]
    depends_on: list[str] = []             # other agent_ids
    estimated_tokens: int = 0
    reasoning: str                         # why this agent claims
```

### Resolution Rules (enforced in `orchestrator.py`)

1. **Max 3 agents per task** (flood control) -- except the Auditor which always runs
2. **One primary only** -- highest `relevance_score` wins
3. **Supporting and cross_talk can stack** (max 1 each)
4. **Cross-talk threshold higher** (`>= 0.6`) than supporting (`>= 0.5`)
5. **Dependencies create ordering** (topological sort)
6. **The Auditor runs LAST, always** -- validates everything before delivery

---

## 3. The 3-Phase Eval (Inside Each Agent)

Each LLM-based agent runs three phases when `evaluate_relevance` is called on it:

### Phase 1: Hard Filter (no LLM)

Rule-based, instant. If this fails, the agent stays silent. No LLM call.

```python
# backend/agents/pharmacist.py example pattern
def hard_filter(self, blackboard: Blackboard) -> bool:
    """Return True if agent should NOT speak."""
    # The Mapper stays silent if there's no classification yet
    if blackboard.classifier_output is None:
        return True
    # The Mapper stays silent if classifier confidence too low
    if blackboard.classifier_output.confidence < 0.5:
        return True
    return False
```

### Phase 2: Soft Score (small LLM call)

Cheap Gemini 3.5 Flash call. Returns a `0.0 - 1.0` relevance score.

```python
async def score_relevance(self, blackboard: Blackboard) -> float:
    """Return relevance score 0.0 - 1.0."""
    prompt = f"""Rate 0.0-1.0: relevance of {self.agent_id} to this task.
    Trigger: {blackboard.trigger_type}
    Classification: {blackboard.classifier_output.model_dump_json()}
    Return ONLY a float."""
    
    result = await vertex_ai.generate(
        model="gemini-3.5-flash",
        prompt=prompt,
        max_tokens=8,
    )
    return self._parse_score(result)
```

### Phase 3: Claim Type (deterministic)

Based on the score, decide claim type and dependencies:

```python
def classify_claim_type(self, score: float, blackboard: Blackboard) -> AgentClaim | None:
    if score < self.MIN_THRESHOLD:
        return None  # silent
    
    if score >= 0.85:
        return AgentClaim(
            agent_id=self.agent_id,
            relevance_score=score,
            response_type="primary",
            depends_on=self.PRIMARY_DEPENDENCIES,
            reasoning="High relevance to trigger"
        )
    elif score >= 0.65:
        return AgentClaim(
            agent_id=self.agent_id,
            relevance_score=score,
            response_type="supporting",
            depends_on=self.SUPPORTING_DEPENDENCIES,
            reasoning="Moderate relevance, adds context"
        )
    else:  # 0.5 - 0.65
        return AgentClaim(
            agent_id=self.agent_id,
            relevance_score=score,
            response_type="cross_talk",
            depends_on=[],
            reasoning="Tangential relevance, only fires if no flood"
        )
```

---

## 4. Trigger Types & Pipelines

### Trigger Type 1: `new_regulation` (Proactive)

Source: The Watcher detects a new document via Nimble or APIs.

**Expected agent chain (claims):**
- The Classifier: PRIMARY (always speaks)
- The Mapper: PRIMARY chained, depends_on Classifier
- The Analyst: SUPPORTING, depends_on Mapper
- The Advisor: SUPPORTING, depends_on Analyst
- The Auditor: runs last

### Trigger Type 2: `reg_amended` (Proactive)

Source: The Watcher detects existing regulation's hash changed.

Same chain as new_regulation, but higher urgency. Tracked separately for analytics.

### Trigger Type 3: `deadline_approaching` (Heartbeat)

Source: Heartbeat scheduler runs daily, checks regulations where `comment_close - now() < 14 days`.

**Expected chain:**
- The Advisor: PRIMARY (just generate reminder)
- The Auditor: runs last

### Trigger Type 4: `coverage_gap` (Heartbeat)

Source: Heartbeat scheduler runs hourly, finds sources not scraped in 24h.

**No agents -- this is a system alert.** Posts directly to UI notification feed.

### Trigger Type 5: `data_object_added` (User-driven)

Source: User adds a new data object to NovaPay profile.

**Expected chain:**
- The Mapper: PRIMARY (rebuild graph edges)
- The Analyst: SUPPORTING (assess impact of new edges)
- The Advisor: SUPPORTING (suggest control updates)
- The Auditor: runs last

### Trigger Type 6: `user_message` (Interactive)

Source: User types a question in the chat.

**Variable chain based on classifier output:**
- Always: One PRIMARY agent based on intent classification
- Sometimes: 1-2 SUPPORTING agents for cross-talk
- Always: The Auditor last

---

## 5. Data Flow Examples

### Example A: The CFTC Margin Rule (showcase demo)

```
t=0    Watcher detects CFTC final rule via Federal Register API
       ├── Hash differs from stored version → new doc detected
       └── Posts to Blackboard with trigger_type="new_regulation"

t+50ms All agents run evaluate_relevance() in parallel
       ├── Classifier: score 0.95 → PRIMARY claim
       ├── Mapper: score 0.92, depends_on=["the_classifier"] → PRIMARY claim
       ├── Analyst: score 0.88, depends_on=["the_mapper"] → SUPPORTING claim
       ├── Advisor: score 0.85, depends_on=["the_analyst"] → SUPPORTING claim
       └── Auditor: always runs → runs after all others

t+200ms Orchestrator resolves: order = [Classifier, Mapper, Analyst, Advisor, Auditor]

t+3s   Classifier produces output:
       {jurisdiction: ["us_federal"], regulator: ["CFTC"],
        topic: ["margin_collateral"], severity: "HIGH",
        threshold_changes: [{metric: "initial_margin",
                             old: 0.06, new: 0.08}]}

t+5s   Mapper produces output:
       {affected_data_objects: ["derivatives_portfolio"],
        portfolio_scan: {table: "derivatives_portfolio",
                         filter: "instrument_type='IR_SWAP' AND cleared=false",
                         affected_positions: 847,
                         total_notional_usd: 4_200_000_000}}

t+8s   Analyst produces output:
       {position_classification: {BREACH: 214, AT_RISK: 312, MONITORING: 321},
        risk_exposure: {fine_range: [500_000, 5_000_000], ...}}

t+11s  Advisor produces output:
       {control_updates: [{control_id: "CTRL-001",
                           field: "threshold",
                           old: 0.06, new: 0.08,
                           new_status: "FAILING"}],
        action_plan: [...],
        datadog_alert: {severity: "critical", owner: "risk_team"}}

t+13s  Auditor approves
       ├── Check Grounding API verifies CFTC 23.154 citation → grounded
       ├── Logical consistency: ✓
       ├── No fabrication: ✓
       └── Verdict: approved

t+14s  Stream to frontend:
       ├── WebSocket messages in order
       ├── Datadog alert fires
       └── ClickHouse: audit_trail row written
```

### Example B: User Question -- "What if we expand to EU?"

```
t=0    User types message via WebSocket to /ws/chat
       └── Posts to Blackboard with trigger_type="user_message",
           payload={message: "...", intent: TBD}

t+50ms Classifier evaluates as PRIMARY (intent: jurisdiction_expansion)
       └── Other agents wait for classification

t+1s   Classifier output: {intent: "what_if_jurisdiction_expansion",
                            new_jurisdiction: "eu"}

t+1.1s Mapper evaluates with classification → PRIMARY
       Advisor evaluates → SUPPORTING

t+4s   Mapper queries graph WITHOUT modifying it (simulation mode):
       new_edges_simulated: [
         "customer_pii → GDPR Art. 17",
         "transaction_records → GDPR Art. 5",
         ...
       ]

t+6s   Advisor produces output:
       summary_for_user: "Expanding to EU would add 14 new regulatory
       obligations across GDPR, MiCA, and PSD2. Most significant impact:
       customer_pii now subject to data subject erasure rights. Want me
       to draft a compliance roadmap?"

t+7s   Auditor approves → stream to frontend
```

---

## 6. The Knowledge Graph

The KG lives in ClickHouse as two tables: `kg_nodes` and `kg_edges`. See [DATA_MODEL.md](DATA_MODEL.md) for full schema.

### Node Types

- `data_object` -- e.g. `customer_pii`, `transaction_records`
- `regulation` -- e.g. `cftc_margin_rule_2026`, `gdpr_art_17`
- `article` -- specific articles within regulations
- `obligation` -- specific requirements derived from regulations
- `jurisdiction` -- `us_federal`, `eu`, `us_state_ny`
- `regulator` -- `SEC`, `CFTC`, `FCA`
- `product` -- `cross_border_remittance`, `bnpl_lending`
- `customer_segment` -- `us_consumers`, `eu_consumers`
- `portfolio_position` -- references to specific rows in portfolio tables (e.g. `derivative_position_12345`)

### Edge Types

- `applies_to` -- regulation → data_object
- `requires` -- regulation → obligation
- `exempts` -- regulation → data_object (negative edge)
- `cross_references` -- regulation → regulation
- `supersedes` -- regulation → regulation (newer overrides older)
- `amends` -- regulation → regulation
- `collects` -- product → data_object
- `processes` -- product → data_object
- `stores` -- product → data_object (with retention metadata)
- `classified_as` -- data_object → category (e.g. PII)
- `operates_in` -- product → jurisdiction
- `serves` -- product → customer_segment

### Graph Operations

All graph operations go through `backend/data/kg_repo.py`. The Mapper calls:

- `find_applicable_regulations(data_object_id) -> list[Regulation]`
- `find_affected_data_objects(regulation_id) -> list[DataObject]`
- `add_edge(source_id, target_id, edge_type, confidence)`
- `simulate_jurisdiction_addition(jurisdiction) -> list[NewEdge]`
- `multi_hop_traverse(start_node, max_hops, edge_types_filter) -> list[Path]`

---

## 7. Concurrency Model

### Single asyncio event loop per FastAPI worker

- All agent calls are `async def`
- All LLM calls are async via `httpx.AsyncClient`
- All ClickHouse queries use `clickhouse_connect.get_async_client`
- Agent parallel evaluation uses `asyncio.gather(...)`
- Sequential agent execution uses sequential `await` calls

### Concurrency Rules

1. **The Blackboard is per-task** -- never shared across tasks
2. **One orchestration task = one asyncio task** -- spawned via `asyncio.create_task`
3. **WebSocket connections are per-user** -- managed by `ws_chat.py`
4. **Background heartbeat lives in a separate asyncio task** -- started at app startup
5. **Never block the event loop** -- if you need sync I/O, use `asyncio.to_thread()`

### Example: Parallel Evaluation, Sequential Execution

```python
# backend/orchestrator/orchestrator.py

async def orchestrate(blackboard: Blackboard) -> Blackboard:
    """Run one full orchestration cycle."""
    
    # Phase 1: PARALLEL evaluation (all agents at once)
    claims = await asyncio.gather(*[
        agent.evaluate_relevance(blackboard)
        for agent in self.agents
    ])
    active_claims = [c for c in claims if c is not None]
    
    # Phase 2: Resolution (sync, fast)
    ordered = self.resolve(active_claims)
    
    # Phase 3: SEQUENTIAL execution (respects dependencies)
    for claim in ordered:
        agent = self.get_agent(claim.agent_id)
        output = await agent.execute(blackboard)
        self.attach_output(blackboard, agent.agent_id, output)
        # Stream to WebSocket immediately
        await self.stream_partial(blackboard, agent.agent_id, output)
    
    # Phase 4: Auditor runs LAST
    audit_result = await self.auditor.execute(blackboard)
    blackboard.auditor_output = audit_result
    
    if audit_result.verdict == "rejected":
        # Route back to relevant agent for retry
        await self.handle_rejection(blackboard, audit_result)
    
    blackboard.chain_complete = True
    return blackboard
```

---

## 8. Error Handling Strategy

### Exception Hierarchy

```python
# backend/utils/exceptions.py

class RegRadarError(Exception):
    """Base for all RegRadar errors."""

class IntegrationError(RegRadarError):
    """External integration failed."""

class VertexAIError(IntegrationError): pass
class ClickHouseError(IntegrationError): pass
class NimbleError(IntegrationError): pass
class DatadogError(IntegrationError): pass
class LuminaiError(IntegrationError): pass

class AgentError(RegRadarError):
    """Agent execution failed."""

class AgentTimeoutError(AgentError): pass
class AgentOutputInvalidError(AgentError): pass

class DataError(RegRadarError):
    """Data layer error."""

class SeedDataMissingError(DataError): pass
class KnowledgeGraphInconsistentError(DataError): pass
```

### Retry Policy

Every external call uses `tenacity` with exponential backoff:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type(VertexAIError),
)
async def call_gemini(...):
    ...
```

### Graceful Degradation

| Failure | Degradation |
|---|---|
| Vertex AI down | Fall back to OpenRouter (with structured warning logged) |
| Nimble rate-limited | Fall back to Firecrawl silently |
| ClickHouse Cloud down | Fall back to local ClickHouse Docker if running |
| Datadog down | Log alerts to stderr + show in UI notification |
| Luminai down | Mark action as "manual only", surface in UI |
| Auditor rejects 3x | Surface to user with "low confidence" disclaimer |

---

## 9. Observability

### Logging

- `structlog` with JSON output
- Bound context: `task_id`, `agent_id`, `trigger_type`, `correlation_id`
- All logs auto-forwarded to Datadog via `ddtrace-run`

### Metrics (Datadog)

| Metric | Type | Tags |
|---|---|---|
| `regradar.agent.latency_ms` | distribution | `agent_id`, `trigger_type` |
| `regradar.agent.claim_score` | gauge | `agent_id`, `claim_type` |
| `regradar.agent.silent_count` | counter | `agent_id` |
| `regradar.llm.tokens_input` | counter | `model`, `agent_id` |
| `regradar.llm.tokens_output` | counter | `model`, `agent_id` |
| `regradar.watcher.documents_scraped` | counter | `source`, `scraper` |
| `regradar.watcher.changes_detected` | counter | `source` |
| `regradar.kg.nodes_total` | gauge | - |
| `regradar.kg.edges_total` | gauge | - |
| `regradar.controls.failing_count` | gauge | - |
| `regradar.controls.at_risk_count` | gauge | - |
| `regradar.auditor.rejections` | counter | `reason` |

### Traces

LLM Observability auto-instrumented via `ddtrace-run`. Every Gemini call shows up as a span with:
- Input/output messages
- Token counts
- Latency
- Agent context (via custom span tags)

### LLM Observability Custom Tags

```python
from ddtrace.llmobs import LLMObs

LLMObs.annotate(
    span=span,
    input_data=[{"role": "user", "content": prompt}],
    output_data=[{"role": "assistant", "content": response}],
    metadata={
        "agent_id": "the_classifier",
        "trigger_type": "new_regulation",
        "task_id": task_id,
    },
)
```

---

## 10. Frontend Architecture (Summary)

See [FRONTEND.md](FRONTEND.md) for full details. Key points:

- React + TypeScript + Vite + Tailwind
- Zustand for global state (lightweight, no Redux)
- Single WebSocket connection per user, multiplexed across views
- Components subscribe to specific blackboard fields via store selectors
- Right panel content driven by `selected_item` in store
- Routing via `react-router-dom` for tab switching (Dashboard / Chat / Graph / Controls)

---

## 11. Critical Architectural Invariants

These MUST hold true:

1. **No agent talks to another agent directly.** Communication is always via the blackboard.
2. **No agent modifies the blackboard outside its own output field.** The orchestrator owns mutations.
3. **No raw LLM responses leave an agent.** Every agent parses to Pydantic model, then returns.
4. **The Auditor is the only agent that can REJECT another agent's output.**
5. **The Watcher is the only non-LLM agent.** All others use Gemini.
6. **The Mapper is the only agent that queries portfolio tables.** Others use Mapper's output.
7. **The Advisor is the only agent that writes to the controls table.** Others read.
8. **No ClickHouse query in a route or agent.** Always via repository.
9. **Every WebSocket message has a `type` field.** Frontend routes on this.
10. **Every error is structured.** No string `Exception("something failed")`.

Read [AGENTS.md](AGENTS.md) next.
