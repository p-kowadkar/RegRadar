# PRIZES.md

Explicit sponsor track strategy. Every prize, every track, every "Tool Use" judging criterion -- mapped to what we built and why.

---

## The Devpost prize tracks (verified May 23, 2026)

Three explicit prize tracks with cash/credit:

| Prize | Sponsor | Value |
|---|---|---|
| Best use of Nimble's API or Web Search Agents | Nimble | $1,500 |
| Best use of ClickHouse | ClickHouse | $1,000 |
| Best use of Senso.ai | Senso | 3,000 credits |

The remaining sponsors (Datadog, Vertex AI / DeepMind, Coinbase / x402) contribute to the general **Tool Use (20%)** judging dimension. No explicit cash prize -- but using them is the difference between scoring 5/5 and 2/5 on that dimension.

---

## Judging dimensions (Devpost, equal weight 20% each)

1. **Idea** -- novelty + impact
2. **Technical execution** -- engineering quality
3. **Tool use** -- depth of sponsor integration (>=3 sponsors mandatory)
4. **Presentation** -- the 3-minute pitch
5. **Autonomy** -- the agents actually act without human prompts

We're targeting 5/5 on every dimension. Below is how each is earned.

---

## How we hit each prize / track

### Prize 1: Best use of Nimble ($1,500)

**What Nimble does for us:** Primary scraper for the Policy Crawler. Hits CFPB, FRB, FTC, Federal Register, state regulators. Returns structured regulatory text + acts as a search agent for ad-hoc compliance questions.

**Why we're not just using `requests.get()`:** Nimble repositioned in Feb 2026 as the **Web Search Agents Platform** -- AI-native search with verification + structured output. Our Policy Crawler is exactly the use case they pitched in their Series B announcement: an AI agent that searches the web in real time, validates, and feeds downstream agents structured data.

**Specifically we use:**
- `/extract` -- single URL → markdown for every regulation source
- `/search` -- ad-hoc regulatory lookup (used by Impact Analysis as a tool when it encounters ambiguous schema fields)
- `/search` with `answer=true` -- the agentic search mode, used sparingly for high-value disambiguation queries

**Demo proof:** The Policy Crawler's hourly loop visibly hits Nimble. The dashboard shows "Nimble: X credits used" -- judges see real consumption.

**Why we win this prize over the field:** Most teams will use Nimble as a glorified scraper. We use it as the front-end of a 4-agent reasoning system that publishes monetized output. The story is "Nimble found the regulation; we made it actionable, grounded, citeable, and saleable."

### Prize 2: Best use of ClickHouse ($1,000)

**What ClickHouse does for us:** Single store for everything. Credit card accounts (50K rows) + policy embeddings (vector search via HNSW) + compliance conditions + 3 event tables + impact reports + auditor verdicts + audit trail + published briefs + Datadog alerts + x402 fetches.

