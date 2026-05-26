# RegRadar

**Agentic Governance & Compliance Intelligence for Fintechs**

> When a regulation changes, when a customer behaves a certain way, or when previously-invisible data becomes queryable — our agents go to work. They detect, classify, score the impact, update controls, and alert the right owner. No human had to ask. The system catches violations that have existed in the data for years but were never surfaced.

Originally built for the **Agentic Engineering Hack — NYC** (Datadog, May 2026); now maintained for public release. Multi-agent system anchored on Pydantic AI, OpenRouter (Gemini 2.5 family by default), ClickHouse Cloud, Firecrawl (primary scraper) + Nimble (optional). Optional LLM observability via Pydantic Logfire or Datadog Lapdog — pick whichever you want, or skip both.

---

## What you get

A live dashboard at `http://127.0.0.1:5173` that reads ClickHouse Cloud directly. Every panel is sourced from real cloud rows. The Policy Crawler agent is fully wired: it scrapes regulations through Nimble, calls a Gemini model through Pydantic AI (via OpenRouter to dodge Google's free-tier daily cap), writes `policy_changes` rows, and updates `regulations.last_crawled_at`. Lapdog captures every LLM span locally so you can replay the prompt and response.

---

## Setup (literal step-by-step)

This is the **exact** sequence on a fresh Mac. It assumes Python 3.13 and Node 20+.

### 0. Prereqs

```bash
# Homebrew is needed for Lapdog
which brew || /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Lapdog (Datadog LLM Observability local agent)
brew install datadog/lapdog/lapdog
```

### 1. Clone and create the venv

```bash
cd ~/<wherever>
git clone https://github.com/p-kowadkar/RegRadar.git RegRadar-pk
cd RegRadar-pk

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Required keys

You need **four** keys minimum. Copy the template and edit:

```bash
cp .env.example .env
```

Fill in `.env` with these values. Every other variable can stay at its default.

| Key | Where to get it | Required for |
|---|---|---|
| `CLICKHOUSE_HOST` | ClickHouse Cloud → service settings | Dashboard reads, agent writes |
| `CLICKHOUSE_PORT` | `8443` for Cloud | same |
| `CLICKHOUSE_USER` | usually `default` | same |
| `CLICKHOUSE_PASSWORD` | ClickHouse Cloud → users | same |
| `CLICKHOUSE_SECURE` | `true` for Cloud | same |
| `CLICKHOUSE_DATABASE` | `regradar` | same |
| `NIMBLE_API_KEY` | https://online.nimbleway.com/account-settings/api-keys | Policy Crawler scraping |
| `OPENROUTER_API_KEY` | https://openrouter.ai/keys | Policy Crawler LLM calls |
| `FIRECRAWL_API_KEY` | https://www.firecrawl.dev (optional, fallback) | Crawler if Nimble fails |
| `GOOGLE_CLOUD_PROJECT` | Google Cloud project id | Only if you skip OpenRouter |
| `GOOGLE_CLOUD_LOCATION` | e.g. `us-central1` | same |
| `GOOGLE_GENAI_USE_VERTEXAI` | `True` | same |
| `DD_API_KEY` | Datadog account (optional) | If set, Lapdog dual-ships to your Datadog org |

**Why OpenRouter?** Gemini's free-tier API has a 20-requests-per-day cap on `gemini-2.5-flash`, which the Policy Crawler will exhaust in two runs. OpenRouter gives you a single key that fronts the same model with usage-based billing. The code automatically picks OpenRouter when `OPENROUTER_API_KEY` is set; otherwise it falls back to the Gemini API key, then to Vertex AI ADC.

### 3. Smoke test (verify all the wiring)

```bash
python3 scripts/smoke_test.py
```

Expected output: 7 PASS rows.

```
RegRadar Smoke Test
Env vars present                PASS
ClickHouse Cloud reachable      PASS  v25.x / 7 regulations
ClickHouse async client         PASS
Nimble extract                  PASS  N chars markdown
Firecrawl fallback              PASS  (or skipped, no key)
Vertex AI provider              PASS  model=gemini-2.5-flash
Lapdog local agent              PASS  running
```

If any row fails, the message tells you which env var or service is the problem. Common ones:

- **ClickHouse Cloud reachable: FAIL** → wrong host/password, or the Cloud service is paused. Check at https://clickhouse.cloud.
- **Nimble extract: FAIL** → key is invalid or the org is suspended.
- **Vertex AI provider: FAIL** → run `gcloud auth application-default login`, **or** just rely on `OPENROUTER_API_KEY` (the code's resolver picks it first).
- **Lapdog local agent: FAIL** → run `lapdog start`.

### 4. Run the stack

You need three terminals (or three tmux panes).

**Terminal 1 — backend API under Lapdog:**
```bash
./scripts/run_with_lapdog.sh python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — frontend dev server:**
```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

**Terminal 3 — Policy Crawler (one-shot or scheduled):**

```bash
# One-shot: crawl all 7 regulations once
./scripts/run_policy_crawler.sh

# Or: run the full scheduler (Crawler hourly, Impact Analysis every 60s)
./scripts/run_with_lapdog.sh python -m backend.scheduler
```

### 5. Open the dashboard

| What | URL |
|---|---|
| **Dashboard** (poll-driven, every 10s) | http://127.0.0.1:5173 |
| **API docs** (FastAPI Swagger) | http://127.0.0.1:8000/docs |
| **Lapdog session viewer** (local, no Datadog account needed) | https://lapdog.datadoghq.com |

Each KPI on the dashboard has a small monospace caption underneath that tells you the exact ClickHouse column or query the number comes from.

---

## Demo path (Crawler → ClickHouse → Dashboard → Lapdog)

While the dashboard is open, run the Crawler. You'll see:

1. **Terminal 3** logs the Crawler steps:
   ```
   [info] agent.run.start              agent=policy_crawler trigger_id=REG-005
   [info] nimble.scrape_success        url=https://www.law.cornell.edu/...
   [info] crawler.regulation_done      regulation_id=REG-005 material=false ...
   [info] agent.run.complete           agent=policy_crawler trigger_id=REG-005
   ```
2. **Dashboard** within 10s shows fresh `last_crawled_at` timestamps in the Regulations registry, plus new rows in the Policy Changes feed.
3. **Lapdog** at https://lapdog.datadoghq.com shows the LLM session per regulation: prompt, response, token counts.

That's the full real loop, no fake data.

---

## Architecture

```
                     ┌─────────────────────────────────────┐
                     │       Policy Crawler (hourly)       │
                     │  Pydantic AI · Gemini 2.5 Flash     │
                     │  OpenRouter or Vertex/Gemini path   │
                     │  Nimble → Firecrawl fallback        │
                     └──────────────────┬──────────────────┘
                                        │
                       writes regradar.policy_changes
                       updates regradar.regulations.last_crawled_at
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

| Agent | Status | LLM provider |
|---|---|---|
| **Policy Crawler** | Live, end to end | OpenRouter (auto-selected) → falls back to Gemini API key → Vertex ADC |
| **Impact Analysis** | Code shipped, awaits cloud schema for `agent_state`/`asset_changes`/`violations` | Same |
| **Asset Scanner** | Team WIP | Same |

---

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python 3.13, FastAPI, asyncio, APScheduler |
| Agent framework | Pydantic AI |
| LLM | OpenRouter `google/gemini-2.5-flash` (default), Gemini API, or Vertex AI |
| Data store | ClickHouse Cloud 25.8+ |
| Scraping | Nimble Web Search Agents (`nimble_python` SDK) + Firecrawl fallback |
| LLM observability | Optional: Pydantic Logfire (recommended for public deploys) or Datadog Lapdog (local) + ddtrace |
| Frontend | React 18, Vite 5, TypeScript, Tailwind, Recharts, lucide-react |
| Logging | structlog (JSON), Datadog trace correlation |

---

## Repository layout

```
RegRadar-pk/
├── backend/
│   ├── main.py                     FastAPI app
│   ├── scheduler.py                APScheduler entry
│   ├── agents/
│   │   ├── base.py
│   │   ├── policy_crawler.py       team's crawler (Nimble + Pydantic AI)
│   │   └── impact_analysis.py      team's impact agent (cursor-driven)
│   ├── api/                        read-only dashboard endpoints
│   │   ├── dashboard.py            /api/dashboard/summary, /api/regulations, /api/data-assets
│   │   ├── violations.py           /api/violations, /api/policy-changes, /api/schema-events
│   │   ├── agents.py               /api/agent-runs, /api/agent-state, /api/coverage
│   │   └── datadog_metrics.py      statsd gauges
│   ├── data/
│   │   ├── schema.sql              canonical cloud schema
│   │   └── models.py               Pydantic shapes
│   ├── integrations/
│   │   ├── clickhouse_client.py    get_client (async), get_sync_client (per-call)
│   │   ├── nimble.py               nimble_python.Nimble extract
│   │   ├── firecrawl.py            silent fallback
│   │   └── vertex_ai.py            Pydantic AI provider resolver (OpenRouter → Gemini → Vertex)
│   └── utils/{env,logging}.py
├── frontend/                       Vite + React dashboard
├── scripts/
│   ├── run_with_lapdog.sh          generic Lapdog wrapper
│   ├── run_policy_crawler.sh       crawler under Lapdog
│   ├── run_impact_agent.sh         impact agent under Lapdog
│   ├── run_asset_scanner.sh        asset scanner stub
│   ├── setup_cc_accounts.py        cloud seed for cc_accounts
│   ├── test_crawler.py             crawl REG-005 only
│   └── smoke_test.py               7-check end-to-end smoke
├── seed/                           static JSON seeds
├── docs/                           architecture, API, data model, ERD, demo script
├── requirements.txt
├── .env.example
└── README.md
```

---

## ClickHouse tables the dashboard reads

The dashboard's data model: column-by-column reference in [`docs/regradar-clickhouse.md`](docs/regradar-clickhouse.md), ER diagram at [`docs/data_model_erd.html`](docs/data_model_erd.html).

| Table | Purpose |
|---|---|
| `regulations` | 7 controls (REG-001…REG-007), thresholds, `last_crawled_at` |
| `data_assets`, `critical_data_elements` | Asset inventory + CDEs |
| `asset_regulation_map` | Which assets are in scope of which regulations |
| `compliance_violations`, `remediation_steps` | Live state of breaches and how to fix them |
| `compliance_scans` | Time series of scan results |
| `policy_changes` | **Crawler-detected regulation changes (live)** |
| `schema_events` | Asset Scanner events |
| `cc_accounts` | Synthetic credit-card portfolio |

The Impact Analysis Agent expects 7 additional tables (`asset_changes`, `agent_state`, `policy_registry`, `violations`, `notification_failures`, `agent_dead_letter`, `asset_tags`). The full schema is in [`backend/data/schema.sql`](backend/data/schema.sql); apply it to your cloud cluster before running the scheduler.

---

## Troubleshooting

**The dashboard shows "NetworkError when attempting to fetch resource"**
The browser is loading from `localhost:5173` but the API is on `127.0.0.1:8000` (or vice versa). The default `APP_CORS_ORIGINS` in `.env.example` allows both, but if you locked it down, widen it.

**Policy Crawler: 429 quota exceeded on Gemini**
You're on the Gemini free tier (20 req/day on `gemini-2.5-flash`). Set `OPENROUTER_API_KEY` and the resolver auto-switches.

**`AttributeError: 'AsyncClient' object has no attribute 'aio'`**
You hit a known incompatibility between `pydantic-ai` and `google-genai >= 2.0` on the Vertex provider. Fix: set `OPENROUTER_API_KEY` so the code skips Vertex.

**`ImportError: cannot import name 'get_ch_client'`**
You're running an old version of `backend/scheduler.py` or `backend/agents/impact_analysis.py`. Pull the latest — both now import `get_sync_client` from `backend.integrations.clickhouse_client`.

**Scheduler crashes at `agent_state` query**
ClickHouse Cloud doesn't have the new Impact Analysis tables yet. Apply [`backend/data/schema.sql`](backend/data/schema.sql) to the cloud cluster.

---

## Docs

| Doc | Purpose |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture |
| [AGENTS.md](docs/AGENTS.md) | Agent contracts and prompts |
| [DATA_MODEL.md](docs/DATA_MODEL.md) | Column-by-column schema |
| [regradar-clickhouse.md](docs/regradar-clickhouse.md) | Schema quick reference |
| [API.md](docs/API.md) | Endpoint catalog |
| [FRONTEND.md](docs/FRONTEND.md) | UI components |
| [INTEGRATIONS.md](docs/INTEGRATIONS.md) | Nimble, Firecrawl, Vertex AI, Datadog |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Day 0 + cloud runbooks |
| [TESTING.md](docs/TESTING.md) | Demo + fallback procedures |
| [DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 3-minute pitch |
| [PRIZES.md](docs/PRIZES.md) | Sponsor-track strategy |

---

## License

MIT. See [LICENSE](LICENSE).
