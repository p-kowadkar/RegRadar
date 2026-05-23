# RegRadar

**Agentic Governance & Compliance Intelligence for Fintechs**

> When a regulation changes, RegRadar's agents go to work immediately. They detect the change, scan YOUR financial instruments and customer accounts, classify each as in-breach or at-risk, update governance controls automatically, and route alerts to the right owner -- all in under 15 seconds. No human had to ask.

Built for the **Agentic Engineering Hack -- NYC** (tokens& × DeepMind × Datadog × Nimble × ClickHouse × Luminai × Senso × Evolution Equity).

---

## Quick Links

| Doc | Purpose |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture, blackboard pattern, data flow |
| [AGENTS.md](docs/AGENTS.md) | All 6 agents -- behavior, prompts, I/O contracts, error handling |
| [DATA_MODEL.md](docs/DATA_MODEL.md) | Complete ClickHouse schema -- 8 tables, every column |
| [API.md](docs/API.md) | FastAPI endpoints, WebSocket protocol, request/response shapes |
| [FRONTEND.md](docs/FRONTEND.md) | React component breakdown, state management, UI contracts |
| [SEED_DATA.md](docs/SEED_DATA.md) | Pre-loaded data -- regulations, portfolios, controls, KG edges |
| [INTEGRATIONS.md](docs/INTEGRATIONS.md) | Sponsor wiring -- Nimble, ClickHouse, Datadog, Luminai, Vertex AI |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Day 0 prep, .env setup, local + cloud runbooks |
| [TESTING.md](docs/TESTING.md) | Demo run-through, smoke tests, fallback procedures |

---

## Tech Stack (Locked)

| Layer | Tech | Why |
|---|---|---|
| Backend language | Python 3.11+ | Async, modern type hints |
| Backend framework | FastAPI | Async-native, OpenAPI, WebSockets |
| Data contracts | Pydantic v2 | Strict validation everywhere |
| Logging | structlog | Structured JSON, Datadog-ready |
| Data store | ClickHouse (Cloud + local Docker for dev) | KG + vectors + analytics in one |
| LLM providers | Vertex AI (Gemini 3.5 Flash + 3.1 Pro) | Sponsor + Check Grounding |
| LLM fallback | OpenRouter | If Gemini rate-limits |
| Web scraping | Nimble (primary) + Firecrawl (silent fallback) | Sponsor + resilience |
| Observability | Datadog LLM Observability | Sponsor + multi-agent monitoring |
| Workflow automation | Luminai | Sponsor + action execution |
| Frontend | React + TypeScript + Tailwind | Type safety, modern DX |
| Frontend hosting | Lovable (preferred) or Vercel | Fast deployment |
| Agent communication | In-memory blackboard | Hackathon scope, no Redis needed |
| Code repo | github.com/shashank1289/RegRadar | Existing |

---

## Project Structure

```
RegRadar/
├── README.md
├── .env.example
├── requirements.txt
├── pyproject.toml
├── docker-compose.yml              # local ClickHouse, optional Redis
├── docs/                            # all spec markdown lives here
│   ├── ARCHITECTURE.md
│   ├── AGENTS.md
│   ├── DATA_MODEL.md
│   ├── API.md
│   ├── FRONTEND.md
│   ├── SEED_DATA.md
│   ├── INTEGRATIONS.md
│   ├── DEPLOYMENT.md
│   └── TESTING.md
├── backend/
│   ├── __init__.py
│   ├── main.py                     # FastAPI entry
│   ├── config.py                   # Pydantic Settings
│   ├── logging_setup.py            # structlog config
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── blackboard.py           # The shared state
│   │   ├── orchestrator.py         # Conflict resolution
│   │   └── heartbeat.py            # Scheduled triggers
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py                 # BaseAgent ABC + 3-phase eval
│   │   ├── watcher.py              # The Watcher (no LLM)
│   │   ├── classifier.py           # The Classifier
│   │   ├── mapper.py               # The Mapper
│   │   ├── analyst.py              # The Analyst
│   │   ├── advisor.py              # The Advisor
│   │   ├── auditor.py              # The Auditor
│   │   └── prompts/                # System prompts as .txt files
│   │       ├── classifier.txt
│   │       ├── mapper.txt
│   │       ├── analyst.txt
│   │       ├── advisor.txt
│   │       └── auditor.txt
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── vertex_ai.py            # Gemini client + Check Grounding
│   │   ├── clickhouse_client.py    # ClickHouse wrapper
│   │   ├── nimble_client.py        # Nimble scraping
│   │   ├── firecrawl_client.py     # Firecrawl fallback
│   │   ├── datadog_client.py       # Custom metrics + alerts
│   │   └── luminai_client.py       # Workflow execution
│   ├── data/
│   │   ├── __init__.py
│   │   ├── schema.py               # Pydantic models for everything
│   │   ├── kg_repo.py              # Knowledge graph repository
│   │   ├── portfolio_repo.py       # Portfolio tables repository
│   │   ├── controls_repo.py        # Governance controls repository
│   │   └── reg_repo.py             # Regulations repository
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes_company.py       # /api/company/*
│   │   ├── routes_graph.py         # /api/graph/*
│   │   ├── routes_feed.py          # /api/feed/*
│   │   ├── routes_controls.py      # /api/controls/*
│   │   ├── routes_monitor.py       # /api/monitor/*
│   │   └── ws_chat.py              # /ws/chat
│   └── utils/
│       ├── __init__.py
│       ├── hashing.py              # SHA256 for change detection
│       └── time_helpers.py
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── types.ts                # All TypeScript interfaces (mirror Pydantic)
│       ├── api/
│       │   ├── client.ts           # HTTP client (axios/fetch)
│       │   └── websocket.ts        # WebSocket connection manager
│       ├── components/
│       │   ├── Sidebar.tsx
│       │   ├── Dashboard.tsx
│       │   ├── GroupChat.tsx
│       │   ├── KnowledgeGraph.tsx
│       │   ├── ControlsBoard.tsx
│       │   ├── AgentMessage.tsx
│       │   ├── KPICard.tsx
│       │   ├── FeedItem.tsx
│       │   └── RightPanel.tsx
│       ├── store/
│       │   └── store.ts            # Zustand global state
│       └── styles/
│           └── globals.css
├── seed/
│   ├── regulations.json            # 20 core regs with text
│   ├── controls.json               # 8 pre-defined CTRL-*
│   ├── kg_edges.json               # initial graph edges
│   ├── novapay_profile.json        # demo company profile
│   ├── generate_portfolios.py      # synthetic portfolio generator
│   └── load_seed.py                # one-shot loader script
└── scripts/
    ├── setup_clickhouse.py         # create all tables
    ├── verify_env.py               # smoke test all integrations
    ├── trigger_demo_event.py       # stage CFTC margin amendment
    └── record_demo.py              # browser automation for backup video
```

