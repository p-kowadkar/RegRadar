# DEPLOY.md

How to publish RegRadar so anyone with a URL can use it. **Total cost: $0/month.**

Architecture:

```
       Browser
         │
         │  https://regradar.pages.dev
         ▼
┌────────────────────┐         ┌──────────────────────────┐
│  Cloudflare Pages  │ ──API──▶│  Hugging Face Spaces     │
│  React/Vite SPA    │         │  Docker FastAPI :7860    │
│  (free, unlimited) │         │  (free CPU-basic)        │
└────────────────────┘         └──────────┬───────────────┘
                                          │
              ClickHouse Cloud ◀──────────┤
              (you already pay)           │
                                          ▼
                                  UptimeRobot (free)
                                  GET /health every 5 min
                                  -> never sleeps
```

---

## Table of contents

1. [Prerequisites](#1-prerequisites)
2. [Deploy the backend — pick one host](#2-deploy-the-backend--pick-one-host)
   - 2a. [Hugging Face Spaces](#2a-hugging-face-spaces-free) (free, sleeps in 48h, keep-warm with UptimeRobot)
   - 2b. [DigitalOcean App Platform](#2b-digitalocean-app-platform-5mo) ($5/mo, never sleeps)
3. [Deploy the frontend to Cloudflare Pages](#3-deploy-the-frontend-to-cloudflare-pages)
4. [Keep the backend awake with UptimeRobot](#4-keep-the-backend-awake-with-uptimerobot) (HF only)
5. [Add Cloudflare Turnstile (bot protection)](#5-add-cloudflare-turnstile-bot-protection)
6. [Enable BYOK + SlowAPI (cost protection)](#6-enable-byok--slowapi-cost-protection)
7. [Observability (optional)](#7-observability-optional)
8. [Backups + recovery](#8-backups--recovery)
9. [Cost ceiling math](#9-cost-ceiling-math)

---

## 1. Prerequisites

- GitHub repo pushed (`prod` branch on github.com/p-kowadkar/RegRadar)
- A populated `.env` saved in 1Password ("RegRadar — .env (prod)")
- Accounts (all free):
  - **[huggingface.co](https://huggingface.co)** — backend option A (free)
  - **OR [cloud.digitalocean.com](https://cloud.digitalocean.com)** — backend option B ($5/mo, $200 starter credit for new accounts)
  - [dash.cloudflare.com](https://dash.cloudflare.com) — frontend + Turnstile (free)
  - [uptimerobot.com](https://uptimerobot.com) — keep-warm pings (HF only, free)
- Optional later: Cloudflare custom domain ($10/yr)

---

## 2. Deploy the backend — pick one host

The Dockerfile is portable: it defaults to port 7860 (HF Spaces) but reads
`$PORT` at runtime so it also works on DO App Platform, Railway, Fly.io, etc.

### 2a. Hugging Face Spaces (free)

HF Spaces runs your `Dockerfile` and binds it to a public URL like
`https://pkowadkar-regradar.hf.space`. Free CPU-basic tier sleeps only after
**48 hours** idle — UptimeRobot keeps it permanently warm (step 4).

**Create the Space:**

1. Go to https://huggingface.co/new-space
2. **Owner**: `pkowadkar`
3. **Space name**: `regradar`
4. **License**: MIT
5. **SDK**: **Docker** → **Blank**
6. **Hardware**: CPU basic (free, 16 GB RAM)
7. **Visibility**: Public
8. Click **Create Space**

**Push the backend code:**

The Space is its own git repo. From the RegRadar repo root:

```powershell
git remote add hf https://huggingface.co/spaces/pkowadkar/regradar
git push hf prod:main
```

You may need an HF access token (`hf_…`) when prompted:
- https://huggingface.co/settings/tokens → New token → role **Write**
- Use the token as the password.

HF auto-builds the `Dockerfile` and starts the container. First build takes
**3-5 minutes**. Watch logs at:
`https://huggingface.co/spaces/pkowadkar/regradar?logs=build`

**Configure secrets:**

In the Space → **Settings** → **Variables and secrets** → **New secret**.
Add every value from `.env` Sections [A] + [B] (see the [shared secrets
list](#secrets-for-either-host)). Restart the Space after saving.

**Verify the backend:**

```powershell
curl https://pkowadkar-regradar.hf.space/health
# -> {"status":"ok"}

curl https://pkowadkar-regradar.hf.space/api/dashboard/summary
# -> {"monitored":12,"accountedFor":8,...}
```

If `/api/dashboard/summary` 500s with `KeyError: 'CLICKHOUSE_HOST'`, the
secrets aren't injected yet — restart the Space.

---

### 2b. DigitalOcean App Platform ($5/mo)

DO App Platform reads your `Dockerfile` straight from GitHub, builds it on
their infra, and exposes the container on a `*.ondigitalocean.app` URL with
free SSL. **Never sleeps**, no UptimeRobot needed.

**Create the App:**

1. Go to https://cloud.digitalocean.com/apps → **Create App**
2. **Service Provider**: GitHub → **Authorize DigitalOcean**
3. **Repository**: `p-kowadkar/RegRadar`
4. **Branch**: `prod`
5. **Source Directory**: leave as `/` (Dockerfile is at the repo root)
6. **Autodeploy on push**: leave checked
7. Click **Next**

**Configure the resource:**

App Platform should auto-detect the Dockerfile. On the **Resources** screen:

1. Click the auto-created resource (named `regradar` or similar)
2. **Resource Type**: keep as **Web Service**
3. **Edit** → **Plan**:
   - **Basic** plan
   - **Container Size**: `512 MB RAM | 1 vCPU` ($5/mo)
4. **HTTP Port**: `8080` (App Platform's default — our Dockerfile binds to `$PORT` automatically)
5. **Health Check Path**: `/health` (uses the endpoint we built)
6. Click **Back**, then **Next**

**Set environment variables:**

Still on the create screen → **Environment Variables** for the service. Add
every value from `.env` Sections [A] + [B] (see the [shared secrets
list](#secrets-for-either-host)). Mark `CLICKHOUSE_PASSWORD`, all API keys,
and `TURNSTILE_SECRET_KEY` as **encrypted**.

Click **Next** → **Region** (pick the closest to your ClickHouse Cloud
region — likely `nyc` or `sfo`) → **App Info** → name it `regradar` →
**Create Resources**.

Build takes ~5 minutes. Watch logs in the dashboard. Final URL appears at
the top: `https://regradar-XXXXX.ondigitalocean.app`.

**Verify:**

```powershell
curl https://regradar-XXXXX.ondigitalocean.app/health
# -> {"status":"ok"}

curl https://regradar-XXXXX.ondigitalocean.app/api/dashboard/summary
# -> {"monitored":12,"accountedFor":8,...}
```

**Push-to-deploy**: with Autodeploy enabled, every `git push origin prod`
triggers a rebuild (~5 min). To deploy a hotfix without waiting for build,
use the dashboard's **Actions → Force Rebuild and Deploy**.

---

### Secrets for either host

Add to HF Space → Variables and secrets, OR DO App Platform → Environment
Variables. Same list either way.

| Secret | Value / source |
|---|---|
| `CLICKHOUSE_HOST` | from your `.env` |
| `CLICKHOUSE_PORT` | `8443` |
| `CLICKHOUSE_USER` | `default` |
| `CLICKHOUSE_PASSWORD` | from your `.env` (mark encrypted on DO) |
| `CLICKHOUSE_SECURE` | `true` |
| `CLICKHOUSE_DATABASE` | `regradar` |
| `OPENROUTER_API_KEY` | recommended LLM (mark encrypted) |
| `FIRECRAWL_API_KEY` | recommended scraper (mark encrypted) |
| `GOOGLE_CLOUD_PROJECT` | optional, only if using Vertex ADC instead |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` (paired with above) |
| `NIMBLE_API_KEY` | optional, falls back to Firecrawl |
| `LOGFIRE_TOKEN` | optional (step 7) |
| `APP_CORS_ORIGINS` | `https://regradar.pages.dev` (update after step 3) |
| `ENABLE_SCHEDULERS` | `false` (recommended for public demo) |
| `BYOK_ENABLED` | `true` |
| `DAILY_LLM_CALL_BUDGET` | `500` |
| `TURNSTILE_ENABLED` | `false` (set `true` after step 5) |
| `TURNSTILE_SECRET_KEY` | (after step 5, mark encrypted) |

---

## 3. Deploy the frontend to Cloudflare Pages

### 3a. Connect the repo

1. https://dash.cloudflare.com → **Workers & Pages** → **Create** → **Pages**
2. **Connect to Git** → select **RegRadar** → branch **prod**
3. **Framework preset**: Vite
4. **Build command**: `npm run build`
5. **Build output directory**: `dist`
6. **Root directory** (advanced): `frontend`

### 3b. Build-time environment variables

Settings → Environment variables → Production:

| Variable | Value |
|---|---|
| `VITE_API_URL` | HF: `https://pkowadkar-regradar.hf.space` <br> DO: `https://regradar-XXXXX.ondigitalocean.app` |
| `VITE_TURNSTILE_SITE_KEY` | (set after step 5) |
| `VITE_ENABLE_BYOK` | `true` |

Click **Save and Deploy**. First build takes ~90 seconds. Site goes live at
`https://regradar.pages.dev`.

### 3c. Update backend CORS

Back in HF Spaces → Secrets → edit `APP_CORS_ORIGINS`:

```
https://regradar.pages.dev,https://<your-preview>.pages.dev
```

Restart the Space.

---

## 4. Keep the backend awake with UptimeRobot

> **Skip this step if you chose DigitalOcean App Platform (2b).** DO doesn't
> sleep — UptimeRobot is only useful there as an outage notifier (still
> worth setting up but not critical).

HF Spaces free tier sleeps after 48 hours idle. A 5-minute ping makes that
window irrelevant.

1. https://uptimerobot.com → Sign up (free)
2. **+ New Monitor** → **HTTPS**
3. **Friendly name**: `RegRadar backend`
4. **URL**: `https://pkowadkar-regradar.hf.space/health` (HF) or `https://regradar-XXXXX.ondigitalocean.app/health` (DO)
5. **Monitoring interval**: 5 minutes (free tier minimum)
6. **Save**

You'll get an email if the backend stops responding. Free tier supports 50
monitors, so also add the Pages URL.

**Why this works for HF**: each `/health` request resets the idle timer.
50,000 keep-warm requests/month is trivial — no rate limit hit.

---

## 5. Add Cloudflare Turnstile (bot protection)

Free, invisible CAPTCHA. Blocks scripted abuse of your demo endpoint before
it reaches Python.

### 5a. Create a Turnstile site

1. dash.cloudflare.com → **Turnstile** → **Add site**
2. **Site name**: `regradar-demo`
3. **Hostnames**: `regradar.pages.dev` (and your custom domain if you have one)
4. **Widget mode**: Invisible
5. **Save**

Copy the **Site key** (public) and **Secret key** (private).

### 5b. Wire it up

| Where | Variable | Value |
|---|---|---|
| HF Spaces secret | `TURNSTILE_ENABLED` | `true` |
| HF Spaces secret | `TURNSTILE_SITE_KEY` | site key |
| HF Spaces secret | `TURNSTILE_SECRET_KEY` | secret key |
| Cloudflare Pages env | `VITE_TURNSTILE_SITE_KEY` | site key (same value) |

Restart the Space + redeploy Pages. The frontend will render an invisible
widget on first page load; the backend will reject demo-trigger requests
without a valid token.

> Backend validator and frontend widget integration are tracked in the
> follow-up step "BYOK + Turnstile wiring". This guide covers the
> infrastructure side — the code lives in `backend/api/security.py` (when
> built).

---

## 6. Enable BYOK + SlowAPI (cost protection)

Three tiers of users on a single endpoint:

| User | What they send | Cost to you |
|---|---|---|
| Bot | (blocked by Turnstile) | $0 |
| Visitor, no key | Demo pool, SlowAPI capped at `DEMO_API_RATE_LIMIT` per IP | ~$0.08/day max per IP |
| Power user | `X-User-API-Key` + `X-User-LLM-Provider` headers | $0 to you |

Relevant `.env` vars (section [B]):

```bash
BYOK_ENABLED=true
BYOK_BYPASS_RATE_LIMIT=true
DEMO_API_RATE_LIMIT=10/day
DEMO_API_BURST_LIMIT=3/minute
DAILY_LLM_CALL_BUDGET=500
```

### What's wired today

**Phase 1 — security primitives + event-row trigger**

- `backend/api/security.py` — `verify_turnstile`, `extract_user_keys` (LLM + Scraper headers), `limiter` (smart per-IP / per-request-UUID key_func), `check_and_increment_budget`, `current_budget_state`
- `backend/api/trigger.py` — `POST /api/trigger` + `GET /api/trigger/budget`
- Three scenarios (`schema_enrichment_fcra`, `dispute_filed`, `promo_rate_expiry`) insert event rows into ClickHouse
- SlowAPI rate-limits demo-pool requests; BYOK LLM key bypasses
- Daily kill switch returns 503 when `DAILY_LLM_CALL_BUDGET` exhausted

**Phase 2 — full BYOK end-to-end on `/api/trigger/crawl`**

- `backend/integrations/vertex_ai.py:vertex_model_for_user(key, provider)` — builds a Pydantic AI Model bound to a user-provided LLM key. Supports `openrouter`, `gemini`, `openai`. Does NOT mutate the singleton.
- `backend/integrations/nimble.py:scrape_url(..., api_key_override=None)` — fresh Nimble client per request when BYOK present.
- `backend/integrations/firecrawl.py:scrape_url(..., api_key_override=None)` — same pattern.
- `backend/agents/policy_crawler.py:crawl_one(..., llm_model=None, scraper_key=None, scraper_provider=None)` — when overrides present, builds a fresh Agent and bypasses the Nimble→Firecrawl fallback to honour the user's chosen provider.
- `backend/api/trigger.py:trigger_crawl` — `POST /api/trigger/crawl` synchronously runs Policy Crawler with BYOK passthrough. Demo budget skipped when BYOK LLM key present.

**Verified end-to-end:**
- Server keys: real Gemini call via OpenRouter + Firecrawl scrape → CrawlVerification result in ~22s
- Fake BYOK LLM key → `401 Missing Authentication header` from OpenRouter (proves key was forwarded, not server-side error)
- Fake BYOK LLM + Scraper keys → Firecrawl fails first with the fake scraper key → graceful fallback path → demo budget unchanged

### Known limitations

- `backend/agents/impact_analysis.py` makes **zero LLM calls** (deterministic SQL evaluators only), so BYOK doesn't apply there. The `/api/trigger` endpoint only inserts an event row; Impact Analysis consumes it on its next poll cycle using the server's ClickHouse client.
- BYOK headers `provider=anthropic` raise a 400 — wire through OpenRouter with an Anthropic-capable key instead.
- The daily kill switch is in-process. For multi-instance deploys (Cloudflare Workers in front of multiple HF Spaces), promote it to a Redis or ClickHouse counter.

---

## 7. Observability (optional)

Out of the box, you have three free channels:

| Channel | Status | Where to view |
|---|---|---|
| HF Spaces container logs | Always works | `huggingface.co/spaces/<you>/regradar?logs=container` |
| structlog JSON to stderr | Always works | Same container log stream |
| In-app Agent Activity panel | Always works | React dashboard (reads `agent_state` + `agent_outputs` from ClickHouse) |

For per-LLM-call trace UI (input/output, tokens, latency), pick one:

### Logfire (recommended)

Pydantic AI's first-party trace UI. Free 10M spans/mo, 30-day retention.

1. Sign up at https://logfire.pydantic.dev
2. Create a project → copy the write token (`pylf_v1_…`)
3. HF Spaces → Secrets → add `LOGFIRE_TOKEN` = your token
4. Restart the Space
5. `backend/main.py` auto-detects the token, calls `logfire.configure()` + `logfire.instrument_pydantic_ai()` + `logfire.instrument_fastapi(app)`
6. Open https://logfire.pydantic.dev → your project → Live view

### Datadog LLM Observability (alternative)

Sponsor-grade product. 14-day free trial, paid after. Use only if you want the AI Agent Console + control-breach alerting.

1. Get a Datadog API key
2. HF Spaces secrets: set `DD_API_KEY`, `DD_LLMOBS_ENABLED=1`, `DD_LLMOBS_AGENTLESS_ENABLED=1`, `DD_LLMOBS_ML_APP=regradar`
3. Restart the Space — `ddtrace` auto-instruments `google-genai` + `pydantic-ai`
4. View at https://app.datadoghq.com/llm/traces

You can run both side-by-side. Each is a no-op if its env var is missing.

---

## 8. Backups + recovery

| What | Mechanism | Action needed |
|---|---|---|
| **ClickHouse data** | Daily auto-snapshots, 2 retained, basic tier | None — restore via Cloud console → Backups |
| **`.env` secrets** | 1Password entry "RegRadar — .env (prod)" | Update after every change |
| **Code** | GitHub `prod` branch | Already pushed |
| **HF Space code** (if using 2a) | HF git repo (mirror of GitHub) | `git push hf prod:main` after each release |
| **DO App Platform** (if using 2b) | Autodeploy on push to `prod` | Nothing — push triggers rebuild |
| **Cloudflare Pages config** | Tied to GitHub `prod` branch | Redeploys auto on push |
| **50,000 cc_accounts rows** | Deterministic regen | `python scripts/setup_cc_accounts.py` |

**Optional belt-and-suspenders**: weekly Parquet dump to a free 5 GB GCS bucket:

```sql
INSERT INTO FUNCTION gcs(
    'https://storage.googleapis.com/<your-bucket>/regradar/{_partition_id}.parquet',
    '<hmac-access-key>', '<hmac-secret>',
    'Parquet'
)
SELECT * FROM regradar.cc_accounts;
```

Schedule it via APScheduler or cron. Skip for hackathon — auto-snapshots are enough.

---

## 9. Cost ceiling math

### Hosting fixed cost

| Component | HF Spaces path | DO App Platform path |
|---|---|---|
| Backend | $0/mo (free CPU-basic) | $5/mo (512 MiB shared) |
| Frontend | $0/mo (Cloudflare Pages) | $0/mo (Cloudflare Pages) |
| Cloudflare Turnstile | $0 | $0 |
| UptimeRobot | $0 | $0 |
| ClickHouse Cloud | what you already pay | what you already pay |
| **Hosting baseline** | **$0/mo** | **$5/mo** |

With $200 DO starter credit: ~40 months runway on the DO path.

### Variable LLM cost

With Cloudflare Turnstile + SlowAPI 10/day/IP cap, paid Gemini 3.5 Flash
(~$0.0075 per Impact Analysis call):

| Scenario | Daily cost |
|---|---|
| Idle (just UptimeRobot pings) | $0 |
| 10 casual visitors, max usage | ~$0.75 |
| 100 visitors, max usage | ~$7.50 |
| Viral / abuse attempt | Capped at `DAILY_LLM_CALL_BUDGET` × $0.0075 = ~$3.75 |
| BYOK users (regardless of count) | $0 — their key, their bill |

`DAILY_LLM_CALL_BUDGET=500` is the hard kill switch — once exceeded, the
demo endpoint returns 503 until UTC midnight. No way to overrun this.

---

## Troubleshooting

**HF Space or DO App build fails on `pip install`**
Check the build log. If it's a wheel build (gcc), the Dockerfile installs
`gcc g++` — make sure the base image is `python:3.11-slim`, not `:3.11-alpine`.

**DO App Platform: backend OOM-killed mid-request**
512 MiB plan is tight when Pydantic AI + Gemini SDK both load. Symptoms:
container restarts every few minutes, logs show `SIGKILL`. Fix: upgrade
the resource to `1 GB RAM` plan ($10/mo) in App settings. Per-second billing
means you can switch back down at any time.

**DO App Platform: port misconfigured**
Logs show "Application failed to start on port 8080". Our Dockerfile reads
`$PORT` (set to 8080 by App Platform), so check the **HTTP Port** setting
in App settings — should be 8080. If you overrode it, either change it
back or set `PORT` to match in env vars.

**Frontend loads but every chart is empty**
Open browser DevTools → Network. Look for the API call. If it's hitting
`127.0.0.1:8000` instead of your HF URL, `VITE_API_URL` wasn't set at build
time — re-deploy Pages after adding it.

**CORS error in browser console**
HF backend → Secrets → add your Pages URL to `APP_CORS_ORIGINS`, then
restart the Space.

**UptimeRobot reports DOWN**
Hit `/health` manually. If it works, UR may be rate-limited by HF — try the
10-minute interval. If `/health` itself 500s, the Space crashed — check
logs at `huggingface.co/spaces/<username>/regradar?logs=container`.

**The demo trigger button does nothing**
Open DevTools → Network. If Turnstile is enabled and the token isn't
attaching, check the widget rendered (look for the Cloudflare iframe in
the DOM). If `X-CF-Turnstile-Response` header is missing, the frontend
JS provider isn't wired up.
