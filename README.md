# RegRadar

**Agentic Governance & Compliance Intelligence for Fintechs**

> When a regulation changes, when a customer behaves a certain way, or when previously-invisible data becomes queryable — our agents go to work. They detect, classify, score the impact, update controls, and alert the right owner. No human had to ask. The system catches violations that have existed in the data for years but were never surfaced.

Built for the **Agentic Engineering Hack — NYC** (Datadog, May 2026). Multi-agent system anchored on Pydantic AI, Vertex AI Gemini 3.5 Flash, ClickHouse Cloud, Nimble, Firecrawl, and Datadog Lapdog (LLM Observability).

---

## Domain Scope

RegRadar monitors consumer credit card portfolios for compliance with two federal regimes:

- **TILA / Regulation Z** — penalty rate notice (1026.9(g)), promo rate expiry (1026.9(g)), billing dispute resolution (1026.13)
- **FCRA** — 7-year stale-data limit (Section 605), bureau accuracy + dispute flagging (Section 623(a))

Seven testable controls (REG-001…REG-007). One ClickHouse store.

---

## Architecture

```
                     ┌─────────────────────────────────────┐
                     │       Policy Crawler (hourly)       │
                     │  Pydantic AI · Gemini 3.5 Flash     │
                     │  Nimble → Firecrawl fallback        │
                     └──────────────────┬──────────────────┘
                                        │
                       writes regradar.policy_changes
                                        │
                                        ▼
┌──────────────────┐    ┌──────────────────────────────────────────┐
│ asset_changes    │───▶│   Impact Analysis Agent (every 60s)      │
│ (asset scanner)  │    │   polls cursor → resolves policy_registry│
└──────────────────┘    │   → evaluates 6 rule kinds → violations  │
                        └──────────────────┬───────────────────────┘
                                           │
                       writes regradar.violations + dispatches webhooks
                                           │
                                           ▼
                  ┌────────────────────────────────────────────┐
                  │  Dashboard (FastAPI + React + Lapdog)      │
                  │  Reads ClickHouse Cloud, polls every 10s   │
                  └────────────────────────────────────────────┘
```

| Agent | Activation | LLM calls | Job |
|---|---|---|---|
| **Policy Crawler** | Hourly (APScheduler) | 1 per regulation per cycle | Scrape with Nimble, verify thresholds via Gemini, write `policy_changes` |
| **Impact Analysis** | Every 60s (cursor poll) | 0–N depending on rules | Read `asset_changes` → resolve `policy_registry` → write `violations` + notify |
| **Asset Scanner** | Team WIP | 0 | Watches data assets and writes `asset_changes` events |

LLM tracing for both agents is captured locally by **Lapdog** at `127.0.0.1:8126`. Set `DD_API_KEY` to dual-ship traces to Datadog LLM Observability cloud.

---

## Tech Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.13, FastAPI, asyncio, APScheduler |
| Agent framework | Pydantic AI (Gemini via Vertex AI provider) |
| LLM | Vertex AI Gemini 3.5 Flash (workhorse), 3.1 Pro (reasoning), gemini-embedding-001 |
| Data store | ClickHouse Cloud 25.8+ (HNSW vector search GA) |
| Scraping | Nimble Web Search Agents (primary, `nimble_python` SDK) + Firecrawl (silent fallback) |
| LLM observability | Datadog Lapdog (local) + ddtrace 4.8+ |
| Frontend | React 18, Vite 5, TypeScript, Tailwind, Recharts, lucide-react |
| Logging | structlog, JSON to stderr, dd.trace_id correlation |

---

## Repository Structure