---

## Day 0 Setup (TL;DR)

```bash
# 1. Clone + venv
git clone https://github.com/shashank1289/RegRadar.git
cd RegRadar
python -m venv venv && source venv/bin/activate

# 2. Install
pip install -r requirements.txt

# 3. Copy and fill .env
cp .env.example .env
# fill in: GEMINI_API_KEY, CLICKHOUSE_*, DD_API_KEY, NIMBLE_API_KEY, FIRECRAWL_API_KEY

# 4. Auth GCP for Vertex AI
gcloud auth application-default login
gcloud config set project gen-lang-client-0677154031

# 5. Start local ClickHouse (or point to ClickHouse Cloud)
docker compose up -d clickhouse

# 6. Set up schema + load seed data
python scripts/setup_clickhouse.py
python seed/load_seed.py

# 7. Smoke test
python scripts/verify_env.py

# 8. Run
ddtrace-run uvicorn backend.main:app --reload --port 8000

# 9. Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

See [DEPLOYMENT.md](docs/DEPLOYMENT.md) for full details.

---

## The Demo Arc (CFTC Margin Rule)

At 9:00:00, RegRadar detects a CFTC margin rule amendment scraped by Nimble. In 14 seconds:

1. **9:00:00** -- The Watcher detects + posts to blackboard
2. **9:00:03** -- The Classifier labels: jurisdiction=us_federal, severity=HIGH, deadline=60d
3. **9:00:05** -- The Mapper queries: 847 IR swap positions, $4.2B notional
4. **9:00:08** -- The Analyst classifies: 214 BREACH, 312 AT_RISK, 321 PASSING
5. **9:00:11** -- The Advisor updates CTRL-001 threshold 6% → 8%
6. **9:00:12** -- Datadog critical alert fires to Risk Team
7. **9:00:14** -- The Auditor approves the chain, citations verified

Total: 14 seconds. No human triggered it.

---

## Critical Rules for AI Tools Building This

1. **Always use Pydantic v2 models for data contracts.** Never pass raw dicts between modules.
2. **All LLM calls go through `backend/integrations/vertex_ai.py`** -- never instantiate the Gemini client elsewhere.
3. **All ClickHouse access goes through repository classes in `backend/data/`** -- never write raw SQL in agents or routes.
4. **All agent base behavior lives in `backend/agents/base.py::BaseAgent`** -- concrete agents only override the abstract methods.
5. **All errors must use the custom exception hierarchy in `backend/utils/exceptions.py`** -- no bare `except`.
6. **All logs use structlog with bound context** -- never `print()`, never standard `logging`.
7. **All async functions must be properly awaited** -- no fire-and-forget except via `asyncio.create_task()` with logging.
8. **TypeScript types in `frontend/src/types.ts` must mirror Pydantic models exactly.**
9. **Never invent regulatory citations, fine amounts, or case names** -- agent prompts enforce this.
10. **Never use the OpenAI SDK directly** -- only via Vertex AI / Gemini.

Read [ARCHITECTURE.md](docs/ARCHITECTURE.md) next.
