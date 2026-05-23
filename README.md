# RegRadar

**Agentic Governance & Compliance Intelligence for Fintechs**

> When a regulation changes, when a customer behaves a certain way, or when previously-invisible data becomes queryable -- our agents go to work. They detect, classify, score the impact, update controls, publish a grounded compliance brief, and alert the right owner. No human had to ask. The system catches violations that have existed in the data for years but were never surfaced.

Built for the **Agentic Engineering Hack -- NYC** (Datadog, May 23 2026). Multi-agent system anchored on Pydantic AI, Vertex AI Gemini 3.5 Flash, ClickHouse, Nimble, Senso (cited.md), Datadog LLM Observability, and x402 payment rails.

---

## Domain Scope

RegRadar monitors consumer credit card portfolios for compliance with two federal regimes:

- **TILA / Regulation Z** -- penalty rate notice (1026.9(g)), promo rate expiry (1026.9(g)), billing dispute resolution (1026.13)
- **FCRA** -- 7-year stale-data limit (Section 605), bureau accuracy + dispute flagging (Section 623(a))

Six testable controls. Four policy embeddings. One ClickHouse store.

---

## Quick Links

| Doc | Purpose |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture, 4-agent topology, three trigger paths |
| [AGENTS.md](docs/AGENTS.md) | All 4 agents -- Pydantic AI patterns, prompts, I/O contracts |
| [DATA_MODEL.md](docs/DATA_MODEL.md) | ClickHouse schema -- credit card accounts, controls, policy_changes, schema_events |
| [API.md](docs/API.md) | FastAPI endpoints, WebSocket protocol, x402-gated routes |
| [FRONTEND.md](docs/FRONTEND.md) | React components -- live agent stream, schema-enrichment timeline, controls dashboard |
| [SEED_DATA.md](docs/SEED_DATA.md) | TILA/FCRA controls, 4 policy embeddings, credit card synthetic data |
| [INTEGRATIONS.md](docs/INTEGRATIONS.md) | Nimble, ClickHouse, Vertex AI, Datadog, Senso (cited.md), x402, Firecrawl |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Day 0 prep, .env, local + cloud runbooks |
| [TESTING.md](docs/TESTING.md) | Demo run-through, smoke tests, fallback procedures |
| [PRIZES.md](docs/PRIZES.md) | Explicit mapping: every sponsor track and how we hit it |
| [DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 3-minute pitch, second-by-second |

---

## Tech Stack (Locked)

| Layer | Tech | Why |
|---|---|---|
| Backend language | Python 3.11+ | Asyncio for agent fan-out |
| Web framework | FastAPI | Async-native, OpenAPI, WebSockets |
| Agent framework | **Pydantic AI** | Type-safe, FastAPI-native, no LangChain bloat |
| Data validation | Pydantic v2 | Type contracts everywhere |
| Logging | structlog | Structured JSON, Datadog-friendly |
| LLM (workhorse) | **Vertex AI Gemini 3.5 Flash** (launched May 19, 2026) | $1.50 in / $9 out per M tokens, native Google Search grounding |
| LLM (judge) | **Vertex AI Gemini 3.1 Pro** | Deeper reasoning for LLM-as-Judge |
| Embeddings | **gemini-embedding-001** | $0.15/M tokens, 3072 dims w/ Matryoshka truncation, top MTEB leaderboard |
| Grounding check | **Vertex AI Check Grounding API** | Built-in citation verification, used by Auditor |
| LLM fallback | OpenRouter | If Vertex AI 429s, silent failover |
| Data store | **ClickHouse 25.8+** | Vector search GA, HNSW, binary quantization -- portfolio + embeddings + audit in one |
| Observability | **Datadog AI Agent Monitoring** | Auto-instrumented LLM spans, AI Agent Console |
| Scraping | Nimble (primary) + Firecrawl (silent fallback) | Sponsor + resilience |
| Published content | **Senso Remediate API → cited.md** | Closes Senso prize loop |
| Monetization | **x402 (Coinbase) + USDC on Base** | Per-fetch micropayments for compliance briefs |
| Frontend | React 18 + TypeScript + Tailwind + Vite | Fast HMR, type safety |
| State | Zustand + TanStack Query | Server state + WS integration |

**Non-deterministic reasoning at exactly five points**, all at the boundary between unstructured regulatory text and structured schema:

1. **Policy text → compliance condition** (Policy Crawler)
2. **Policy diff → material change classification** (Policy Crawler on update)
3. **Schema field → policy relevance mapping** (Impact Analysis on schema_event)
4. **Ambiguous account scoping resolution** (Impact Analysis on edge cases)
5. **Grounding check on every generated claim** (Auditor via Check Grounding API)

Compliance decisions are never made by an embedding similarity score -- only by SQL conditions derived from extracted regulatory text.

```
                     ┌─────────────────────────────────────┐
                     │       Policy Crawler (hourly)       │
                     │  Gemini 3.5 Flash · grounded search │
                     └──────────────────┬──────────────────┘
                                        │
                       writes policy_changes (LLM call ends here)
                                        │
                                        ▼
┌─────────────┐    ┌──────────────────────────────────────────┐    ┌─────────────┐
│  schema     │───▶│    Impact Analysis Agent (event-driven)  │◀───│  behavior   │
│  events     │    │  Gemini 3.5 Flash · function calling     │    │  triggers   │
└─────────────┘    └──────────────────┬───────────────────────┘    └─────────────┘
                                      │
                              writes impact + control updates
                                      │
                                      ▼
                     ┌──────────────────────────────────────┐
                     │   Auditor (LLM-as-Judge, on demand)  │
                     │  Gemini 3.1 Pro + Check Grounding    │
                     └──────────────────┬───────────────────┘
                                        │
                            approved → publish to cited.md + alert
                                        │
                                        ▼
                  ┌────────────────────────────────────────────┐
                  │  Monitoring Agent (daily, zero-LLM)        │
                  │  Pure SQL · safety net for all 6 controls  │
                  └────────────────────────────────────────────┘
```

| Agent | Activation | LLM Calls | Job |
|---|---|---|---|
| **Policy Crawler** | Scheduled (hourly via Nimble) | 1 per new regulation version | Chunk + embed + extract structured compliance conditions |
| **Impact Analysis** | Event-driven (3 trigger types) | 1 per event | Map change/event to affected accounts, classify breach severity |
| **Auditor** | After Impact Analysis | 1 per impact report | LLM-as-Judge: ground every claim, block fabricated citations |
| **Monitoring** | Scheduled daily | **Zero** | Run all 6 control SQL queries, alert Datadog on breach |

---

## Three Trigger Paths

1. **Immediate behavior triggers** -- `dispute_filed = true` (TILA 30/90-day clocks + FCRA bureau flag obligation simultaneously), `penalty_rate_applied = true` (TILA 45-day notice clock starts)
2. **Schema change triggers** -- when `original_delinquency_date`, `bureau_reported_status`, or `promo_notice_sent_date` is populated/added, surfaces violations that always existed but were never queryable
3. **Daily scheduled scan** -- safety net across all controls, no LLM

---

## Where LLM Reasoning Is Applied

Non-deterministic reasoning at **exactly four points**, all at the boundary between unstructured regulatory text and structured schema:

1. **Policy text → compliance condition** (Policy Crawler)
2. **Policy diff → material change classification** (Policy Crawler on update)
3. **Schema field → policy relevance mapping** (Impact Analysis on schema_event)
4. **Ambiguous account scoping resolution** (Impact Analysis on edge cases)

Plus one verification layer:

5. **Grounding check on every generated claim** (Auditor via Check Grounding API)

Compliance decisions themselves are never made by an embedding similarity score -- only by SQL conditions derived from extracted regulatory text.

---

## Demo Arc (3 minutes flat)

```
0:00-0:20   Citi Global Markets — $1.975M, 360,000 accounts. The breach was a query, not a mystery.
0:20-0:40   The architecture in one breath: 4 agents, 3 triggers, 4 embeddings → 6 controls.
0:40-1:50   Live beat 1 (headline): Schema enrichment surfaces historical FCRA violations.
            We backfill original_delinquency_date — agent immediately surfaces 1,247 accounts
            illegally reported for over 7 years. No human triggered the scan.
1:50-2:30   Live beat 2: dispute_filed = true on one account. TILA 30-day clock starts
            AND FCRA bureau-flag obligation fires — simultaneously, in parallel.
2:30-2:50   Auditor approves the chain. Compliance brief auto-published to cited.md/regradar/...
            Datadog alert visible on the side panel.
2:50-3:00   x402-gated brief is now monetized. Other agents pay USDC to cite us. Close.
```

See [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) for exact wording.

---

## Prize Track Strategy

We hit **6 sponsor tools** (well above the 3-tool minimum for full Tool Use points):

| Sponsor | What we do | Prize track? |
|---|---|---|
| **Nimble** | Primary regulatory scraping for Policy Crawler | ✅ "Best use of Nimble's API" -- $1,500 |
| **ClickHouse** | Single analytical store for accounts + embeddings + audit | ✅ "Makes your life better / Impact" -- $1,000 |
| **Senso** | Publish grounded compliance briefs to cited.md after Auditor approves | ✅ "Senso content generation" -- 3K credits |
| **Datadog** | LLM Observability + AI Agent Console + control breach alerts | Venue + scored on Tool Use |
| **Vertex AI / DeepMind** | All LLM reasoning + Check Grounding | Scored on Tool Use |
| **x402 / Coinbase** | Monetize compliance briefs per fetch via USDC | "Monetize it" bonus |

See [docs/PRIZES.md](docs/PRIZES.md) for the explicit story per track.

---

## Critical Rules for AI Tools (Claude Code, Antigravity, etc.)

If you're building this:

1. **All agent I/O is Pydantic-typed.** Use Pydantic AI's `Agent` class with typed `input` and `output_type`. Never use raw dicts.
2. **All Gemini calls go through `backend/integrations/vertex_ai.py`.** Singleton + lazy init pattern. Centralization is what lets Datadog auto-instrumentation work.
3. **All ClickHouse queries go through `backend/data/repositories.py`.** No raw `client.query()` calls scattered across modules.
4. **The Auditor is non-negotiable.** Every Impact Analysis output passes through grounding check before publishing or alerting. No exceptions.
5. **Never invent regulatory citations, fine amounts, or case names.** The Auditor will reject the response. See system prompts in AGENTS.md.
6. **The Monitoring Agent makes ZERO LLM calls.** Pure SQL. If you find yourself adding an LLM call to it, you're doing it wrong.
7. **Schema enrichment is a first-class trigger.** Write `schema_events` rows when you backfill columns -- the Impact Analysis Agent listens.
8. **Async everywhere.** Every agent invocation, every integration call, every route handler.
9. **All logs structured.** Use `structlog` and tag with `agent`, `trigger_id`, `account_id`, `regulation_id`.
10. **Run with `ddtrace-run`.** Always. Even in dev. Auto-instruments Pydantic AI + google-genai for Datadog AI Agent Monitoring.
11. **Frontend talks to backend only via WebSocket for live data.** REST is for initial loads and explicit user actions.
12. **The `/compliance-brief/{reg_id}` endpoint is x402-gated.** Returns HTTP 402 until payment proof is provided.

---

## Quickstart

```bash
git clone <this-repo>
cd RegRadar

# 1. Python env
python -m venv venv
source venv/bin/activate                      # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Env
cp .env.example .env
# fill in API keys (see docs/DEPLOYMENT.md)

# 3. Local ClickHouse
docker compose up -d clickhouse

# 4. Seed data
python scripts/load_seed_data.py

# 5. Run backend (ddtrace-run auto-instruments for Datadog)
ddtrace-run uvicorn backend.main:app --reload --port 8000

# 6. Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

---

## Repository Structure

```
RegRadar/
├── README.md                              ← this file
├── .env.example                           ← every env var documented
├── requirements.txt, pyproject.toml
├── docker-compose.yml                     ← local ClickHouse
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── AGENTS.md
│   ├── DATA_MODEL.md
│   ├── API.md
│   ├── FRONTEND.md
│   ├── SEED_DATA.md
│   ├── INTEGRATIONS.md
│   ├── DEPLOYMENT.md
│   ├── TESTING.md
│   ├── PRIZES.md                          ← sponsor track strategy
│   └── DEMO_SCRIPT.md                     ← 3-min timing
│
├── backend/
│   ├── main.py
│   ├── agents/
│   │   ├── policy_crawler.py              ← Pydantic AI agent
│   │   ├── impact_analysis.py             ← Pydantic AI agent
│   │   ├── auditor.py                     ← LLM-as-Judge agent
│   │   └── monitoring.py                  ← Zero-LLM, SQL only
│   ├── integrations/
│   │   ├── vertex_ai.py                   ← Gemini + Check Grounding
│   │   ├── openrouter.py                  ← LLM fallback
│   │   ├── clickhouse_client.py
│   │   ├── nimble.py
│   │   ├── firecrawl.py
│   │   ├── datadog.py                     ← alerts + LLM Obs
│   │   ├── senso.py                       ← cited.md publishing
│   │   └── x402_pay.py                    ← Coinbase x402 middleware
│   ├── data/
│   │   ├── schema.sql                     ← ClickHouse DDL
│   │   ├── models.py                      ← Pydantic catalog
│   │   └── repositories.py
│   ├── api/
│   │   ├── routes.py
│   │   └── websocket.py
│   └── utils/
│       ├── env.py
│       └── logging.py
│
├── frontend/                              ← React + TS + Vite
├── seed/
│   ├── controls.json                      ← 6 TILA/FCRA controls
│   ├── policy_embeddings.json             ← 4 policy chunks pre-embedded
│   └── credit_cards/
│       ├── generate_accounts.py           ← synthetic data generator
│       └── README.md
└── scripts/
    ├── setup.sh
    ├── load_seed_data.py
    ├── demo_trigger.py                    ← fire schema_event or behavior trigger
    └── smoke_test.py
```

---

## Team

| Role | Responsibility |
|---|---|
| Repo owner | [@p-kowadkar](https://github.com/p-kowadkar) |
| Team size | 4 |

Hackathon: Agentic Engineering Hack NYC, May 23, 2026, Datadog NYC.

---

## License

MIT. See [LICENSE](LICENSE).

---

**Last updated:** May 23, 2026 -- pre-hackathon
