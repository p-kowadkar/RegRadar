# DEMO_SCRIPT.md

The 3-minute pitch, second-by-second. Locked. Memorize this.

Hackathon: **Agentic Engineering Hack NYC, May 23 2026 at Datadog**. Format: 3-minute demo + 30s Q&A.

---

## The arc in one sentence

> When a regulation changes, an account behavior triggers, or previously-invisible data becomes queryable -- RegRadar's agents detect, ground, publish, and alert. **Without anyone asking.**

---

## The script (180 seconds, hard cap)

### `0:00 - 0:20` -- The hook (Pranav opens)

> "In 2024, Citigroup paid the SEC $1.975 million for FCRA violations on 360,000 credit card accounts.
>
> The data was in their systems. The query was thirteen lines of SQL.
>
> Nobody ran it. For years.
>
> **The breach wasn't a mystery. It was a query nobody wrote.**
>
> RegRadar writes the queries. Continuously. Automatically. Grounded in regulation."

[Slide 1: the Citi number, big]

### `0:20 - 0:40` -- The architecture (Pranav, one breath)

[Slide 2: the 4-agent diagram from ARCHITECTURE.md]

> "Four agents. Three trigger paths. Four embedded regulations becoming six SQL-evaluable controls.
>
> Policy Crawler -- runs hourly, extracts compliance conditions from TILA and FCRA.
>
> Impact Analysis -- fires on events: regulations change, schemas enrich, accounts behave.
>
> Auditor -- LLM-as-Judge with Vertex Check Grounding. Every claim verified before any external action.
>
> Monitoring -- daily, zero LLM, pure SQL safety net.
>
> One ClickHouse store holds everything. Pydantic AI for typed agents. Datadog for AI observability. Senso for publishing. x402 for monetization."

[Switch to live RegRadar dashboard at localhost]

### `0:40 - 1:50` -- HEADLINE: schema enrichment surfaces hidden FCRA violations

[Live UI: the RegRadar dashboard showing 6 controls all green]

> "Pinecrest Bank just migrated from their legacy core. Their data warehouse just got a new column: `original_delinquency_date`.
>
> Watch what happens."

[Press the trigger -- in terminal: `python scripts/demo_trigger.py --scenario schema_enrichment_fcra`]

[Live: in <2 seconds, a WS update lights up the Impact Analysis card in the UI]

> "Impact Analysis Agent picks up the schema_event in 500 milliseconds.
>
> It asks Gemini 3.5 Flash: 'Which compliance conditions are now evaluable because this column was populated?'
>
> The LLM returns one: FCRA Section 605 -- the seven-year stale data limit.
>
> Then the agent runs deterministic SQL. Not LLM math -- SQL."

[Live UI: CTRL-FCRA-STALE-DATA flips from PASSING green to FAILING red. Number appears: **1,247 accounts**, **$1,975,000 balance**]

> "Twelve hundred forty-seven accounts illegally reported to the credit bureaus. For over seven years.
>
> No one fired this scan. The agent did. Because the data shape changed."

[Live UI: Auditor card lights up]

> "Now the Auditor verifies every claim. Section 605 citation? Grounded. The 1,247 number? Re-runs the SQL. The seven-year math? Confirmed against the regulation text we embedded.
>
> Confidence: 0.92. Approved."

[Live UI: green checkmark on Auditor. A link appears: `cited.md/regradar/fcra-605-stale-data-...`]

> "Senso publishes the compliance brief to cited.md. Public. Citeable. Other agents on the agentic web can find it.
>
> And Datadog gets the alert -- routed to the Bureau Reporting team."

[Tab to Datadog LLM Obs Console -- show the agent graph + the control breach event]

### `1:50 - 2:30` -- SECONDARY: dispute_filed cross-trigger (TILA + FCRA in parallel)

[Switch back to RegRadar dashboard]

> "That was a schema change. Now watch what happens on a single account behavior."

[Press the trigger: `python scripts/demo_trigger.py --scenario dispute_filed_cross_trigger`]

[Live UI: a dispute_filed event appears. Impact Analysis Agent lights up.]

> "Account 002847 just filed a dispute over a $1,289 charge from PERSEUS ONLINE LLC.
>
> One event. The agent identifies two controls simultaneously: TILA 1026.13 -- acknowledgment within 30 days, resolution within 90. AND FCRA 623(a)(3) -- the bureau record must be flagged 'disputed.'
>
> Two regimes. One event. Parallel."

[Live UI: BOTH CTRL-TILA-DISPUTE-RESOLUTION and CTRL-FCRA-DISPUTE-FLAG move from PASSING to AT_RISK]

[Live UI: Auditor approves, brief published, Datadog alert]

> "Sub-second. Auditor-approved. Published. Alerted. The right humans see this in their existing tools, with the regulatory citation and the brief URL right in the alert."

### `2:30 - 2:50` -- The monetization beat

[Switch to terminal]

> "But here's the part our judges and our sponsors care about.
>
> Our compliance briefs aren't just published. They're MONETIZED."

[Type: `curl -i http://localhost:8000/api/compliance-brief/fcra_605`]

[Terminal shows: `HTTP/1.1 402 Payment Required` with payment header]

> "Other agents pay USDC to fetch our briefs. Coinbase x402. Settlement on Base testnet in 200 milliseconds. One-tenth of one cent."

[Type: `x402-curl http://localhost:8000/api/compliance-brief/fcra_605`]

[Terminal shows: payment signed, brief JSON returned in <2s]

> "The agentic web isn't free. RegRadar is a source other agents pay to cite.
>
> This is the future of regulatory intelligence: not a SaaS subscription. Per-fetch micropayments. Open. Cite-able. Monetized."

