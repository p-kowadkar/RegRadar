# RegRadar — Problem Statement

---

## The Problem

Financial institutions managing credit card portfolios operate under continuous, overlapping regulatory obligations. Violations are not discovered through proactive monitoring — they surface during audits, examinations, or enforcement actions, often years after the breach began. The data that would have revealed the violation existed in the institution's own systems the entire time. Nobody was watching it.

Citigroup Global Markets paid $1.975 million in 2023 for programming 360,000 retail accounts for electronic disclosure delivery without documented customer consent. The breach was a query, not a mystery.

---

## What We Are Building

An agentic compliance monitoring system that operates on credit card transaction and account data to detect TILA and FCRA violations in real time — triggered by customer behavior, data enrichment, and regulatory change.

---

## The Data

Credit card account and transaction data in ClickHouse. Synthetic dataset modelling:

- Account attributes: type, state, credit limit, balance, APR, promotional rates
- Behavioral fields: days past due, payment history, dispute status, penalty rate flags
- Bureau reporting fields: reported status, dispute flag, delinquency date, charge-off status
- Policy tags: `applicable_policies[]` array linking each account to the regulations that govern it

---

## The Regulatory Scope

**Six controls across two federal regulations.**

### TILA — Truth in Lending Act / Regulation Z

**Penalty Rate Notice and Promo Rate Expiry**
Both require 45-day advance written notice before a rate change takes effect. Structurally identical. One policy embedding (Reg Z 1026.9(g)) covers both controls. Lowest implementation cost for the coverage.

**Billing Dispute Resolution**
When a dispute is filed, a 30-day acknowledgement clock and a 90-day resolution clock start simultaneously. This control is cross-regulation — the same behavioral event (`dispute_filed = true`) also triggers an FCRA bureau flagging obligation. One event, two compliance checks, evaluated in parallel.

### FCRA — Fair Credit Reporting Act

**7-Year Stale Data**
Negative information cannot be reported to bureaus after 7 years from the original delinquency date. Single threshold, pure date arithmetic, one-sentence regulatory text. The highest-impact schema enrichment story — when `original_delinquency_date` is backfilled from a data migration, violations that have persisted for years surface immediately.

**Bureau Accuracy**
Reported bureau status must match the account's actual payment status. Cannot be evaluated until bureau-side fields exist in the schema. Schema enrichment trigger.

**Dispute Bureau Flag**
While a dispute is under investigation, the account must be flagged as disputed in all bureau reports. Fires on the same `dispute_filed` event as the TILA billing dispute control.

---

## Three Trigger Paths

**Immediate behavior triggers → Impact Analysis Agent**
- `dispute_filed = true` — starts TILA investigation clocks and FCRA bureau flag obligation simultaneously
- `penalty_rate_applied = true` — starts 45-day notice clock immediately
- Cannot wait for a daily scan. Compliance clock begins at the moment the event fires.

**Schema change → Impact Analysis Agent**
- `original_delinquency_date` populated — bulk scan surfaces stale bureau reporting violations
- `bureau_reported_status` field added — accuracy mismatches become visible
- `promo_notice_sent_date` field added — promotional accounts without notice become queryable
- Trigger mechanism: `schema_events` table in ClickHouse. No CDC, no Kafka.

**Daily scan → Monitoring Agent → all six controls**
- Safety net for all controls regardless of event triggers
- Handles time-based controls with no discrete event: promo dates approaching, delinquency buckets accumulating, 7-year thresholds crossing
- Zero LLM calls. Entirely deterministic SQL.

---

## Three Agents

**Policy Crawler** — scheduled hourly
Monitors regulatory sources via Nimble. Chunks and embeds policy text via DeepMind. Extracts structured compliance conditions from regulatory language (one LLM call per new or updated regulation). Detects policy version changes and writes to `policy_changes` table to trigger the Impact Analysis Agent. After writing structured conditions to ClickHouse the LLM is done until the regulation changes again.

**Monitoring Agent** — scheduled daily
Executes compliance check queries against all accounts tagged with active policies. Counts breaches. Stores time-series results in `compliance_scans`. Fires Datadog alerts on threshold breach. Zero LLM calls. Runs at scale and frequency without meaningful API cost.

**Impact Analysis Agent** — event-driven
Fires on three event types: policy version change, schema enrichment, immediate behavior trigger. Makes one LLM call per event to classify what changed, map a new schema field to relevant policies, or resolve ambiguous account scoping. All downstream execution after that call is deterministic SQL. Writes impact report, updates audit trail, triggers Datadog.

---

## Where LLM Reasoning Is Applied

The system applies non-deterministic reasoning at exactly four points — all at the boundary between unstructured regulatory text and structured schema:

1. **Policy text → compliance condition** — extracting field names, operators, thresholds, and account scope from raw regulation text
2. **Policy diff → material change** — determining whether a regulation update changes a threshold, expands scope, or is a minor clarification
3. **Schema field → policy relevance** — mapping a new or newly-populated field to the policies it affects
4. **Ambiguous account scoping** — resolving accounts that sit in regulatory grey areas (pre-effective-date accounts, partial documentation, bankruptcy status)

Everything else is deterministic. Compliance decisions are never made by an embedding similarity score — only by SQL conditions derived from extracted regulatory text.

---

## Embedding Architecture

Four policy embeddings cover all six controls:

| Embedding | Regulatory text | Controls covered |
|---|---|---|
| Reg Z 1026.9(g) | 45-day notice requirement | Penalty Rate Notice + Promo Rate Expiry |
| Reg Z 1026.13 | Billing error resolution | Billing Dispute |
| FCRA Section 605 | 7-year reporting limit | 7-Year Stale Data |
| FCRA Section 623(a) | Furnisher accuracy + dispute obligations | Bureau Accuracy + Dispute Flag |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Regulatory ingestion | Nimble |
| Data store | ClickHouse — portfolio data, embeddings, controls, audit trail |
| Embedding generation | DeepMind text-embedding-004 |
| Agent reasoning | DeepMind gemini-2.5-flash — function calling |
| Monitoring and alerting | Datadog |
| Deployment target | Senso — financial institutions |