**We are the canonical ClickHouse 25.8 vector demo:**
- `vector_similarity('hnsw', 'cosineDistance', 768)` index -- GA in 25.8
- Binary quantization-ready (we don't enable at our scale; the architecture supports it)
- Mixed analytical + vector + time-series workloads in one engine

**Demo proof:** The Monitoring Agent runs 6 control SQL queries across 50K accounts in milliseconds. The Impact Analysis Agent does similarity search against the policy embeddings table. Judges can run `SELECT * FROM system.data_skipping_indices WHERE table='policy_embeddings'` and see the HNSW index exists.

**Why we win this prize over the field:** Most teams will use ClickHouse as "the database" -- another Postgres. We use ClickHouse's specific strengths: GA HNSW vectors (most teams will still be on pgvector), wide-column analytical scans (which is what makes the daily Monitoring Agent feasible at zero LLM cost), and ReplacingMergeTree semantics for our control-state tables. The architecture would NOT work as well on Postgres.

### Prize 3: Best use of Senso (3,000 credits)

**What Senso does for us:** Publishes our Auditor-approved compliance briefs to `cited.md/regradar/<slug>`. Other AI agents on the web can discover, retrieve, and cite our briefs.

**Why this closes the Senso prize loop:** Senso explicitly told us at signup -- "publishing to cited.md is what qualifies for the prize, not just ingestion." We do both: ingest each brief via `/content/file`, generate the public version via `/generate`, then publish.

**Specifically we use:**
- `/content/file` -- ingest the brief markdown from each Auditor-approved Impact Report
- `/generate` -- compose the cited.md page with our brief as the primary source
- `/search` -- our frontend lets users find similar past violations across all our published briefs

**Demo proof:** During the cascade, the WS stream shows the `brief_published` event. The cited.md URL appears in the UI. Judges can click it and see the real public brief.

**Why we win this prize over the field:** Most teams will either skip Senso entirely (because cited.md publishing requires a real content pipeline) or do a token ingest call. We turn Senso into the public-facing layer of a compliance product. Every approved Impact Report = one cited.md publication. By end of demo: 2-3 real public briefs at cited.md/regradar/.

**Bonus story:** Senso's ICP is community banks and credit unions. We picked Pinecrest Bank (a regional credit card issuer) as our demo entity precisely to match Senso's ICP. The story for Saroop (Senso CEO) at the after-party: "Your platform let us turn a compliance event into a citeable knowledge product in under 8 seconds."

---

## Non-prize sponsor tracks (Tool Use scoring)

### Datadog -- LLM Observability + AI Agent Console + Control Breach Alerts

**Triple-purpose integration:**

1. **LLM Obs** -- every Gemini call traced via `ddtrace>=4.8` auto-instrumentation of `google-genai` AND `pydantic-ai>=1.63`. Token counts, latencies, tool call hierarchies -- all auto-captured.
2. **AI Agent Console** (GA June 2025) -- our 3 LLM-using agents render as nodes in Datadog's agent visualizer. Inter-agent edges show the chain. This is what judges see when we tab to Datadog mid-demo.
3. **Custom Events** -- every control breach posts a Datadog Event tagged with `control_id`, `owner_team`, `severity`. Real-world alert routing.

**Demo proof:** Tab over to Datadog's AI Agent Console at ~2:30 mark. Judges see Impact Analysis → Auditor chain as nodes. Click any node, drill into the trace.

**Tool Use score impact:** Datadog hosts the event. They want to see their newest product (AI Agent Monitoring) used at depth. We do.

### Vertex AI / Google DeepMind -- Gemini + Check Grounding

**Three Vertex products:**

1. **Gemini 3.5 Flash** (GA May 19, 2026) -- the workhorse for Policy Crawler and Impact Analysis. $1.50/$9 per 1M tokens. The launch announcement said it beats 3.1 Pro on agentic benchmarks; we're a flagship example.
2. **Gemini 3.1 Pro** -- the Auditor uses this. Deeper reasoning for the LLM-as-Judge role. $2/$12 per 1M.
3. **Check Grounding API** -- the Auditor's spine. Verifies every claim against source regulation text. Returns 0-1 confidence + cited spans.
4. **gemini-embedding-001** -- top MTEB leaderboard model. 3072 dims with Matryoshka truncation to 768 for ClickHouse index efficiency.

**Demo proof:** The dashboard shows model usage per agent. Auditor verdicts include the grounding confidence scores.

**Tool Use score impact:** Vertex AI is the underlying LLM platform. We use it at depth across 4 distinct products (text gen, reasoning, embeddings, grounding) -- not just one.

### Coinbase / x402 -- Monetize the agentic web

**What:** The `/api/compliance-brief/{reg_id}` endpoint is x402-gated. Other agents pay 0.001 USDC on Base to fetch our structured brief. Coinbase's facilitator handles verification + settlement in ~200ms.

**Why this matters:** Devpost says: *"Monetize it with agent payment rails (x402, MPP, CDP, agentic.market)."* Of those four, x402 is the most mature (169M+ transactions, $50M+ volume as of April 2026, backed by AWS Bedrock AgentCore Payments). It's the obvious choice.

**Demo proof:** The closing beat shows a `curl -i` returning HTTP 402, then an `x402-curl` returning the brief after USDC settlement. Visible in the terminal.

**Tool Use score impact:** Devpost explicitly mentions x402 as a way to score on the "Autonomy" dimension. Our agents take an autonomous action (sell their output). Few teams will pull this off.

---

## The "3+ sponsors required" bar

**Mandatory minimum: 3 sponsors used.** We use **6**. Every one shows up in the demo:

| Sponsor | Demo beat | Time it appears |
|---|---|---|
| Vertex AI | Every agent run | Continuous |
| Nimble | Background (Policy Crawler) + Impact Analysis tool calls | Background + 0:40 |
| ClickHouse | Every query, dashboard backend | Continuous |
| Datadog | AI Agent Console tab-over | 2:00 |
| Senso | Brief publish to cited.md | 1:40, 2:20 |
| x402 / Coinbase | Monetization beat | 2:30-2:50 |

If judges count, we're at 2x the minimum.

---

## The Autonomy dimension (often the tiebreaker)

Devpost's wording: *"Your agent(s) need to take real action -- publish, monitor, orchestrate, transact -- grounded in real sources."*

Our autonomy beats, in order of impact:

1. **The schema_event headline demo.** Nobody clicked "scan." The agent picked up a column-populated event and surfaced 1,247 violations.
2. **The dispute_filed cross-trigger.** One event, two regulations, two control updates, one Auditor verdict, one publish, one alert -- all without a human touching anything.
3. **The publish action.** The Auditor approves → Senso publishes → cited.md URL exists. Real public artifact, real action.
4. **The Datadog alert.** Real alert routed to the Bureau Reporting team's existing tools.
5. **The x402 monetization.** Other agents transact with our agents. Real autonomous commerce.

5 distinct autonomous actions in 3 minutes.

---

## What we explicitly are NOT competing for

- **Best AI-Native UX** (if there's such a track) -- our frontend is functional, not beautiful. We bet on architecture over polish.
- **Best B2C concept** -- this is B2B compliance, not a consumer app.
- **Best use of [any sponsor not in our stack]** -- if there's a track for a sponsor we're not using (Vercel, Netlify, Hugging Face, etc.), we accept the loss. Adding a tool just for a track dilutes the architecture story.

---

## The narrative thread that ties it all together

Every prize track is part of one story:

> A regulation changes (Nimble finds it).
> Or a schema enriches (ClickHouse holds the new data).
> Or an account misbehaves (Vertex AI Gemini reasons about which controls apply).
> The Auditor (Vertex AI + Check Grounding) verifies the claim.
> Senso publishes the grounded brief to cited.md.
> Datadog routes the alert to the right team.
> x402 lets other agents pay to cite our work.

Six sponsors. One coherent product. Every integration earns its place in the architecture, not bolted on for points.

---

## If we win one prize, here's what we say at the after-party

To each sponsor's representatives:

**Nimble (Tomer / Knorovich):** "Your Series B pivot to Web Search Agents is exactly what we needed. Our Policy Crawler is the use case you described in your TechCrunch announcement -- AI agent searching, verifying, feeding downstream agents."

**ClickHouse:** "Your 25.8 vector_similarity GA + your binary quantization roadmap is what let us ditch pgvector + Pinecone. One store, one mental model, milliseconds at 50K accounts."

**Senso (Saroop):** "You publish to cited.md. We made it Auditor-approved. Every brief we ship is grounded against the source regulation. That's the trust layer the agentic web needs."

**Datadog:** "Your AI Agent Console is the only place we can see our chain end-to-end without writing custom dashboards. ddtrace 4.8 auto-instrumenting Pydantic AI tool calls -- chef's kiss."

**Coinbase:** "x402 closes the agentic-commerce loop. We monetize compliance intelligence per fetch. This is what 'AI agents transact with AI agents' looks like in production."

**Google DeepMind:** "Gemini 3.5 Flash on agentic benchmarks is real. Our Policy Crawler runs 1 LLM call per regulation change. Our Impact Analysis runs 1 LLM call per event. Cost-effective and accurate."