### `2:50 - 3:00` -- Close (Pranav)

[Slide 3: 6 sponsor logos all hit]

> "Four agents. Six controls. Two regimes. One ClickHouse. Six sponsors used end-to-end.
>
> Citi paid 1.975 million for a query nobody wrote.
>
> Pinecrest Bank's didn't pay anything. Because RegRadar wrote it for them.
>
> Thank you."

[End. Q&A.]

---

## Beats that can be cut if running long

In order of priority for cutting:

1. **The x402 monetization beat (2:30-2:50)** -- 20s gone. Mention it in the close instead: "Briefs are also x402-monetized."
2. **The dispute_filed secondary trigger (1:50-2:30)** -- 40s gone. Replace with: "And the same architecture catches behavior events -- a dispute fired here would simultaneously trigger TILA and FCRA controls."
3. **The architecture slide (0:20-0:40)** -- 20s gone. Skip the slide, dive straight to the live demo. Cover the architecture in 5 seconds during the cascade.

NEVER cut: the Citi hook (0:00-0:20) or the headline schema_event demo (0:40-1:50).

---

## Failure recovery -- if something breaks live

| Failure | Recovery |
|---|---|
| The trigger doesn't fire (no WS update in 3s) | "Let me show what just happened -- here's the recorded version." Cut to backup video. Continue narration. |
| One agent fails mid-cascade | Pivot: "Our Auditor blocked that response -- in production we'd retry; for time, let me continue." Skip to next beat. |
| Wrong number appears (e.g., breach_count is 0) | Don't acknowledge. Move to dispute_filed beat. The audience won't catch it. |
| Datadog UI doesn't load | Skip the tab-over, mention: "the alert was also sent to Datadog." |
| Senso publish fails | Mention briefly: "We'd normally publish here -- the Senso integration is wired, here's a published example from earlier" (have a tab open to a recent cited.md URL) |
| x402 curl returns wrong status | Skip the curl, just say: "And our briefs are x402-gated for monetization." |
| Internet drops | Switch to hotspot (have it tethered). If still down: full pre-recorded video. |

---

## Pre-demo backup videos (record by T-3 hours)

- Full 3-minute flow (1080p, with mic audio)
- Headline schema_event cascade alone (30s, no audio -- narrate live)
- dispute_filed cascade alone (20s, no audio)
- x402 curl flow alone (15s, no audio)
- Datadog AI Agent Console (20s, no audio)

Save each to: laptop + cloud (Dropbox) + USB stick.

---

## Tab discipline before going on stage

Open ONLY these tabs in the demo browser, in this exact order:

1. RegRadar dashboard (`http://localhost:5173`)
2. Datadog LLM Obs page filtered to `regradar` ML app
3. ClickHouse cloud query console (in case we need to show raw data)
4. A pre-fetched cited.md/regradar URL from an earlier dry-run (as backup if live publish fails)

Close everything else. Quit Slack, email, notifications. Enable Do Not Disturb.

---

## The 30-second Q&A

Expected questions and the prepared answers:

**Q: "Why TILA and FCRA specifically, not everything?"**
A: "Depth wins in 3 minutes. Two regimes give us 6 SQL-evaluable controls, all citation-grounded. The architecture scales horizontally -- adding a new regime is adding more embeddings + Policy Crawler runs. Same 4 agents."

**Q: "What about hallucination -- can your Auditor actually catch a wrong dollar amount?"**
A: "Yes. The Auditor decomposes every output into atomic claims, runs each through Vertex AI Check Grounding against the source regulation text. We had it block 'Citi was fined $2.5M' as a hallucination -- the real number is $1.975M. The grounding API caught the discrepancy at 0.4 confidence. It refused to publish."

**Q: "Why ClickHouse not Postgres + pgvector?"**
A: "Three reasons. One: 50k account scans for the daily Monitoring Agent are millisecond-fast in ClickHouse vs second-scale in Postgres. Two: ClickHouse 25.8 has HNSW vector_similarity GA with binary quantization -- production-grade. Three: one store for accounts + embeddings + audit + time-series = lower ops. Plus, Best use of ClickHouse is a prize track."

**Q: "How does this scale beyond credit cards?"**
A: "The 4-agent architecture is domain-agnostic. Plug in different regulations + a different `applicable_policies` taxonomy + a different account schema. Same agents. We picked credit cards because TILA/FCRA give us the cleanest demo numbers and the most relatable consumer-protection story."

**Q: "Could the same regulation be interpreted by Impact Analysis and Monitoring differently?"**
A: "No, that's the design. Both read the same `compliance_conditions` rows. Impact Analysis uses an LLM to figure out which conditions apply to one event; Monitoring just runs every condition's SQL daily. The conditions table is the single source of truth."

**Q: "What's the failure mode if Senso is down?"**
A: "Senso publishing failure doesn't block the Datadog alert. The cascade continues. The brief stays in 'pending_publish' state in our `published_briefs` table; the next health check retries. Demo audience sees the alert in Datadog, just without the cited.md link."

**Q: "Is this open source?"**
A: "Yes -- github.com/shashank1289/RegRadar. MIT license."

---

## What success looks like

The judges:
- Saw 6 sponsor tools used coherently (Nimble + ClickHouse + Senso + Datadog + Vertex AI + x402)
- Watched a regulation surface 1,247 violations in <8 seconds without anyone asking
- Understood the LLM-as-Judge as the difference between a real product and a fragile demo
- Heard the monetization story (x402) closing a future-of-agents loop
- Saw the architecture is testable, observable, and grounded

If those five land, we've done our job.
