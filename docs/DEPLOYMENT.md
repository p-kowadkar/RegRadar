# DEPLOYMENT.md

How to go from zero to running RegRadar on your laptop, on a server, and during the demo. Updated for the 4-agent TILA/FCRA architecture.

---

## Table of Contents

1. [Day 0 Prep -- Checklist](#1-day-0-prep--checklist)
2. [Local Development Setup](#2-local-development-setup)
3. [The Master .env File](#3-the-master-env-file)
4. [Loading Seed Data](#4-loading-seed-data)
5. [Running The Stack](#5-running-the-stack)
6. [Demo Day Runbook](#6-demo-day-runbook)
7. [Production Deployment (Post-Hackathon)](#7-production-deployment-post-hackathon)
8. [Common Gotchas](#8-common-gotchas)

---

## 1. Day 0 Prep -- Checklist

### Account Signups (some verification emails take minutes)

- [ ] **Google Cloud** -- ensure access to project `gen-lang-client-0677154031`
- [ ] **ClickHouse Cloud** -- sign up at [clickhouse.cloud](https://clickhouse.cloud) ($300 credit, 30 days)
- [ ] **Datadog** -- sign up at [datadoghq.com](https://www.datadoghq.com) (14-day trial)
- [ ] **Nimble** -- sign up at [nimbleway.com](https://www.nimbleway.com) (5,000 free searches)
- [ ] **Firecrawl** -- ensure API key works ([firecrawl.dev](https://firecrawl.dev))
- [ ] **Senso** -- sign up at [docs.senso.ai](https://docs.senso.ai), get API key from dashboard
- [ ] **Coinbase Developer Platform (x402)** -- sign up at [portal.cdp.coinbase.com](https://portal.cdp.coinbase.com), get API keys
- [ ] **OpenRouter** -- top up $5 for fallback ([openrouter.ai](https://openrouter.ai))

### Key Generation

- [ ] **GCP** -- enable Vertex AI API, Discovery Engine API, Generative Language API
- [ ] **GCP** -- run `gcloud auth application-default login` and `gcloud config set project gen-lang-client-0677154031`
- [ ] **ClickHouse** -- create a Development-tier service in `us-east-1`, save host/user/password
- [ ] **Datadog** -- generate API key (Organization Settings → API Keys), note your DD_SITE
- [ ] **Nimble** -- copy API key from dashboard
- [ ] **Senso** -- copy X-API-Key from `docs.senso.ai` after signup; note your namespace
- [ ] **Coinbase CDP** -- get API key ID + secret; generate a wallet for X402_RECIPIENT_ADDRESS
- [ ] **OpenRouter** -- generate API key

### Tooling

- [ ] **Python 3.11+** (`python --version`)
- [ ] **Node.js 20+** (`node --version`)
- [ ] **Docker Desktop** running (`docker ps`)
- [ ] **gcloud CLI** (`gcloud --version`)
- [ ] **Antigravity** or **Claude Code** for the build session
- [ ] **Repo cloned**: `git clone https://github.com/shashank1289/RegRadar.git`
- [ ] **VS Code or Antigravity** has Python + Pylance + ESLint extensions

### Verification Smoke Tests (each must pass tonight)

```bash
# 1. Verify Python + venv
python -m venv /tmp/regradar-venv
source /tmp/regradar-venv/bin/activate
pip install google-genai pydantic-ai
python -c "from google import genai; from pydantic_ai import Agent; print('OK')"

# 2. Verify Gemini 3.5 Flash
python -c "
from google import genai
import os
client = genai.Client(vertexai=True, project=os.environ['GOOGLE_CLOUD_PROJECT'], location='us-central1')
r = client.models.generate_content(model='gemini-3.5-flash', contents='Reply with OK')
print('Gemini 3.5 Flash:', r.text)
"

# 3. Verify Gemini 3.1 Pro
python -c "
from google import genai
import os
client = genai.Client(vertexai=True, project=os.environ['GOOGLE_CLOUD_PROJECT'], location='us-central1')
r = client.models.generate_content(model='gemini-3.1-pro', contents='Reply with OK')
print('Gemini 3.1 Pro:', r.text)
"

# 4. Verify gemini-embedding-001
python -c "
from google import genai
import os
client = genai.Client(vertexai=True, project=os.environ['GOOGLE_CLOUD_PROJECT'], location='us-central1')
r = client.models.embed_content(model='gemini-embedding-001', contents='test', config={'output_dimensionality': 768})
print('Embedding dims:', len(r.embeddings[0].values))
"

# 5. Verify ClickHouse Cloud reachable
pip install "clickhouse-connect[arrow]>=0.8.0"
python -c "
import clickhouse_connect, os
c = clickhouse_connect.get_client(host=os.environ['CLICKHOUSE_HOST'], port=int(os.environ['CLICKHOUSE_PORT']), username=os.environ['CLICKHOUSE_USER'], password=os.environ['CLICKHOUSE_PASSWORD'], secure=True)
print('ClickHouse:', c.query('SELECT version()').result_rows[0][0])
"

# 6. Verify Nimble SDK works
pip install "nimble-sdk>=1.0.0"
python -c "
from nimble_sdk import Nimble
import os
n = Nimble(api_key=os.environ['NIMBLE_API_KEY'])
r = n.search(query='CFPB credit card rule', num_results=2)
print(f'Nimble search returned: {len(r.results)} results')
"

# 7. Verify Senso reachable
pip install httpx
python -c "
import httpx, os
r = httpx.get('https://apiv2.senso.ai/health', headers={'X-API-Key': os.environ['SENSO_API_KEY']})
print('Senso:', r.status_code)
"

# 8. Verify Datadog with ddtrace 4.8+
pip install "ddtrace>=4.8.0" "pydantic-ai>=1.85.0"
DD_API_KEY=$DD_API_KEY DD_SITE=$DD_SITE DD_LLMOBS_ENABLED=1 DD_LLMOBS_AGENTLESS_ENABLED=1 DD_LLMOBS_ML_APP=regradar-smoke \
ddtrace-run python -c "
from google import genai
import os
client = genai.Client(vertexai=True, project=os.environ['GOOGLE_CLOUD_PROJECT'], location='us-central1')
r = client.models.generate_content(model='gemini-3.5-flash', contents='ddtrace smoke')
print('Trace should appear in Datadog LLM Obs in ~30 sec')
"

# 9. Verify Docker can run ClickHouse 25.8 locally
docker run --rm -d -p 18123:8123 --name regradar-ch-test --ulimit nofile=262144:262144 clickhouse/clickhouse-server:25.8
sleep 8
curl -s http://localhost:18123 --data "SELECT version()"
docker stop regradar-ch-test

# 10. Verify x402 (use testnet to avoid real USDC)
pip install "x402>=0.4.0"
python -c "from x402.fastapi import x402_protected; print('x402 SDK OK')"
```

If ALL 10 smoke tests pass tonight, you're ready.

### Pre-Demo File Backups

Save these in TWO places (laptop + cloud):

- [ ] `.env` with all keys filled in
- [ ] `seed/` directory
- [ ] Demo recordings (record TWO: full flow + headline schema_event only)

---

## 2. Local Development Setup

### One-Shot Setup

```bash
git clone https://github.com/shashank1289/RegRadar.git
cd RegRadar
chmod +x scripts/setup.sh
./scripts/setup.sh
```

### What `scripts/setup.sh` does

```bash
#!/bin/bash
set -e

# 1. Python env
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Frontend
(cd frontend && npm install)

# 3. Local ClickHouse via Docker
docker compose up -d clickhouse
echo "Waiting for ClickHouse..."
sleep 8

# 4. Apply schema
python scripts/apply_schema.py

# 5. Generate + load seed data
python seed/credit_cards/generate_accounts.py
python scripts/load_seed_data.py

# 6. Smoke
python scripts/smoke_test.py

echo "✓ Setup complete. Run 'ddtrace-run uvicorn backend.main:app --reload' to start."
```

### docker-compose.yml

```yaml
version: "3.8"
services:
  clickhouse:
    image: clickhouse/clickhouse-server:25.8
    container_name: regradar-clickhouse
    ports:
      - "8123:8123"
      - "9000:9000"
    environment:
      - CLICKHOUSE_DB=regradar
      - CLICKHOUSE_USER=default
      - CLICKHOUSE_PASSWORD=
    ulimits:
      nofile:
        soft: 262144
        hard: 262144
    volumes:
      - clickhouse-data:/var/lib/clickhouse

volumes:
  clickhouse-data:
```

---

## 3. The Master .env File

See `.env.example` in the repo root for the full template. Required vars:

- `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_GENAI_USE_VERTEXAI`
- `OPENROUTER_API_KEY`
- `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_USER` (password optional)
- `NIMBLE_API_KEY`, `FIRECRAWL_API_KEY`
- `DD_API_KEY`, `DD_SITE`
- `SENSO_API_KEY`

Optional (for monetization beat):
- `X402_RECIPIENT_ADDRESS`, `CDP_API_KEY_ID`, `CDP_API_KEY_SECRET`

The app refuses to start if any required var is missing -- see `backend/utils/env.py::validate()`.

---

## 4. Loading Seed Data

`scripts/load_seed_data.py` runs:

1. Apply schema (`backend/data/schema.sql`)
2. Insert Pinecrest Bank profile (`seed/issuer_profile.json`)
3. Insert 2 regulation versions -- TILA + FCRA (`seed/regulations.json`)
4. Embed + insert 4 policy chunks (`seed/policy_embeddings.json`)
5. Insert 6 compliance conditions (`seed/compliance_conditions.json`)
6. Generate + insert 50k credit card accounts
7. Insert 6 controls (`seed/controls.json`)
8. Run initial monitoring sweep

Expected runtime: ~90 seconds locally, ~3 min against ClickHouse Cloud.

### Verification

```bash
python scripts/smoke_test.py --check-seed
```

Which validates:
- `SELECT COUNT(*) FROM credit_card_accounts` returns 50,000
- `SELECT COUNT(*) FROM controls` returns 6
- `SELECT COUNT(*) FROM compliance_conditions` returns >= 6
- `SELECT COUNT(*) FROM policy_embeddings` returns 4
- `SELECT COUNT(*) FROM reg_versions` returns 2
- Every control has at least one row in `compliance_scans`

---

## 5. Running The Stack

### Development Mode

Two terminals, both stay running.

**Terminal 1 -- Backend (with ddtrace auto-instrumentation):**

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

### Background Loops

The Policy Crawler + Monitoring + Event Poller run INSIDE the FastAPI process via `asyncio.create_task()` from `lifespan`. No separate worker process needed.

### Triggering Demo Events Manually

```bash
# In a third terminal
python scripts/demo_trigger.py --scenario schema_enrichment_fcra
python scripts/demo_trigger.py --scenario dispute_filed_cross_trigger
python scripts/demo_trigger.py --scenario policy_change_tila_promo_notice
python scripts/demo_trigger.py --list
```

---

## 6. Demo Day Runbook

### T-2 Hours: Final Prep

- [ ] `git pull` latest from `main`
- [ ] Run `./scripts/setup.sh` -- confirm everything works
- [ ] Load fresh seed data (`python scripts/load_seed_data.py --reset`)
- [ ] Run smoke test (`python scripts/smoke_test.py`)
- [ ] Open Datadog LLM Obs in browser, verify traces flowing
- [ ] Open ClickHouse cloud console
- [ ] Open Nimble dashboard, check remaining credits
- [ ] Open Senso dashboard, verify published_briefs namespace
- [ ] Stage each demo scenario, verify it lands the expected breach number
- [ ] Record fresh demo videos -- save in 3 places (laptop + cloud + USB)
- [ ] Test internet on demo machine + hotspot backup

### T-30 Minutes: Pre-Stage

- [ ] Switch `.env` to ClickHouse Cloud (uncomment the cloud block)
- [ ] Restart backend: `ddtrace-run uvicorn backend.main:app --port 8000`
- [ ] Restart frontend: `npm run dev`
- [ ] Pre-warm:
  - Hit `/api/health/integrations` -- verify every integration "ok"
  - Hit `/api/agents/status` -- 4 agents listed
  - Open Datadog AI Agent Console
  - Pre-fetch a published cited.md URL from a dry run (in case live publish fails)
- [ ] Close all unnecessary browser tabs
- [ ] Quit Slack, email, all notifications
- [ ] Set system to "Do Not Disturb"
- [ ] Open ONLY: RegRadar UI, Datadog LLM Obs, terminal for demo_trigger, terminal for `curl`

### T-5 Minutes: Final Check

- [ ] Backend logs scrolling cleanly, no ERROR lines
- [ ] Dashboard shows: 6 controls (mix of PASSING and possibly some WARNING from seed data), KPI cards populated
- [ ] WebSocket indicator GREEN
- [ ] Fire one test trigger in dry-run mode, verify the chain works end-to-end

### Showtime: The Cascade

See [DEMO_SCRIPT.md](DEMO_SCRIPT.md) for the second-by-second pitch.

The two live triggers, in order:

1. `python scripts/demo_trigger.py --scenario schema_enrichment_fcra` (headline, at 0:40)
2. `python scripts/demo_trigger.py --scenario dispute_filed_cross_trigger` (secondary, at 1:50)

Closing beat: `curl -i http://localhost:8000/api/compliance-brief/fcra` then `x402-curl http://localhost:8000/api/compliance-brief/fcra` (at 2:30).

### If Something Breaks

See [DEMO_SCRIPT.md section "Failure recovery"](DEMO_SCRIPT.md#failure-recovery----if-something-breaks-live).

---

## 7. Production Deployment (Post-Hackathon)

Not in scope. Sketch:

- Backend: Google Cloud Run (matches Vertex region) with `min_instances=1`
- Frontend: Vercel or Netlify
- ClickHouse Cloud Production tier
- Auth: Clerk or Auth0 in front of frontend; JWT validation middleware on FastAPI
- Multi-tenant: add `tenant_id` column to every table; per-tenant data partitioning
- Background workers: replace in-process Policy Crawler / Monitoring loops with Celery or Arq + Redis Cloud
- Secrets: Google Secret Manager
- Sentry for error tracking; PagerDuty for paging

---

## 8. Common Gotchas

### Gemini returns empty response

Check `response.candidates[0].finish_reason`. If `SAFETY` or `BLOCKLIST`, rephrase the prompt. Rare with regulatory content but possible.

### ClickHouse vector search returns no results

The query vector MUST be cast to `Array(Float32)`:

```sql
-- Wrong
SELECT * FROM policy_embeddings ORDER BY cosineDistance(embedding, [0.1, 0.2, ...]) LIMIT 5;

-- Right
SELECT * FROM policy_embeddings ORDER BY cosineDistance(embedding, [0.1, 0.2, ...]::Array(Float32)) LIMIT 5;
```

Also: don't use deprecated index types (`annoy`, `usearch`) -- removed in ClickHouse 25.8. Use `vector_similarity('hnsw', ..., 768)`.

### Datadog LLM Obs traces don't appear

1. Confirm `DD_LLMOBS_ENABLED=1` and `DD_LLMOBS_AGENTLESS_ENABLED=1` are set
2. Confirm `DD_SITE` matches your account's region
3. Confirm `ddtrace>=4.8.0` (older versions miss Pydantic AI tool spans)
4. Traces take 30-60s to appear in UI -- be patient

### Pydantic AI agent runs not auto-instrumented

You need `pydantic-ai>=1.63.0` AND `ddtrace>=4.8.0`. Verify:

```bash
pip show pydantic-ai ddtrace
```

### Nimble returns 401 Unauthorized

API key expired or wrong format. Regenerate at nimbleway.com dashboard. Restart backend after updating `.env`.

### Senso publish fails

Check that your X-API-Key works against `https://apiv2.senso.ai/health`. If 401, regenerate at docs.senso.ai. The publishing namespace must be claimed -- the first publish to a namespace claims it for you.

### x402 middleware errors

For demo, USE `X402_NETWORK=base-sepolia` (testnet) to avoid real USDC outflows. The protocol is identical -- only the chain changes.

### Frontend can't connect to WebSocket

1. Check `APP_CORS_ORIGINS` includes `http://localhost:5173`
2. Verify WS URL: `ws://localhost:8000/ws/stream` (not `/ws/chat` -- that was the old design)
3. If using HTTPS in prod, must be `wss://`

### Pydantic v2 validation errors on agent output

Pydantic AI's `output_type` parameter constrains the LLM's JSON output. If validation fails:
1. Check the agent's system prompt -- is the JSON schema specified?
2. Pydantic AI auto-retries with the schema -- usually succeeds on retry
3. If still failing, log the raw response and tighten the prompt

### Local ClickHouse container won't start

Usually port conflict on 8123 or insufficient ulimit. Map to a different port (`18123:8123`) and update `.env`. Or stop any other ClickHouse instance with `docker ps | grep clickhouse`.

### "module not found" after activating venv

Two Pythons -- system vs venv. Fix:

```bash
which python                       # should show venv path
deactivate && source venv/bin/activate
pip install -r requirements.txt
```