```
RegRadar-pk/
├── backend/
│   ├── main.py                            FastAPI app (CORS, routers)
│   ├── scheduler.py                       APScheduler entry: Crawler + Impact Analysis
│   ├── agents/
│   │   ├── base.py                        agent_run_context, agent IDs
│   │   ├── policy_crawler.py              Hourly crawler (Pydantic AI agent)
│   │   └── impact_analysis.py             Cursor-driven cycle (event consumer → policy resolver → evaluator → writer → notifier)
│   ├── api/
│   │   ├── dashboard.py                   /api/dashboard/summary, /api/regulations, /api/data-assets
│   │   ├── violations.py                  /api/violations, /api/policy-changes, /api/schema-events
│   │   ├── agents.py                      /api/agent-runs, /api/agent-state, /api/coverage
│   │   └── datadog_metrics.py             statsd gauges
│   ├── data/
│   │   ├── schema.sql                     Canonical ClickHouse Cloud schema
│   │   └── models.py                      Pydantic shapes (AssetChangeEvent, ImpactEvaluationResult, …)
│   ├── integrations/
│   │   ├── clickhouse_client.py           get_client (async), get_sync_client (per-call)
│   │   ├── nimble.py                      Web extract via nimble_python.Nimble
│   │   ├── firecrawl.py                   Silent fallback
│   │   └── vertex_ai.py                   Pydantic AI provider + embeddings
│   └── utils/
│       ├── env.py                         validate() + typed getters
│       └── logging.py                     structlog + Datadog LLM Obs annotation
│
├── frontend/                              Vite + React dashboard
│   └── src/
│       ├── App.tsx                        Layout + polling
│       ├── api/client.ts                  REST client
│       ├── types.ts                       Shared types (mirrors backend models)
│       └── components/                    Header, KpiCard, PolicyBreakdownChart,
│                                          CrawlerPanel, ViolationList, ViolationTimeline,
│                                          RegulationsTable, AgentActivityPanel, CoverageMatrix
│
├── docs/                                  Architecture, Agents, Data Model, API, Frontend,
│                                          Integrations, Deployment, Testing, Demo Script,
│                                          ClickHouse reference, ERD
│
├── scripts/
│   ├── run_with_lapdog.sh                 Generic Lapdog wrapper
│   ├── run_policy_crawler.sh              Crawler under Lapdog
│   ├── run_impact_agent.sh                Impact Analysis under Lapdog
│   ├── run_asset_scanner.sh               (Stub for the team's asset scanner)
│   ├── setup_cc_accounts.py               Cloud seed for cc_accounts
│   ├── test_crawler.py                    Crawl REG-005 only
│   └── smoke_test.py                      End-to-end smoke (env, ClickHouse, Nimble, Firecrawl, Vertex, Lapdog)
│
└── seed/                                  Static JSON seeds (controls, profile)
```

---

## Quickstart

Prereqs: Python 3.13, Node 20+, Homebrew (for Lapdog), a populated `.env`.

