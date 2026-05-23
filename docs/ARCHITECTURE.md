# ARCHITECTURE.md

The complete system architecture for RegRadar. Read this before writing any code.

This document defines: the 4-agent topology, the 3 trigger paths, the single-store data model, the LLM-as-Judge contract, and the data flow end-to-end.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [The Four Agents](#2-the-four-agents)
3. [Three Trigger Paths](#3-three-trigger-paths)
4. [Where LLM Reasoning Is Applied](#4-where-llm-reasoning-is-applied)
5. [Data Flow End-to-End](#5-data-flow-end-to-end)
6. [The Blackboard Pattern (Simplified)](#6-the-blackboard-pattern-simplified)
7. [Pydantic AI Orchestration](#7-pydantic-ai-orchestration)
8. [The Auditor as LLM-as-Judge](#8-the-auditor-as-llm-as-judge)
9. [Publishing to cited.md (Senso)](#9-publishing-to-citedmd-senso)
10. [x402 Monetization Layer](#10-x402-monetization-layer)
11. [Observability Architecture](#11-observability-architecture)
12. [Design Decisions and Trade-offs](#12-design-decisions-and-trade-offs)

---

## 1. System Overview

```
                ┌──────────────────────────────────────────────────┐
                │              External Sources                     │
                │  SEC · CFTC · CFPB · FRB · FDIC · Federal Register │
                └────────────────────┬─────────────────────────────┘
                                     │
                                     │ Nimble Web Search Agents
                                     │ (scheduled hourly)
                                     ▼
              ┌──────────────────────────────────────────────────┐
              │                Policy Crawler                     │
              │  Gemini 3.5 Flash (with grounded Google Search)   │
              │  Chunks · embeds (gemini-embedding-001) · extracts│
              │  structured compliance conditions per regulation  │
              └──────────────────────┬───────────────────────────┘
                                     │
                                     │ writes policy_changes row
                                     │ (one LLM call per regulation)
                                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │                      ClickHouse 25.8+                    │
        │  ┌──────────────────┐  ┌──────────────────┐             │
        │  │  credit_card_    │  │  policy_         │             │
        │  │  accounts        │  │  embeddings      │             │
        │  │  (synthetic)     │  │  (4 chunks)      │             │
        │  └──────────────────┘  └──────────────────┘             │
        │  ┌──────────────────┐  ┌──────────────────┐             │
        │  │  controls (6)    │  │  policy_changes  │             │
        │  └──────────────────┘  └──────────────────┘             │
        │  ┌──────────────────┐  ┌──────────────────┐             │
        │  │  schema_events   │  │  behavior_events │             │
        │  └──────────────────┘  └──────────────────┘             │
        │  ┌──────────────────┐  ┌──────────────────┐             │
        │  │  audit_trail     │  │  compliance_     │             │
        │  │                  │  │  scans           │             │
        │  └──────────────────┘  └──────────────────┘             │
        └──────────────────────────┬──────────────────────────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            │                      │                      │
            ▼                      ▼                      ▼
   ┌────────────────┐    ┌──────────────────┐    ┌────────────────┐
   │ Impact         │    │  Monitoring      │    │  HTTP API +    │
   │ Analysis Agent │    │  Agent (daily)   │    │  WebSocket     │
   │ (event-driven) │    │  Zero LLM, SQL   │    │  (FastAPI)     │
   │ Gemini 3.5     │    │  only            │    └────────┬───────┘
   │ Flash + tools  │    └──────────────────┘             │
   └────────┬───────┘                                     │
            │                                              │
            │ impact + control updates                     │
            ▼                                              │
   ┌────────────────────────────────────┐                  │
   │       Auditor (LLM-as-Judge)        │                  │
   │  Gemini 3.1 Pro + Check Grounding  │                  │
   │  Verifies every claim is grounded   │                  │
   │  Blocks hallucinated citations      │                  │
   └────────┬───────────────────────────┘                  │
            │                                               │
            │ approved                                       │
            ▼                                               │
   ┌────────────────┐    ┌──────────────────┐               │
   │  Senso →       │    │  Datadog event   │               │
   │  cited.md      │    │  + AI Agent Obs  │               │
   │  (publish)     │    └──────────────────┘               │
   └────────┬───────┘                                       │
            │                                               │
            │ public URL                                    │
            ▼                                               ▼
   ┌──────────────────────────────────────────────────────────────┐
   │   /api/compliance-brief/{reg_id}   ← x402-gated (USDC/Base) │
   │   Other agents pay $0.001 per fetch to read RegRadar's brief │
   └──────────────────────────────────────────────────────────────┘
```

---

## 2. The Four Agents

### 2.1 Policy Crawler (`backend/agents/policy_crawler.py`)

**Activation:** scheduled, every 60 minutes via `asyncio.create_task` started in FastAPI `lifespan`.

**Tools:**
- Nimble search & scrape (regulatory sources)
- Google Search grounding (Gemini 3.5 Flash native feature)
- ClickHouse repository write methods

**LLM calls per execution:** 1 per new or updated regulation version detected. Most polls produce zero LLM calls because nothing changed.

**Job:**
1. Hit ~10 regulatory source URLs via Nimble (SEC press, CFPB rules, FRB regulations, etc.)
2. Compute content hash, compare to prior version stored in `reg_versions`
3. If new or changed: chunk + embed via `gemini-embedding-001`, then call Gemini 3.5 Flash with the regulation text and a structured-output schema to extract `ComplianceCondition` records
4. Write `reg_versions` row + `policy_changes` row (the latter is what triggers Impact Analysis)
5. Done. No further LLM activity until next change.

**Output type:** `PolicyExtractionResult` (Pydantic):
```python
class ComplianceCondition(BaseModel):
    regulation_id: str
    regulation_section: str               # "12 CFR 1026.9(g)"
    condition_kind: Literal[
        "advance_notice", "time_window", "field_match",
        "stale_data_limit", "dispute_flag_required"
    ]
    field_required: str                   # e.g. "promo_notice_sent_date"
    operator: Literal["lt", "lte", "eq", "gte", "gt", "exists", "matches"]
    threshold_value: float | str
    threshold_unit: str                   # "days", "boolean", "string_match"
    account_scope: dict[str, Any]         # which accounts this applies to
    citation_text: str                    # exact regulatory text quote
```

### 2.2 Impact Analysis Agent (`backend/agents/impact_analysis.py`)

**Activation:** event-driven. Fires when a row appears in:
- `policy_changes` (a regulation moved)
- `schema_events` (a column got populated or added)
- `behavior_events` (an account behavior triggered an immediate clock)

**Tools:**
- ClickHouse repositories (read accounts, read policy conditions, write impact reports)
- Gemini 3.5 Flash with function calling

**LLM calls per execution:** 1 per event. The LLM reasons about which conditions apply to the event and writes an `ImpactReport`. All downstream account scanning is deterministic SQL.

**Job:**
1. Read the triggering event
2. LLM call (one): given the event + applicable ComplianceConditions, decide what to query and how to classify breaches. Returns a function-call payload describing the SQL parameters to execute.
3. Execute deterministic SQL against `credit_card_accounts`. Count BREACH / AT_RISK / PASSING.
4. Write `impact_reports` row.
5. Hand off to Auditor.

**Output type:** `ImpactReport` (Pydantic) -- detailed in AGENTS.md.

### 2.3 Auditor (`backend/agents/auditor.py`) -- LLM-as-Judge

**Activation:** triggered immediately after Impact Analysis writes a report.

**Tools:**
- Vertex AI Check Grounding API (citation verification)
- Gemini 3.1 Pro (deeper reasoning for ambiguous claims)
- ClickHouse to look up source text from `reg_versions`

**LLM calls per execution:** 1 Check Grounding call + up to 1 Gemini 3.1 Pro call (only if Check Grounding flags ambiguity).

**Job:**
1. Decompose the ImpactReport into individual claims (citations, numbers, classifications)
2. For each claim, run Check Grounding against the cited `reg_versions.content_markdown`
3. If overall_confidence >= 0.85 → approve. If 0.65-0.85 → approve_with_warnings. If < 0.65 → reject and write rejection reasons.
4. On approve: hand off to Senso publishing + Datadog alerting.
5. On reject: write to `audit_trail` with the failed claims; do NOT publish or alert. Impact Analysis can retry with stricter prompt.

**Output type:** `AuditorVerdict` (see AGENTS.md).

**Why LLM-as-Judge here:** the regulatory domain is unforgiving. A fabricated case citation or wrong dollar amount during the demo (or in production) ends the company. The Auditor exists so that the system fails closed when uncertain.

### 2.4 Monitoring Agent (`backend/agents/monitoring.py`) -- Zero LLM

**Activation:** scheduled, daily at 00:00 UTC.

**Tools:** ClickHouse only.

**LLM calls per execution:** ZERO. By design.

**Job:**
1. For each of the 6 controls, execute the SQL query stored in `controls.check_sql`
2. Count breaches per control
3. Write `compliance_scans` time-series row
4. Fire Datadog event if breach count > 0
5. Done

**Why zero LLM:** controls are defined by structured `ComplianceCondition` records. Once those exist, evaluation is pure SQL. LLM at this stage adds latency, cost, and hallucination risk for no value. The 4th agent is the safety net; it doesn't need to be smart.

---

## 3. Three Trigger Paths

### Path 1: Immediate behavior triggers

| Behavior event | What fires | Controls touched |
|---|---|---|
| `dispute_filed = true` | TILA 30/90-day clocks start + FCRA bureau-flag obligation | CTRL-TILA-DISPUTE, CTRL-FCRA-DISPUTE-FLAG |
| `penalty_rate_applied = true` | TILA 45-day notice clock starts | CTRL-TILA-PENALTY-RATE-NOTICE |
| `promo_rate_assigned = true` | TILA 45-day notice obligation for future expiry | CTRL-TILA-PROMO-RATE-NOTICE |

**Mechanism:** `INSERT INTO behavior_events ...` from application code or demo trigger. Impact Analysis Agent has a worker task that polls `behavior_events WHERE processed = false` every 500ms during the demo (1 second in normal ops). When found, processes immediately.

### Path 2: Schema change triggers

| Schema change | What surfaces |
|---|---|
| `original_delinquency_date` column populated (backfill) | FCRA 7-year violations -- accounts illegally reported for years |
| `bureau_reported_status` column added | FCRA accuracy mismatches become visible |
| `promo_notice_sent_date` column added | TILA promo notice violations queryable |

**Mechanism:** when a migration runs, it writes a row to `schema_events`. Impact Analysis Agent polls this table the same way as `behavior_events`. Schema changes are how we get the "no one was looking at this for years" demo moment.

### Path 3: Daily scheduled scan

Safety net. The Monitoring Agent runs all 6 control SQL queries daily regardless of events. Catches:
- Time-based controls where the deadline passes silently (promo_end_date crosses, delinquency ages into 7-year window)
- Controls where the event-driven path missed something
- Drift between policy conditions and actual data

---

## 4. Where LLM Reasoning Is Applied

The system uses non-deterministic reasoning at **exactly five points**, all at the boundary between unstructured regulatory text and structured schema:

| Point | Agent | LLM | Purpose |
|---|---|---|---|
| Policy text → ComplianceCondition | Policy Crawler | Gemini 3.5 Flash | Extract field, operator, threshold from regulation |
| Policy diff → material change | Policy Crawler (on update) | Gemini 3.5 Flash | Decide if change is material (new threshold/scope) or clarification |
| Schema field → policy relevance | Impact Analysis | Gemini 3.5 Flash | Map new column to which policies it enables/affects |
| Ambiguous account scoping | Impact Analysis | Gemini 3.5 Flash | Edge cases (pre-effective-date accounts, partial docs, bankruptcy) |
| Grounding verification | Auditor | Check Grounding + Gemini 3.1 Pro | Verify every claim and citation in ImpactReport |

**Everything else is deterministic SQL.** Compliance decisions are never made by an embedding similarity score -- only by SQL conditions derived from extracted regulatory text.

---

## 5. Data Flow End-to-End

### Scenario A: Schema enrichment demo (headline)

```
1. Migration script runs: ALTER TABLE credit_card_accounts ADD COLUMN
   original_delinquency_date Date; UPDATE ... SET original_delinquency_date = ...

2. Migration writes: INSERT INTO schema_events
   (event_type='column_populated', table='credit_card_accounts',
    column='original_delinquency_date', populated_at=now())

3. Impact Analysis Agent's poll worker picks up the schema_event within 500ms.

4. Agent LLM call (Gemini 3.5 Flash): 'A new column original_delinquency_date
   was populated on credit_card_accounts. Given the active ComplianceConditions,
   which apply?' → returns function-call to query FCRA Section 605 condition.

5. Agent executes deterministic SQL:
     SELECT count(), sum(balance_usd)
     FROM credit_card_accounts
     WHERE original_delinquency_date IS NOT NULL
       AND original_delinquency_date < today() - INTERVAL 7 YEAR
       AND bureau_reported = true

6. Result: 1,247 accounts, $X total balance.

7. Agent writes impact_reports row + control_updates row (CTRL-FCRA-7YR → FAILING).

8. Auditor: Check Grounding on the citation ('FCRA Section 605') and the
   numerical claim. Approves.

9. Senso integration publishes a compliance brief to cited.md/regradar/fcra-605-stale-data-discovery
   with full citation, account count, suggested remediation steps.

10. Datadog event fires: 'CTRL-FCRA-7YR FAILING -- 1247 accounts, owner: Bureau Reporting Team'

11. Frontend streams the entire chain over WebSocket. User sees agents lighting up,
    the control flipping red, and the cited.md URL appearing.
```

### Scenario B: dispute_filed cross-trigger (secondary)

```
1. User clicks 'File Dispute' on account A-12345.

2. App writes:
     INSERT INTO behavior_events
     (event_type='dispute_filed', account_id='A-12345', occurred_at=now())

3. Impact Analysis poll worker picks up within 500ms.

4. ONE LLM call (Gemini 3.5 Flash): 'A dispute was filed on account A-12345.
   Given active ComplianceConditions, which controls fire?'
   → returns: ['CTRL-TILA-DISPUTE', 'CTRL-FCRA-DISPUTE-FLAG']

5. Agent runs TWO deterministic SQL checks in parallel:
   a) TILA: is acknowledgment_sent within 30 days? (not yet -- starts a clock)
   b) FCRA: is bureau_dispute_flag = true? (not yet -- starts an obligation)

6. Agent writes one impact_report with two control_updates (both move to AT_RISK).

7. Auditor approves. Senso publishes brief. Datadog alerts both teams.

8. Frontend shows TWO controls lighting up amber from a single event.
```

### Scenario C: New regulation arrives (background, less dramatic)

```
1. Nimble scrape (hourly) picks up a CFPB update at consumerfinance.gov/rules.

2. Policy Crawler compares content hash to last seen → CHANGED.

3. ONE LLM call (Gemini 3.5 Flash) with structured output schema → extracts
   ComplianceCondition records, writes them to ClickHouse.

4. Crawler writes policy_changes row.

5. Impact Analysis picks up the policy_changes row, runs deterministic
   scans against all accounts.

6. Same Auditor + Senso + Datadog flow.
```

---

## 6. The Blackboard Pattern (Simplified)

We kept a lightweight blackboard for trigger correlation but radically simplified it from the v2 design.

**Why we still have one:**
- Multi-agent traces in Datadog need a shared `trigger_id` to group spans
- WebSocket clients need to subscribe to all events for a single trigger
- The Auditor needs read access to whatever Impact Analysis wrote

**What we removed:**
- No more 6-agent self-selection
- No more relevance scoring at evaluation time
- No more cross-agent dependency resolution

**The remaining blackboard is just a per-trigger context object:**

```python
# backend/orchestrator/context.py
class TriggerContext(BaseModel):
    trigger_id: str
    trigger_type: Literal["policy_change", "schema_event", "behavior_event"]
    payload: dict
    started_at: datetime
    impact_report: ImpactReport | None = None
    auditor_verdict: AuditorVerdict | None = None
    published_brief_url: str | None = None
    datadog_event_id: str | None = None
```

Stored in-memory in a dict keyed by `trigger_id`. WebSocket clients receive updates as fields populate.

---

## 7. Pydantic AI Orchestration

We use **Pydantic AI** as the agent framework. It's a typed, FastAPI-native alternative to LangChain that gives us:

- Strict input/output Pydantic models for every agent
- Built-in tool calling via decorated functions
- Native async
- Auto-instrumentation hooks for Datadog
- No LangChain abstraction surface area

### Agent skeleton

```python
# backend/agents/policy_crawler.py
from pydantic_ai import Agent, RunContext
from backend.data.models import PolicyExtractionInput, PolicyExtractionResult
from backend.integrations.vertex_ai import vertex_model

policy_crawler = Agent(
    model=vertex_model("gemini-3.5-flash"),
    input_type=PolicyExtractionInput,
    output_type=PolicyExtractionResult,
    system_prompt=POLICY_CRAWLER_SYSTEM_PROMPT,
)

@policy_crawler.tool
async def search_regulation_text(
    ctx: RunContext,
    regulator: str,
    topic: str,
) -> list[str]:
    """Search regulatory sources via Nimble for the given regulator+topic."""
    ...

@policy_crawler.tool
async def get_prior_version(
    ctx: RunContext,
    regulation_id: str,
) -> str | None:
    """Return the markdown of the last-seen version of this regulation."""
    ...
```

Pydantic AI handles the system prompt, tool dispatch, response parsing, and retries.

### Why Pydantic AI over LangGraph

LangGraph is the right choice if we needed:
- Long-running stateful workflows with checkpointing
- Complex conditional routing across many agent types
- Human-in-the-loop pauses

We don't. Our workflow is linear: trigger → Impact Analysis → Auditor → publish. Each agent runs once. Pydantic AI's typed contracts give us safety without LangGraph's graph machinery. Less code, less to debug at 3 AM.

### Why not the OpenAI Agents SDK or Claude Agent SDK

We're using Gemini, not GPT or Claude. Pydantic AI is model-agnostic and works cleanly with `google-genai`.

---

## 8. The Auditor as LLM-as-Judge

The Auditor runs after Impact Analysis. Its job is to **fail closed when uncertain**.

### Inputs

- The ImpactReport JSON
- The source `reg_versions.content_markdown` for every regulation cited

### Processing

1. **Claim decomposition.** Extract every factual claim from the ImpactReport: citations (e.g., "FCRA Section 605"), numbers ("1,247 accounts"), classifications ("BREACH"), and prescriptive recommendations.
2. **Per-claim grounding.** For each claim, call `vertex_ai.check_grounding(claim=..., sources=[source_text])`. The Check Grounding API returns a confidence score and supporting text excerpts.
3. **Aggregate verdict.**
   - If every claim has `confidence >= 0.85` → **approved**
   - If any claim has `confidence` in [0.65, 0.85) → **approved_with_warnings** (publish but flag in audit_trail)
   - If any claim has `confidence < 0.65` → **rejected** (do NOT publish or alert; write rejection reasons)
4. **Optional reasoning escalation.** For approved_with_warnings, optionally invoke Gemini 3.1 Pro with the warning claim and ask it to refine or remove. This is the only place 3.1 Pro is used.

### Why grounding API not pure LLM-as-Judge

Pure LLM-as-Judge (one LLM judging another) is biased and hallucination-prone in itself. The Vertex Check Grounding API is purpose-built for this: it scores whether a claim is supported by provided sources, with explicit citation extraction. We use it as the spine, with 3.1 Pro only as a tiebreaker.

### What the Auditor blocks

- "Citi was fined $2 million for this" -- if no source supports $2M specifically
- "847 accounts affected" -- if the actual SQL returned 213
- "Section 1026.9(g) requires a 60-day notice" -- it requires 45
- "Recommended action: notify customers within 30 days" -- if no regulation cited prescribes 30

These are the kinds of errors that have killed compliance demos in the past. The Auditor exists so they never reach the audience.

---

## 9. Publishing to cited.md (Senso)

When the Auditor approves an ImpactReport, the Senso integration generates a structured agent-native compliance brief and publishes it to `cited.md/regradar/<slug>`.

### Why this matters

1. **Closes the Senso prize loop.** Senso's prize requires using their content generation APIs to publish grounded, citeable content to a public destination. Ingestion alone doesn't qualify.
2. **Establishes RegRadar as a cite-able source on the agentic web.** Other compliance agents can discover and cite our briefs.
3. **Provides the audit trail externally.** The brief at `cited.md/regradar/<slug>` is timestamped, citation-grounded, and publicly verifiable.

### Brief schema

```python
class CompianceBrief(BaseModel):
    title: str                          # "FCRA Section 605: 1,247 accounts surfaced as stale-data violations"
    handle: str                         # "regradar"
    slug: str                           # "fcra-605-stale-data-2026-05-23"
    body: str                           # markdown with structured sections
    tags: list[str]                     # ["fcra", "section-605", "credit-reporting", "consumer-protection"]
    provenance: ProvenanceMetadata      # who, when, source citations
    related_regulation_id: str
    affected_account_count: int
    suggested_remediation: list[str]
```

### Publishing flow

```python
# backend/integrations/senso.py
async def publish_brief(brief: ComplianceBrief) -> PublishedBrief:
    payload = brief.model_dump()
    response = await senso_client.post("/remediate", json=payload)
    return PublishedBrief(
        url=f"https://cited.md/{brief.handle}/{brief.slug}",
        senso_id=response["id"],
        published_at=response["published_at"],
    )
```

---

## 10. x402 Monetization Layer

The compliance brief URL is monetized via x402. Other agents pay USDC micropayments to fetch the full structured brief.

### Endpoint

`GET /api/compliance-brief/{reg_id}` -- gated by x402 middleware.

### Flow

1. An external agent requests the URL.
2. Server returns `HTTP 402 Payment Required` with payment requirements in headers.
3. Agent signs a USDC transfer authorization (EIP-3009) and retries with `X-PAYMENT` header.
4. x402 facilitator (Coinbase) verifies onchain, returns settlement proof.
5. Server returns the structured brief (JSON).

### Implementation

```python
# backend/integrations/x402_pay.py
from x402.fastapi import x402_protected

@app.get("/api/compliance-brief/{reg_id}")
@x402_protected(price_usdc="0.001", network="base", facilitator="coinbase")
async def get_compliance_brief(reg_id: str) -> ComplianceBrief:
    ...
```

### Why this matters for the hackathon

- Devpost explicitly calls out: "Monetize it with agent payment rails (x402, MPP, CDP, agentic.market)"
- It's a 10-second demo beat that lands the "novel monetization" bonus
- Shows the system isn't just defensive (catching violations) but offensive (selling compliance intelligence)

---

## 11. Observability Architecture

### Datadog LLM Observability

We use `ddtrace-run` to auto-instrument the Python process. Every LLM call generates an LLM Obs span automatically:

- `google-genai` SDK → auto-instrumented (Gemini calls become LLM spans)
- Pydantic AI agent calls → instrumented via Pydantic AI's tracing hooks
- `clickhouse-connect` → DB spans
- FastAPI routes → HTTP spans
- `httpx`/`aiohttp` → outbound spans (Nimble, Senso, Firecrawl)

In the Datadog AI Agent Console, we see:
- Each agent as a node
- Inter-agent calls as edges
- Latency per node, token cost per node
- Click into any span to see input/output/grounding scores

### Custom tagging per trigger

```python
# backend/utils/logging.py
def annotate_llm_span(*, agent_id: str, trigger_id: str, **extra):
    from ddtrace.llmobs import LLMObs
    LLMObs.annotate(tags={"agent": agent_id, "trigger_id": trigger_id, **extra})
```

Called at the top of every agent's `run()` method.

### Control breach alerts (separate from LLM Obs)

When the Auditor approves an Impact Report with a control flipping to FAILING, `backend/integrations/datadog.py` posts a Datadog Event with:
- Title: `[RegRadar] {CONTROL_ID} FAILING: {regulation}`
- Body: affected_account_count, total_balance, owner_team, link to cited.md brief
- Tags: `control:{id}`, `owner:{team}`, `severity:critical`

These appear as a stream on the Datadog events page.

---

## 12. Design Decisions and Trade-offs

### Decision: Why 4 agents and not 3 (per Suhita's plan) or 6 (per v2)?

**3 agents missed the LLM-as-Judge layer.** Without grounding verification, the system can fabricate citations on stage. Adding the Auditor was non-negotiable.

**6 agents was overengineered.** The blackboard self-selection added implementation complexity for marginal architectural elegance. Three different activation modes (scheduled, event-driven, scheduled-zero-LLM) plus an LLM-as-Judge is cleaner.

### Decision: Why Pydantic AI not LangGraph?

LangGraph excels at graph workflows with conditional routing and checkpointing. Our workflow is linear. Pydantic AI gives us typed contracts and tool calling with a fraction of the cognitive overhead.

### Decision: Why zero-LLM Monitoring Agent?

The 6 controls are SQL-evaluable once their `ComplianceCondition` records exist. Daily monitoring adding LLM calls would cost ~6 × ~$0.01 = ~$0.06/day per tenant for zero added value (potentially adding hallucination risk). The Monitoring Agent is the system's daily heartbeat -- it must be fast, cheap, and 100% deterministic.

### Decision: Why publish to cited.md before Datadog alert?

If publishing fails, we don't want a Datadog alert pointing to a brief URL that doesn't exist. Order: Senso publish → Datadog alert with the now-live URL. If Senso fails, alert without the URL and log the publish failure separately.

### Decision: Why ClickHouse not Postgres + pgvector?

- ClickHouse 25.8 has GA vector search with binary quantization
- ClickHouse handles 50K+ row scans for daily monitoring in milliseconds
- One store for vectors + portfolios + audit + time-series = lower ops complexity
- We're a sponsor's flagship use case ("Best use of ClickHouse" prize)

### Decision: Why HNSW and not exact vector search?

We only have 4 policy embeddings. Exact search is fine at this scale. HNSW is the right call when we scale to thousands of regulations. We pre-create the index so the demo shows real production patterns.

### Decision: Why `original_delinquency_date` for the headline demo?

- FCRA Section 605 is one sentence with one number -- easiest to ground
- The schema enrichment story is genuinely novel ("agent found violations that existed for 4 years")
- High emotional impact ("you've been illegally on someone's credit report")
- Pure date arithmetic in SQL -- zero risk of demo math going wrong

### Decision: What if a sponsor integration breaks on stage?

Each integration has explicit fallback behavior documented in INTEGRATIONS.md. The non-negotiable ones (ClickHouse, Vertex AI) have OpenRouter fallback. Senso publishing failure produces a warning but the demo continues. x402 monetization is the last beat -- if it breaks, it gets a 10-second skip with no damage.

---

## AI Tool Hints

If you're an AI tool building this:

1. **Implement integrations first** (ClickHouse → Vertex AI → Nimble → Senso → Datadog → Firecrawl → OpenRouter → x402). Each builds on the previous.
2. **Write `backend/data/models.py` second.** All agent I/O references it.
3. **Implement agents in dependency order:** Policy Crawler → Impact Analysis → Auditor → Monitoring.
4. **Test each agent in isolation first.** Mock the others. Wire end-to-end last.
5. **Don't skip the Auditor.** Skipping it means demo hallucinations.
6. **Don't add LLM calls to Monitoring.** It's deliberately zero-LLM. Trust the design.
7. **Pre-warm integrations at startup.** All singletons initialized in FastAPI `lifespan`.
