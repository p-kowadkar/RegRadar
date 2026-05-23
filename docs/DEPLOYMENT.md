# DEPLOYMENT.md

How to go from zero to running RegRadar on your laptop, on a server, and during the demo.

This is the runbook. Level 3 detail -- every command is exact, every gotcha is called out.

---

## Table of Contents

1. [Day 0 Prep -- Tonight's Checklist](#1-day-0-prep--tonights-checklist)
2. [Local Development Setup](#2-local-development-setup)
3. [The Master .env File](#3-the-master-env-file)
4. [Loading Seed Data](#4-loading-seed-data)
5. [Running The Stack](#5-running-the-stack)
6. [Demo Day Runbook](#6-demo-day-runbook)
7. [Production Deployment (Post-Hackathon)](#7-production-deployment-post-hackathon)
8. [Common Gotchas](#8-common-gotchas)

---

## 1. Day 0 Prep -- Tonight's Checklist

Before you sleep, every box should be checked. Walking in tomorrow with these done means zero setup friction.

### Account Signups (do this first -- some take minutes for verification email)

- [ ] **Google Cloud** -- ensure access to project `gen-lang-client-0677154031`
- [ ] **ClickHouse Cloud** -- sign up at [clickhouse.cloud](https://clickhouse.cloud) ($300 credit, 30 days, no card)
- [ ] **Datadog** -- sign up at [datadoghq.com](https://www.datadoghq.com) (14-day trial, no card)
- [ ] **Nimble** -- sign up at [nimbleway.com](https://www.nimbleway.com) (5,000 page free trial)
- [ ] **OpenRouter** -- sign up at [openrouter.ai](https://openrouter.ai) (top up $5 for fallback safety)
- [ ] **Firecrawl** -- ensure existing API key still works ([firecrawl.dev](https://firecrawl.dev))
- [ ] **Luminai** -- credentials will be provided AT the hackathon (skip for now)

### Key Generation

- [ ] **GCP** -- enable Vertex AI API, Discovery Engine API, Generative Language API
- [ ] **GCP** -- run `gcloud auth application-default login` and `gcloud config set project gen-lang-client-0677154031`
- [ ] **GCP** -- generate API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) as backup
- [ ] **ClickHouse** -- create a Development-tier service in `us-east-1`, save host/user/password
- [ ] **Datadog** -- generate API key (Organization Settings → API Keys), note your DD_SITE
- [ ] **Nimble** -- copy API key from dashboard
- [ ] **OpenRouter** -- generate API key at [openrouter.ai/keys](https://openrouter.ai/keys)

### Tooling

- [ ] **Python 3.11+** installed (`python --version` to verify)
- [ ] **Node.js 20+** installed (`node --version` to verify)
- [ ] **Docker Desktop** installed and running (`docker ps` to verify)
- [ ] **gcloud CLI** installed (`gcloud --version`)
- [ ] **Antigravity IDE** downloaded from [antigravity.google](https://antigravity.google) and signed in
- [ ] **Repo cloned** locally: `git clone https://github.com/shashank1289/RegRadar.git`
- [ ] **VS Code or Antigravity** has Python + Pylance extensions installed
- [ ] **Postman or Bruno** installed for hitting test endpoints

### Verification Smoke Tests (run each, all must pass)

These commands verify your environment works before tomorrow. If any fail, fix tonight.

```bash
# 1. Verify Python + venv
python -m venv /tmp/regradar-test-venv
source /tmp/regradar-test-venv/bin/activate
pip install google-genai
python -c "from google import genai; print('genai OK')"

# 2. Verify Gemini works
python -c "
from google import genai
import os
client = genai.Client(
    vertexai=True,
    project=os.environ['GOOGLE_CLOUD_PROJECT'],
    location='us-central1'
)
r = client.models.generate_content(
    model='gemini-3.5-flash',
    contents='Reply with the word OK'
)
print('Gemini reply:', r.text)
"

# 3. Verify ClickHouse Cloud reachable
pip install clickhouse-connect
python -c "
import clickhouse_connect, os
c = clickhouse_connect.get_client(
    host=os.environ['CLICKHOUSE_HOST'],
    port=int(os.environ['CLICKHOUSE_PORT']),
    username=os.environ['CLICKHOUSE_USER'],
    password=os.environ['CLICKHOUSE_PASSWORD'],
    secure=True
)
print('ClickHouse version:', c.query('SELECT version()').result_rows[0][0])
"

# 4. Verify Nimble works
pip install nimble-python
python -c "
from nimble_python import Nimble
import os
n = Nimble(api_key=os.environ['NIMBLE_API_KEY'])
r = n.search(query='SEC press release', num_results=2)
print('Nimble search returned:', len(r.results), 'results')
"

# 5. Verify Datadog ingest works
pip install ddtrace
DD_API_KEY=$DD_API_KEY DD_SITE=$DD_SITE DD_LLMOBS_ENABLED=1 \
DD_LLMOBS_AGENTLESS_ENABLED=1 DD_LLMOBS_ML_APP=regradar-smoke \
ddtrace-run python -c "
from google import genai
import os
client = genai.Client(vertexai=True,
                     project=os.environ['GOOGLE_CLOUD_PROJECT'],
                     location='us-central1')
r = client.models.generate_content(
    model='gemini-3.5-flash',
    contents='ddtrace smoke test'
)
print('Trace should appear in Datadog LLM Obs in ~30 seconds')
"

# 6. Verify Docker can run ClickHouse locally
docker run --rm -d -p 18123:8123 -p 19000:9000 \
  --name regradar-local-test \
  --ulimit nofile=262144:262144 \
  clickhouse/clickhouse-server:latest
sleep 5
curl http://localhost:18123 -d "SELECT 1"
docker stop regradar-local-test
```

If ALL 6 smoke tests print expected output, you're ready.

### Pre-Demo File Backups

Save these in TWO places (laptop primary + cloud backup like Dropbox):

- [ ] `.env` with all keys filled in
- [ ] `seed/` directory contents
- [ ] Demo videos (record TWO -- one full-flow, one CFTC-only)

---

## 2. Local Development Setup

### One-Shot Setup

```bash
git clone https://github.com/shashank1289/RegRadar.git
cd RegRadar
chmod +x scripts/setup.sh
./scripts/setup.sh
```

`scripts/setup.sh` does the following (read it before running):

```bash
#!/bin/bash
set -e

# 1. Python virtualenv
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Frontend dependencies
(cd frontend && npm install)

# 3. Local ClickHouse via Docker
docker compose up -d clickhouse
echo "Waiting for ClickHouse to be ready..."
sleep 5

# 4. Apply schema
python -c "
import os, clickhouse_connect
c = clickhouse_connect.get_client(
    host='localhost', port=8123, username='default', password=''
)
with open('backend/data/schema.sql') as f:
    sql = f.read()
for stmt in sql.split(';'):
    if stmt.strip():
        c.command(stmt)
print('Schema applied')
"

# 5. Load seed data
python scripts/load_seed_data.py

# 6. Run smoke tests
python scripts/smoke_test.py

echo "✓ Setup complete. Run 'ddtrace-run uvicorn backend.main:app --reload' to start."
```

### Manual Setup (if setup.sh fails)

```bash
# Step 1: Python environment
python -m venv venv
source venv/bin/activate                    # Linux/Mac
# .\venv\Scripts\activate                    # Windows PowerShell
pip install --upgrade pip
pip install -r requirements.txt

# Step 2: Copy and fill .env
cp .env.example .env
# Edit .env -- fill in all the keys

# Step 3: Start local ClickHouse
docker compose up -d clickhouse
# Wait ~5 seconds for it to be ready

# Step 4: Apply schema
python scripts/apply_schema.py

# Step 5: Load seed data
python scripts/load_seed_data.py

# Step 6: Install frontend deps
cd frontend
npm install
cd ..

# Step 7: Verify
python scripts/smoke_test.py
```

---

## 3. The Master .env File

The single source of truth for configuration. `backend/utils/env.py` validates this at startup -- missing required vars cause immediate refusal to start.

**Never commit `.env` to git.** `.gitignore` includes it. Only `.env.example` is committed.

### .env.example (template)

```bash
# ════════════════════════════════════════════════════════════════
# GOOGLE CLOUD / VERTEX AI (required)
# ════════════════════════════════════════════════════════════════
GOOGLE_CLOUD_PROJECT=gen-lang-client-0677154031
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_GENAI_USE_VERTEXAI=True
GEMINI_API_KEY=AIza...                              # backup for scripts

# ════════════════════════════════════════════════════════════════
# OPENROUTER (required for fallback resilience)
# ════════════════════════════════════════════════════════════════
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# ════════════════════════════════════════════════════════════════
# CLICKHOUSE (required -- pick local OR cloud)
# ════════════════════════════════════════════════════════════════
# For LOCAL dev (default):
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=
CLICKHOUSE_SECURE=false
CLICKHOUSE_DATABASE=regradar

# For DEMO (override before going on stage):
# CLICKHOUSE_HOST=xxx.us-east-1.aws.clickhouse.cloud
# CLICKHOUSE_PORT=8443
# CLICKHOUSE_USER=default
# CLICKHOUSE_PASSWORD=...
# CLICKHOUSE_SECURE=true
# CLICKHOUSE_DATABASE=regradar

# ════════════════════════════════════════════════════════════════
# NIMBLE (required for scraping)
# ════════════════════════════════════════════════════════════════
NIMBLE_API_KEY=...

# ════════════════════════════════════════════════════════════════
# FIRECRAWL (required as silent fallback)
# ════════════════════════════════════════════════════════════════
FIRECRAWL_API_KEY=fc-...

# ════════════════════════════════════════════════════════════════
# DATADOG (required for observability)
# ════════════════════════════════════════════════════════════════
DD_API_KEY=...
DD_SITE=datadoghq.com                              # or us3, eu1, etc.
DD_SERVICE=regradar-backend
DD_ENV=hackathon
DD_LLMOBS_ENABLED=1
DD_LLMOBS_AGENTLESS_ENABLED=1
DD_LLMOBS_ML_APP=regradar

# ════════════════════════════════════════════════════════════════
# LUMINAI (provided at hackathon)
# ════════════════════════════════════════════════════════════════
LUMINAI_API_KEY=                                   # fill in on-site
LUMINAI_BASE_URL=                                  # fill in on-site
LUMINAI_WORKSPACE_ID=                              # fill in on-site

# ════════════════════════════════════════════════════════════════
# APP CONFIG
# ════════════════════════════════════════════════════════════════
APP_ENV=development                                 # development | demo | production
APP_PORT=8000
APP_LOG_LEVEL=INFO                                  # DEBUG | INFO | WARNING | ERROR
APP_CORS_ORIGINS=http://localhost:5173,http://localhost:3000
APP_WS_HEARTBEAT_SECONDS=30

# ════════════════════════════════════════════════════════════════
# AGENT CONFIG (sensible defaults; override only if needed)
# ════════════════════════════════════════════════════════════════
WATCHER_API_POLL_INTERVAL_SECONDS=900               # 15 min
WATCHER_SCRAPE_INTERVAL_SECONDS=3600                # 1 hour
AGENT_MAX_PER_MESSAGE=3                             # blackboard cap
AGENT_PRIMARY_THRESHOLD=0.85
AGENT_SUPPORTING_THRESHOLD=0.65
AGENT_CROSS_TALK_THRESHOLD=0.50
AUDITOR_REJECT_BLOCKS_DELIVERY=true                 # true for demo safety
```

### Environment Validation

`backend/utils/env.py` runs at import time:

```python
# backend/utils/env.py
import os
from typing import Optional


REQUIRED_VARS = [
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "OPENROUTER_API_KEY",
    "CLICKHOUSE_HOST",
    "CLICKHOUSE_PORT",
    "CLICKHOUSE_USER",
    "CLICKHOUSE_PASSWORD",
    "NIMBLE_API_KEY",
    "FIRECRAWL_API_KEY",
    "DD_API_KEY",
    "DD_SITE",
]


def validate() -> None:
    """Raise at import time if required vars are missing."""
    missing = [v for v in REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        raise RuntimeError(
            f"Missing required env vars: {', '.join(missing)}\n"
            f"Copy .env.example to .env and fill them in."
        )


def get(name: str, default: Optional[str] = None) -> str:
    """Get an env var with optional default."""
    value = os.environ.get(name, default)
    if value is None:
        raise KeyError(f"Env var not set: {name}")
    return value


def get_int(name: str, default: Optional[int] = None) -> int:
    raw = os.environ.get(name)
    if raw is None:
        if default is None:
            raise KeyError(f"Env var not set: {name}")
        return default
    return int(raw)


def get_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in ("true", "1", "yes")


# Called at module import
validate()
```

---

## 4. Loading Seed Data

### Order of Operations

`scripts/load_seed_data.py` runs:

1. Apply schema (`backend/data/schema.sql`)
2. Insert NovaPay company profile (`seed/novapay_profile.json`)
3. Insert static KG taxonomy nodes (regulators, jurisdictions, data object types)
4. Insert 20 pre-fetched regulations + embeddings (`seed/regulations.json`)
5. Insert regulation nodes into KG (derived from step 4)
6. Insert ~80 KG edges (`seed/kg_edges.json`)
7. Generate 3,000 derivative positions → insert (`seed/portfolios/generate_portfolios.py --type=derivatives`)
8. Generate 1,500 bond positions → insert
9. Generate 50,000 BNPL/lending accounts → insert
10. Insert 8 pre-defined controls (`seed/controls.json`)
11. Run initial test of each control → insert into `control_test_results`

Expected runtime: ~2-3 minutes locally, ~5 minutes against ClickHouse Cloud.

### Manual Re-Generation

If you need to regenerate portfolios with different parameters:

```bash
python seed/portfolios/generate_portfolios.py \
    --type=derivatives \
    --count=3000 \
    --seed=42 \
    --output=seed/portfolios/derivatives.parquet
```

Then re-load:

```bash
python scripts/load_seed_data.py --tables=derivatives_portfolio
```

### Verification

After loading, run:

```bash
python scripts/smoke_test.py --check-seed
```

Which validates:

- `SELECT COUNT(*) FROM kg_nodes` returns ~150 (regulators + jurisdictions + data objects + regs)
- `SELECT COUNT(*) FROM kg_edges` returns ~80
- `SELECT COUNT(*) FROM derivatives_portfolio` returns 3000
- `SELECT COUNT(*) FROM bonds_portfolio` returns 1500
- `SELECT COUNT(*) FROM lending_portfolio` returns 50000
- `SELECT COUNT(*) FROM controls` returns 8
- `SELECT COUNT(*) FROM reg_versions` returns 20
- Every control has at least one row in `control_test_results`

---

## 5. Running The Stack

### Development Mode

Two terminals. Both stay running.

**Terminal 1 -- Backend:**

```bash
source venv/bin/activate
ddtrace-run uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --log-level info
```

**Terminal 2 -- Frontend:**

```bash
cd frontend
npm run dev
# Open http://localhost:5173
```

### Background Workers

The Watcher polls APIs and scrapes on a schedule. It runs INSIDE the FastAPI process via `asyncio.create_task()` started in `lifespan`. No separate worker process needed for hackathon scope.

### Triggering Demo Events Manually

```bash
# In a third terminal
python scripts/demo_trigger.py --event=cftc_margin_amendment
python scripts/demo_trigger.py --event=ofac_sanctions_update
python scripts/demo_trigger.py --event=sec_cyber_disclosure
python scripts/demo_trigger.py --list                       # show all events
```

Each event POSTs to `/api/internal/trigger` which inserts a fake "new regulation" into `reg_versions` and posts to the blackboard. The full agent cascade fires.

---

## 6. Demo Day Runbook

The minute-by-minute plan for showtime.

### T-2 Hours: Final Prep

- [ ] Pull latest from `main` branch
- [ ] Run `./scripts/setup.sh` -- confirm everything works
- [ ] Load FRESH seed data (`python scripts/load_seed_data.py --reset`)
- [ ] Run smoke test (`python scripts/smoke_test.py`)
- [ ] Open Datadog LLM Obs tab in browser, verify traces flowing
- [ ] Open ClickHouse cloud console in browser
- [ ] Open Nimble dashboard, check remaining credits
- [ ] Stage the 5 demo events in `scripts/demo_trigger.py` to verify each works
- [ ] Record fresh demo videos (CFTC arc + full flow) -- save in 3 places
- [ ] Test internet on demo machine + hotspot backup

### T-30 Minutes: Pre-Stage

- [ ] Switch `.env` from local ClickHouse to Cloud
- [ ] Restart backend: `ddtrace-run uvicorn backend.main:app --port 8000`
- [ ] Restart frontend: `npm run dev`
- [ ] Pre-warm everything:
  - Hit `/api/health` -- verify 200 OK
  - Hit `/api/dashboard/summary` -- verify data loads
  - Open Datadog LLM Obs -- send one test message through chat
  - Verify the trace appears
- [ ] Close all unnecessary browser tabs
- [ ] Quit Slack, email, all notification sources
- [ ] Set system to "Do Not Disturb"
- [ ] Open ONLY: RegRadar UI, Datadog LLM Obs, terminal for demo_trigger
- [ ] Hide presenter notes / cheat sheet on second monitor

### T-5 Minutes: Final Check

- [ ] Backend logs scrolling cleanly, no ERROR lines
- [ ] Frontend Dashboard view shows current data, KPI cards populated
- [ ] WebSocket connection indicator GREEN
- [ ] One last smoke test: send "hi" in chat -- agent responds within 5 seconds
- [ ] Demo trigger primed: `python scripts/demo_trigger.py --event=cftc_margin_amendment --dry-run` (don't actually fire yet)

### Showtime: The 14-Second Cascade

1. **[Pitch opens]** -- Pranav delivers the hook
2. **[1:30 mark]** -- Pranav: "Let me show you what just happened in real time"
3. **[1:35]** -- Press the trigger: `python scripts/demo_trigger.py --event=cftc_margin_amendment`
4. **[1:36-1:50]** -- The cascade fires on screen. Agents post to chat:
   - 9:00:00 Watcher: "📥 New CFTC final rule detected via Nimble"
   - 9:00:03 Classifier: "🏷️ Classified: HIGH severity, us_federal, margin_collateral"
   - 9:00:05 Mapper: "🗺️ 847 IR swap positions affected, $4.2B notional"
   - 9:00:08 Analyst: "📊 214 BREACH, 312 AT_RISK, 321 PASSING"
   - 9:00:11 Advisor: "🛠️ Updating CTRL-001 threshold from 6% to 8%"
   - 9:00:12 Datadog alert appears in side panel
   - 9:00:14 Auditor: "✅ Chain approved, all citations grounded"
5. **[1:50]** -- Pranav switches to Knowledge Graph view
6. **[2:00]** -- Types "what if we expand to EU?" -- graph re-aligns, GDPR edges appear
7. **[2:30]** -- Clicks "Execute SAR filing" -- Luminai preview iframe loads
8. **[3:00]** -- Tab over to Datadog LLM Obs -- AI Agent Console showing the chain
9. **[3:30]** -- Business case slide
10. **[4:30]** -- Close

### If Something Breaks

**Demo cascade fails midway:**
- Don't pretend it's fine. Acknowledge briefly: "Let me show you the recording we captured an hour ago."
- Cut to pre-recorded video. Continue narration over it.

**Network/internet drops:**
- Switch to mobile hotspot (have it tethered and ready)
- If still down: full pre-recorded video, narrate over it

**ClickHouse Cloud slow / down:**
- Stop backend, change `.env` to point at local ClickHouse
- Restart backend
- 30 seconds of dead air -- ad-lib about the team while waiting

**An agent hallucinates obviously:**
- The Auditor should catch it. If not, deflect: "The Auditor flagged this -- we'd normally pause here"
- Move on quickly

---

## 7. Production Deployment (Post-Hackathon)

Not in hackathon scope, but here's the path:

### Backend Hosting

- **Option A:** Google Cloud Run (matches Vertex AI region)
- **Option B:** Fly.io (good async support)
- **Option C:** Railway (simpler ops)

Recommended: Cloud Run with `min_instances=1` so cold starts don't hurt agent latency.

### Frontend Hosting

- Vercel or Netlify -- both work fine with Vite/React

### ClickHouse

- Stay on ClickHouse Cloud, scale up to Production tier when needed
- Add a separate dev-tier service for non-prod

### Auth

- Add Clerk or Auth0 in front of the frontend
- Add JWT validation middleware to FastAPI routes
- Per-tenant data partitioning in ClickHouse (add `tenant_id` column to every table)

### Multi-Worker / Multi-Process

- Replace in-memory blackboard with Redis pub/sub
- Run uvicorn with `--workers 4`
- Use Redis as a distributed lock for agent claim resolution

### Background Job Queue

- Replace `asyncio.create_task` Watcher with Celery or Arq workers
- Schedule via Cron or Temporal

### Observability Beyond Datadog

- Sentry for error tracking
- BetterStack or PagerDuty for paging

### Secrets

- Migrate from `.env` to Google Secret Manager or HashiCorp Vault
- Rotate API keys quarterly

---

## 8. Common Gotchas

### Gemini Returns Empty Response

**Symptom:** `response.text` is empty or `response.parsed` is None.

**Cause:** Usually a safety filter trip on the prompt or output.

**Fix:** Check `response.candidates[0].finish_reason`. If `SAFETY` or `BLOCKLIST`, rephrase the prompt to avoid trigger terms. For regulatory content this is rare but possible if a prompt contains certain phrasing about money laundering or sanctions.

### ClickHouse Vector Search Returns No Results

**Symptom:** `cosineDistance` query returns empty.

**Cause:** Embedding array type mismatch. ClickHouse needs `Array(Float32)` explicitly.

**Fix:**

```sql
-- Wrong
SELECT * FROM kg_nodes
WHERE cosineDistance(embedding, [0.1, 0.2, ...]) < 0.3

-- Right
SELECT * FROM kg_nodes
WHERE cosineDistance(embedding, [0.1, 0.2, ...]::Array(Float32)) < 0.3
```

### Datadog LLM Obs Traces Don't Show Up

**Symptom:** Running with `ddtrace-run` but no traces appear in LLM Obs.

**Causes & Fixes:**

1. `DD_LLMOBS_ENABLED` not set → check `.env`
2. `DD_LLMOBS_AGENTLESS_ENABLED` not set → check `.env` (set to `1` for hackathon)
3. `DD_SITE` is wrong region → verify in Datadog account settings
4. Traces take 30-60 seconds to appear in UI → wait a minute
5. `ddtrace` version too old → `pip install --upgrade ddtrace`

### Nimble Returns 401 Unauthorized

**Symptom:** All Nimble calls fail with 401.

**Cause:** API key expired or wrong format.

**Fix:** Regenerate at nimble dashboard. Restart backend after updating `.env`.

### Frontend Can't Connect to WebSocket

**Symptom:** Browser console shows `WebSocket connection failed`.

**Cause:** CORS or wrong URL.

**Fix:**

1. Check `APP_CORS_ORIGINS` in `.env` includes `http://localhost:5173`
2. Verify WebSocket URL in frontend matches backend port: `ws://localhost:8000/ws`
3. If using HTTPS in production, must be `wss://`

### Pydantic v2 Validation Errors

**Symptom:** Agents fail with `ValidationError`.

**Cause:** Gemini returned JSON that doesn't match the expected schema.

**Fix:**

1. Check the agent's system prompt -- is the JSON schema fully specified?
2. Use Gemini's `response_schema` parameter (Pydantic class) to force schema adherence
3. If still failing, log the raw response and re-prompt with stricter instructions

### Local ClickHouse Container Won't Start

**Symptom:** `docker compose up clickhouse` exits immediately.

**Cause:** Usually port conflict (something else on 8123) or insufficient ulimit.

**Fix:**

```bash
# Check what's on port 8123
lsof -i :8123

# Or use a different port in docker-compose.yml
ports:
  - "18123:8123"

# Update .env
CLICKHOUSE_PORT=18123
```

### "module not found" After Activating venv

**Symptom:** `ModuleNotFoundError` even though you installed the package.

**Cause:** Two Pythons -- system Python vs venv Python.

**Fix:**

```bash
which python                       # should show venv path
which pip                          # should show venv path
deactivate && source venv/bin/activate
pip install -r requirements.txt
```

### Antigravity Hangs on Large Files

**Symptom:** IDE becomes unresponsive on big files.

**Fix:** Antigravity is in active development -- if it crashes, fall back to VS Code or Cursor temporarily. Most of the team's code should be in modular files under 500 lines anyway.

---

## AI Tool Hints

If you're an AI tool setting this up:

1. **Don't skip `.env.example`.** Create it FIRST. All other code depends on env vars being defined and validated.

2. **`backend/utils/env.py` is the gatekeeper.** Import it at the top of `backend/main.py` so missing vars fail fast at startup.

3. **`scripts/setup.sh` should be idempotent.** Running it twice should not break anything.

4. **`scripts/smoke_test.py` is the single source of truth for "is everything working."** Add a new check whenever you add a new integration.

5. **`docker-compose.yml` is for LOCAL dev only.** Production uses ClickHouse Cloud.