```bash
# 1. Install Lapdog (Datadog LLM Observability local agent)
brew install datadog/lapdog/lapdog

# 2. Python deps
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Copy and fill .env (see .env.example)
cp .env.example .env
#    Required: CLICKHOUSE_HOST/USER/PASSWORD, NIMBLE_API_KEY, GOOGLE_CLOUD_PROJECT,
#              GOOGLE_CLOUD_LOCATION, GOOGLE_GENAI_USE_VERTEXAI, OPENROUTER_API_KEY,
#              FIRECRAWL_API_KEY, DD_API_KEY (DD_API_KEY enables Lapdog forwarding)

# 4. Sanity check the stack end to end
python3 scripts/smoke_test.py

# 5. Run the API under Lapdog (capture LLM traces locally)
./scripts/run_with_lapdog.sh python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 6. Run the agents on a schedule (separate terminal)
./scripts/run_with_lapdog.sh python -m backend.scheduler

# 7. Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Open:

- **Dashboard** — http://127.0.0.1:5173
- **API docs** — http://127.0.0.1:8000/docs
- **Lapdog session viewer** — https://lapdog.datadoghq.com (reads from `127.0.0.1:8126`; no Datadog account required)

---

## Dashboard

The React UI reads from ClickHouse Cloud through the FastAPI layer and polls every 10 seconds.

- **KPI strip** — Assets monitored (`data_assets`), accounted for (`asset_regulation_map.in_scope`), out of compliance (`compliance_violations` OPEN + IN_REMEDIATION), suggested fixes (live `remediation_steps` joined to violations), fixes completed (RESOLVED).
- **Trigger feed** — Latest `policy_changes` rows from the Crawler, latest `schema_events` from the Asset Scanner.
- **Compliance by policy** — Stacked bar of compliant / at-risk / out-of-compliance assets per regulation.
- **Violations + remediation plan** — Live `compliance_violations` joined to `regulations`, `data_assets`, `critical_data_elements`, and `remediation_steps`.
- **Regulations registry** — Each control's `last_crawled_at` so you can see when the Policy Crawler last touched it.
- **Agent activity** — Reads `agent_state` (cursor, cycle count, status) and `agent_outputs` (recent runs). Renders a placeholder until the team applies the new schema rows to ClickHouse Cloud.
- **Asset × regulation coverage** — Joined view of `asset_regulation_map`, `data_assets`, `regulations` with open-violation counts per pair.

---

## Smoke Test

`scripts/smoke_test.py` validates everything the agents need. Expected output:

```
Env vars present                PASS
ClickHouse Cloud reachable      PASS  v25.12.x / N regulations
ClickHouse async client         PASS
Nimble extract                  PASS  N chars markdown
Firecrawl fallback              PASS  (or skipped without key)
Vertex AI provider              PASS  model=gemini-3.5-flash
Lapdog local agent              PASS  running
```

---

## ClickHouse Schema

Canonical schema lives in [`backend/data/schema.sql`](backend/data/schema.sql) and a column-by-column reference in [`docs/regradar-clickhouse.md`](docs/regradar-clickhouse.md).

The dashboard reads from these cloud tables:

| Table | Purpose |
|---|---|
| `regulations` | 7 controls (REG-001…REG-007) with thresholds + last_crawled_at |
| `data_assets`, `critical_data_elements` | Inventory + CDEs |
| `asset_regulation_map` | Which assets are in scope of which regulations |
| `compliance_violations`, `remediation_steps` | Live state of breaches and how to fix them |
| `compliance_scans` | Time series of scan results |
| `policy_changes` | Crawler-detected regulation changes |
| `schema_events` | Asset Scanner events (field added/populated/dropped) |
| `cc_accounts` | Synthetic credit-card portfolio |

The Impact Analysis Agent expects these additional tables (see `backend/data/schema.sql`); apply the schema to cloud before running the scheduler:

`asset_changes`, `agent_state`, `policy_registry`, `violations`, `notification_failures`, `agent_dead_letter`, `asset_tags`.

---

## LLM Observability

All Gemini calls — every Crawler verification, every Impact Analysis evaluation — are captured as Pydantic AI / `ddtrace` LLM spans. Lapdog wraps the process and pushes them to:

- `https://lapdog.datadoghq.com` for instant local replay (no account needed)
- Datadog LLM Observability cloud, when `DD_API_KEY` is set and `--forward` is on (the wrapper sets it automatically when the key is present in `.env`)

Wrappers in `scripts/`:

- `run_with_lapdog.sh <cmd>` — generic
- `run_policy_crawler.sh` — `python -m backend.agents.policy_crawler`
- `run_impact_agent.sh` — Impact Analysis loop
- `run_asset_scanner.sh` — Asset Scanner (probes for the team's module)

---

## Docs

| Doc | Purpose |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture, agent topology, trigger paths |
| [AGENTS.md](docs/AGENTS.md) | Agent contracts, prompts, I/O |
| [DATA_MODEL.md](docs/DATA_MODEL.md) | Column-by-column schema |
| [regradar-clickhouse.md](docs/regradar-clickhouse.md) | Schema reference |
| [API.md](docs/API.md) | FastAPI endpoints, WebSocket protocol |
| [FRONTEND.md](docs/FRONTEND.md) | UI components and contracts |
| [INTEGRATIONS.md](docs/INTEGRATIONS.md) | Nimble, Firecrawl, Vertex AI, Datadog |
| [SEED_DATA.md](docs/SEED_DATA.md) | Seed strategy + controls |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Day 0 + cloud runbooks |
| [TESTING.md](docs/TESTING.md) | Demo run-through, fallback procedures |
| [DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 3-minute pitch |
| [PRIZES.md](docs/PRIZES.md) | Sponsor-track strategy |

ERD: [`docs/data_model_erd.html`](docs/data_model_erd.html) (open in browser) and [`docs/data_model_erd.mmd`](docs/data_model_erd.mmd) (Mermaid source).

---

## License

MIT. See [LICENSE](LICENSE).
