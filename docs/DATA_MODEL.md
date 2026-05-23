# DATA_MODEL.md

Complete ClickHouse schema documentation. Every table, every column, every constraint.

This document maps 1:1 to `backend/data/schema.sql`. If you change the schema, update both.

---

## Table of Contents

1. [Design Principles](#1-design-principles)
2. [Domain: Credit Card Accounts](#2-domain-credit-card-accounts)
3. [Regulations: reg_versions, policy_embeddings, compliance_conditions](#3-regulations-reg_versions-policy_embeddings-compliance_conditions)
4. [Triggers: policy_changes, schema_events, behavior_events](#4-triggers-policy_changes-schema_events-behavior_events)
5. [Controls: controls, compliance_scans](#5-controls-controls-compliance_scans)
6. [Agent Outputs: impact_reports, auditor_verdicts, audit_trail](#6-agent-outputs)
7. [External Publishing: published_briefs, dd_alerts, x402_fetches](#7-external-publishing)
8. [Vector Search Setup](#8-vector-search-setup)
9. [Repository Functions](#9-repository-functions)

---

## 1. Design Principles

### Single store, single source of truth

Everything lives in ClickHouse 25.8+:
- Synthetic credit card accounts (the portfolio)
- Regulation versions + chunked embeddings (vector search)
- Compliance conditions (structured extractions from regulations)
- Event tables (the 3 trigger paths)
- Control definitions + time-series scan results
- Agent outputs (Impact Analysis reports, Auditor verdicts, audit trail)
- External effect tracking (cited.md publications, Datadog alerts, x402 fetches)

No Postgres. No Redis. No separate vector DB.

### ReplacingMergeTree for mutable state

Tables that represent "current state" (`credit_card_accounts`, `reg_versions`, `controls`, `published_briefs`) use `ReplacingMergeTree(updated_at)`. Background merges deduplicate by ORDER BY key, keeping the row with the highest `updated_at`.

### MergeTree for append-only

Event streams, audit trail, time-series (`audit_trail`, `compliance_scans`, `dd_alerts`, `behavior_events`, `schema_events`) use plain `MergeTree`. Time-partitioned with `PARTITION BY toYYYYMM(...)` for fast time-range queries.

### Foreign key conventions

ClickHouse doesn't enforce FKs. We follow the convention strictly:
- `account_id` → `credit_card_accounts.account_id`
- `regulation_id` → `reg_versions.regulation_id`
- `condition_id` → `compliance_conditions.condition_id`
- `control_id` → `controls.control_id`
- `trigger_id` → joins across events + reports + verdicts + alerts

### JSON fields where flexibility matters

For evolving payloads (account attributes, event metadata, agent reasoning), we use `String DEFAULT '{}'` columns named `*_json`. The application is responsible for valid JSON.

---

## 2. Domain: Credit Card Accounts

### `credit_card_accounts`

The synthetic portfolio. ~50,000 accounts seeded.

| Column | Type | Purpose |
|---|---|---|
| `account_id` | String | Primary key |
| `customer_id` | String | Tie to a customer (synthetic) |
| `state` | LowCardinality(String) | US state code, for jurisdiction-specific rules |
| `product_type` | LowCardinality(String) | "standard", "rewards", "secured", "student" |
| `credit_limit_usd` | Float64 | |
| `balance_usd` | Float64 | Current outstanding balance |
| `apr` | Float32 | Effective APR |
| **TILA / Reg Z fields** | | |
| `promo_rate` | Nullable(Float32) | Promotional APR if active |
| `promo_rate_end_date` | Nullable(Date) | When promo expires |
| `promo_notice_sent_date` | Nullable(Date) | When 45-day notice was sent (TILA 1026.9(g)) |
| `penalty_rate_applied` | Bool | TRUE if penalty rate currently applied |
| `penalty_rate_applied_date` | Nullable(Date) | When penalty rate began |
| `penalty_rate_notice_sent_date` | Nullable(Date) | When 45-day notice was sent for penalty rate |
| **Dispute fields (TILA + FCRA)** | | |
| `dispute_filed` | Bool | TRUE if dispute currently active |
| `dispute_filed_date` | Nullable(Date) | When dispute was filed |
| `dispute_acknowledged_date` | Nullable(Date) | Issuer ack date (TILA: must be within 30 days) |
| `dispute_resolved_date` | Nullable(Date) | Issuer resolution date (TILA: within 90 days) |
| `dispute_bureau_flag` | Nullable(Bool) | FCRA: must be TRUE while dispute active |
| **FCRA / bureau reporting** | | |
| `bureau_reported` | Bool | TRUE if reporting to CRAs |
| `bureau_reported_status` | Nullable(String) | What we tell the CRA |
| `payment_status` | LowCardinality(String) | What the customer actually is |
| `original_delinquency_date` | Nullable(Date) | FCRA Section 605: 7-year clock starts here |
| `charge_off_date` | Nullable(Date) | If charged off |
| **Lifecycle** | | |
| `origination_date` | Date | When account was opened |
| `status` | LowCardinality(String) | "active", "closed", "frozen" |
| `last_payment_date` | Nullable(Date) | |
| `last_statement_date` | Nullable(Date) | |
| `applicable_policies` | Array(String) | IDs of regulations governing this account |
| `last_updated` | DateTime | Used by ReplacingMergeTree |
| `attributes_json` | String | Extensible JSON |

**Engine:** `ReplacingMergeTree(last_updated) ORDER BY (state, product_type, account_id)`

**Why this ORDER BY:** state + product_type is the most common filter (jurisdiction-specific rules). account_id provides uniqueness for replace semantics.

### Synthetic distribution

| Field | Distribution |
|---|---|
| `state` | Weighted: CA (15%), TX (10%), FL (8%), NY (8%), other 50 states evenly |
| `product_type` | standard 70%, rewards 20%, secured 5%, student 5% |
| `credit_limit_usd` | log-normal, median $5,000, max $50,000 |
| `balance_usd` | uniform 0 to 0.85 × credit_limit |
| `apr` | normal mean 21%, std 4% |
| `promo_rate` | 25% of accounts have one (active or expired) |
| `dispute_filed` | ~0.8% of accounts have an active dispute |
| `penalty_rate_applied` | ~2% have penalty rates applied |
| `original_delinquency_date` | 12% of accounts have a date; of those, ~10% are >7 years (the demo violations) |
| `bureau_reported_status` | Set on 90% of accounts; intentionally 3% mismatch payment_status (FCRA violations) |

See `seed/credit_cards/generate_accounts.py` for the exact generator. The distribution is tuned so the demo produces sensible numbers (~1,200 stale-data violations, ~1,500 accuracy mismatches, ~400 active disputes).

---

## 3. Regulations: reg_versions, policy_embeddings, compliance_conditions

### `reg_versions`

One row per (regulation_id, version_id). Updates create new rows; ReplacingMergeTree deduplicates.

| Column | Type | Purpose |
|---|---|---|
| `regulation_id` | String | Stable ID like "tila_1026_9g" |
| `version_id` | String | Content sha256 |
| `title` | String | "Notice of Change in Terms" |
| `regulator` | LowCardinality(String) | "CFPB", "FRB", "FTC", "FDIC" |
| `regulation_section` | String | "12 CFR 1026.9(g)" |
| `source_url` | String | Federal Register URL |
| `content_markdown` | String | Full text |
| `content_hash` | String | Sha256 (same as version_id) |
| `is_active` | Bool | True for current version |
| `effective_date` | Nullable(Date) | When the regulation takes effect |
| `scraped_at` | DateTime | When we last fetched it |
| `scraper_used` | LowCardinality(String) | "nimble" \| "firecrawl" |

**Engine:** `ReplacingMergeTree(scraped_at) ORDER BY (regulation_id, version_id)`

### `policy_embeddings`

The 4 policy embeddings. Each regulation gets chunked into ~3-5 embeddings.

| Column | Type | Purpose |
|---|---|---|
| `embedding_id` | String | Primary key |
| `regulation_id` | String | FK to reg_versions |
| `regulation_section` | String | Denormalized for filter speed |
| `chunk_text` | String | The text that was embedded |
| `chunk_index` | UInt32 | Order within regulation |
| `embedding` | Array(Float32) | 768-dim from text-embedding-005 |
| `created_at` | DateTime | |

**Engine:** `MergeTree ORDER BY (regulation_id, chunk_index)`

**Vector index:**
```sql
ALTER TABLE policy_embeddings
ADD INDEX embedding_hnsw_idx embedding
TYPE vector_similarity('hnsw', 'cosineDistance', 768)
GRANULARITY 1;
```

### `compliance_conditions`

The structured extractions from the Policy Crawler.

| Column | Type | Purpose |
|---|---|---|
| `condition_id` | String | Primary key |
| `regulation_id` | String | FK |
| `regulation_section` | String | Denormalized |
| `condition_kind` | LowCardinality(String) | advance_notice \| time_window \| field_match \| stale_data_limit \| dispute_flag_required |
| `field_required` | String | Column on credit_card_accounts to evaluate |
| `operator` | LowCardinality(String) | lt \| lte \| eq \| gte \| gt \| exists \| matches |
| `threshold_value` | String | Stored as string; cast at query time |
| `threshold_unit` | LowCardinality(String) | days \| years \| boolean \| string_match \| field_equality |
| `account_scope_json` | String | JSON dict specifying which accounts (e.g. {"state": ["CA"], "product_type": ["bnpl"]}) |
| `citation_text` | String | Exact quote from regulation |
| `severity` | LowCardinality(String) | LOW \| MEDIUM \| HIGH \| CRITICAL |
| `is_active` | Bool | False = superseded by newer extraction |
| `extracted_at` | DateTime | |
| `extracted_by_agent` | LowCardinality(String) | "policy_crawler" |

**Engine:** `ReplacingMergeTree(extracted_at) ORDER BY (regulation_id, condition_id)`

---

## 4. Triggers: policy_changes, schema_events, behavior_events

All three trigger tables share the same shape: append-only, time-ordered, with a `processed` flag the event poller flips after handling.

### `policy_changes`

Written by the Policy Crawler when a regulation version changes materially.

| Column | Type | Purpose |
|---|---|---|
| `trigger_id` | String | Primary key |
| `regulation_id` | String | Which regulation changed |
| `prior_version_id` | Nullable(String) | NULL for first sighting |
| `new_version_id` | String | The new content hash |
| `is_material_change` | Bool | False for clarifications |
| `change_summary` | String | Crawler's narrative |
| `detected_at` | DateTime | |
| `processed` | Bool | True once Impact Analysis has fired |
| `processed_at` | Nullable(DateTime) | |

### `schema_events`

Written by ETL / migration scripts when columns are added or populated.

| Column | Type | Purpose |
|---|---|---|
| `trigger_id` | String | Primary key |
| `event_type` | LowCardinality(String) | column_added \| column_populated \| column_dropped |
| `table_name` | String | Always "credit_card_accounts" for now |
| `column_name` | String | The affected column |
| `event_payload_json` | String | Extra metadata (rows affected, source migration) |
| `occurred_at` | DateTime | |
| `processed` | Bool | |
| `processed_at` | Nullable(DateTime) | |

### `behavior_events`

Written by application code when an account state changes in a compliance-significant way.

| Column | Type | Purpose |
|---|---|---|
| `trigger_id` | String | Primary key |
| `event_type` | LowCardinality(String) | dispute_filed \| penalty_rate_applied \| promo_rate_assigned \| charge_off \| payment_missed |
| `account_id` | String | FK to credit_card_accounts |
| `event_payload_json` | String | Event-specific metadata |
| `occurred_at` | DateTime | |
| `processed` | Bool | |
| `processed_at` | Nullable(DateTime) | |

### Polling pattern

```python
# backend/data/repositories.py
async def get_unprocessed_events(limit: int = 10) -> list[dict]:
    """Returns the next batch of unprocessed events across all 3 trigger tables, oldest first."""
    sql = """
    SELECT * FROM (
        SELECT trigger_id, 'policy_change' AS event_type, * FROM policy_changes WHERE processed = false
        UNION ALL
        SELECT trigger_id, 'schema_event' AS event_type, * FROM schema_events WHERE processed = false
        UNION ALL
        SELECT trigger_id, 'behavior_event' AS event_type, * FROM behavior_events WHERE processed = false
    )
    ORDER BY occurred_at ASC
    LIMIT {limit:UInt32}
    """
    return await ch.aquery(sql, {"limit": limit})
```

---

## 5. Controls: controls, compliance_scans

### `controls`

The 6 controls (TILA: 3, FCRA: 3). One row per control. Updated when regulation changes.

| Column | Type | Purpose |
|---|---|---|
| `control_id` | String | e.g., "CTRL-TILA-PENALTY-RATE-NOTICE" |
| `name` | String | Human-readable |
| `description` | String | What it tests |
| `related_regulation_id` | String | FK |
| `related_regulation_section` | String | Denormalized |
| `threshold_value` | Float64 | Numerical threshold (parsed from compliance_conditions) |
| `threshold_unit` | String | "days", "boolean", etc. |
| `threshold_comparison` | Enum | lt \| lte \| eq \| gte \| gt \| exists \| matches |
| `check_sql` | String | The SQL the Monitoring Agent runs (pre-built at seed time) |
| `owner_team` | String | e.g., "Bureau Reporting", "Customer Operations" |
| `test_frequency` | LowCardinality | daily \| weekly \| event_based |
| `status` | Enum | PASSING \| WARNING \| FAILING \| UNTESTED |
| `last_tested_at` | Nullable(DateTime) | |

**Engine:** `ReplacingMergeTree(updated_at) ORDER BY control_id`

### The 6 controls (locked)

| Control ID | Name | Regulation | check_sql shape |
|---|---|---|---|
| CTRL-TILA-PENALTY-RATE-NOTICE | Penalty Rate 45-Day Notice | 12 CFR 1026.9(g) | accounts where penalty_rate_applied=true AND (penalty_rate_applied_date - penalty_rate_notice_sent_date) < 45 |
| CTRL-TILA-PROMO-RATE-NOTICE | Promo Rate 45-Day Notice | 12 CFR 1026.9(g) | accounts where promo_rate_end_date - today < 45 AND promo_notice_sent_date IS NULL |
| CTRL-TILA-DISPUTE-RESOLUTION | Billing Dispute 30/90-Day | 12 CFR 1026.13 | active disputes where (today - dispute_filed_date) > 30 AND dispute_acknowledged_date IS NULL; OR > 90 AND dispute_resolved_date IS NULL |
| CTRL-FCRA-STALE-DATA | 7-Year Reporting Limit | FCRA Section 605 | bureau_reported=true AND today - original_delinquency_date > 7 years |
| CTRL-FCRA-BUREAU-ACCURACY | Bureau Status Accuracy | FCRA Section 623(a)(2) | bureau_reported=true AND bureau_reported_status != payment_status |
| CTRL-FCRA-DISPUTE-FLAG | Dispute Bureau Flag | FCRA Section 623(a)(3) | dispute_filed=true AND (dispute_bureau_flag IS NULL OR dispute_bureau_flag=false) |

Full SQL in `seed/controls.json`.

### `compliance_scans`

Time-series of every control evaluation.

| Column | Type | Purpose |
|---|---|---|
| `scan_id` | String | Primary key |
| `control_id` | String | FK |
| `scanned_at` | DateTime | |
| `scan_source` | LowCardinality | daily_monitoring \| event_driven \| manual |
| `result` | Enum | PASS \| WARN \| FAIL |
| `breach_count` | UInt32 | |
| `at_risk_count` | UInt32 | |
| `breach_balance_usd` | Float64 | |
| `total_evaluated` | UInt32 | |
| `notes` | String | |

**Engine:** `MergeTree ORDER BY (control_id, scanned_at) PARTITION BY toYYYYMM(scanned_at)`

---

## 6. Agent Outputs: impact_reports, auditor_verdicts, audit_trail

### `impact_reports`

The Impact Analysis Agent's output.

| Column | Type | Purpose |
|---|---|---|
| `trigger_id` | String | FK to the originating event |
| `source_event_type` | LowCardinality | policy_change \| schema_event \| behavior_event |
| `affected_controls_json` | String | JSON list of ControlUpdate |
| `classifications_json` | String | JSON dict[account_id, AccountClassification] |
| `total_breach_count` | UInt32 | |
| `total_at_risk_count` | UInt32 | |
| `total_balance_at_risk_usd` | Float64 | |
| `citations` | Array(String) | List of regulation_section strings |
| `suggested_remediation` | Array(String) | |
| `reasoning` | String | The agent's narrative |
| `generated_at` | DateTime | |
| `generated_by_agent` | LowCardinality | "impact_analysis" |
| `llm_model_used` | LowCardinality | "gemini-3.5-flash" |
| `llm_tokens_in` | UInt32 | |
| `llm_tokens_out` | UInt32 | |

### `auditor_verdicts`

The Auditor's verdict on an impact_report.

| Column | Type | Purpose |
|---|---|---|
| `trigger_id` | String | FK |
| `verdict` | LowCardinality | approved \| approved_with_warnings \| rejected |
| `overall_confidence` | Float32 | 0.0 - 1.0 |
| `claims_audited_json` | String | List[ClaimAudit] |
| `warnings` | Array(String) | |
| `rejection_reasons` | Array(String) | |
| `safe_to_publish` | Bool | Gate for Senso |
| `safe_to_alert` | Bool | Gate for Datadog |
| `audited_at` | DateTime | |
| `llm_model_used` | LowCardinality | "gemini-3.1-pro" (and/or "check-grounding") |

### `audit_trail`

Append-only event log of everything every agent did.

| Column | Type | Purpose |
|---|---|---|
| `audit_id` | String | Primary key |
| `trigger_id` | String | FK |
| `agent_id` | LowCardinality | |
| `event_kind` | LowCardinality | agent_started \| agent_completed \| agent_failed \| grounding_failed \| published \| alerted |
| `payload_json` | String | |
| `occurred_at` | DateTime | |

---

## 7. External Publishing: published_briefs, dd_alerts, x402_fetches

### `published_briefs`

What we shipped to cited.md via Senso.

| Column | Type | Purpose |
|---|---|---|
| `brief_id` | String | Primary key |
| `trigger_id` | String | FK |
| `slug` | String | The cited.md slug |
| `cited_md_url` | String | Public URL |
| `senso_remediate_id` | String | Senso's tracking ID |
| `title` | String | |
| `body_markdown` | String | The full published content |
| `tags` | Array(String) | |
| `related_regulation_id` | String | |
| `affected_account_count` | UInt32 | |
| `published_at` | DateTime | |
| `fetch_count` | UInt32 | Total reads (free + paid) |
| `paid_fetch_count` | UInt32 | Reads via x402 |
| `total_usdc_earned` | Float64 | |

### `dd_alerts`

Mirror of Datadog events for UI display.

| Column | Type | Purpose |
|---|---|---|
| `alert_id` | String | Primary key |
| `control_id` | String | |
| `trigger_id` | Nullable(String) | NULL for daily_monitoring source |
| `severity` | LowCardinality | info \| warning \| critical |
| `title` | String | |
| `body` | String | |
| `owner_team` | String | |
| `cited_md_url` | Nullable(String) | Link to the supporting brief |
| `source` | LowCardinality | event_driven \| daily_monitoring |
| `sent_at` | DateTime | |
| `acknowledged_at` | Nullable(DateTime) | |

### `x402_fetches`

Every successful x402 payment for a brief.

| Column | Type | Purpose |
|---|---|---|
| `fetch_id` | String | |
| `brief_id` | String | FK |
| `fetcher_wallet` | String | Buyer's address |
| `amount_usdc` | Float64 | |
| `network` | LowCardinality | "base" |
| `tx_hash` | String | Onchain settlement proof |
| `settled_at` | DateTime | |

---

## 8. Vector Search Setup

### Index creation

```sql
ALTER TABLE policy_embeddings
ADD INDEX embedding_hnsw_idx embedding
TYPE vector_similarity('hnsw', 'cosineDistance', 768)
GRANULARITY 1;
```

### Cosine similarity query

```sql
WITH [0.123, 0.456, ...]::Array(Float32) AS query_vec
SELECT
    embedding_id,
    regulation_section,
    chunk_text,
    cosineDistance(embedding, query_vec) AS dist
FROM policy_embeddings
ORDER BY dist ASC
LIMIT 5;
```

**CRITICAL:** The `::Array(Float32)` cast is required. Without it, the type system fails silently and the query returns nothing useful.

### Binary quantization (optional, for scale)

ClickHouse 25.8 added binary quantization for vector indexes. We don't need it at our scale (only 4 regulations × ~5 chunks = 20 embeddings) but production deployments would enable it via index settings.

---

## 9. Repository Functions

All ClickHouse access goes through `backend/data/repositories.py`. No raw client.query() calls elsewhere.

### Catalog (signatures only, see implementation for body)

```python
# Reads
async def get_active_conditions_for_event(event: dict) -> list[ComplianceCondition]: ...
async def get_regulation_text(regulation_section: str) -> str | None: ...
async def get_control(control_id: str) -> dict: ...
async def list_all_controls() -> list[dict]: ...
async def get_last_content_hash(source_url: str) -> str | None: ...
async def get_unprocessed_events(limit: int = 10) -> list[dict]: ...
async def query_accounts_summary(where_clause: str, params: dict) -> dict: ...
async def execute_control_check(control: dict) -> dict: ...

# Writes
async def write_reg_version(result: PolicyExtractionResult) -> None: ...
async def write_policy_change(result: PolicyExtractionResult) -> None: ...
async def write_impact_report(report: ImpactReport) -> None: ...
async def write_auditor_verdict(verdict: AuditorVerdict) -> None: ...
async def write_compliance_scan(scan: dict) -> None: ...
async def write_published_brief(brief: PublishedBrief) -> None: ...
async def write_dd_alert(alert: dict) -> None: ...
async def write_audit_trail(entry: dict) -> None: ...
async def write_schema_event(event_type: str, table: str, column: str, payload: dict) -> str: ...
async def write_behavior_event(event_type: str, account_id: str, payload: dict) -> str: ...

# Status updates
async def mark_event_processed(trigger_id: str) -> None: ...
async def mark_event_failed(trigger_id: str, reason: str) -> None: ...
```

### Why all through one module

- One place to add Datadog tracing
- One place to handle ClickHouse-specific quirks (parameter binding, vector casting)
- Easy to swap to async client globally
- Tests can mock one module instead of N

---

## AI Tool Hints

1. **Apply schema.sql first.** Run `scripts/apply_schema.py` (which executes the DDL) before any other code touches ClickHouse.

2. **Seed in this order:** regulations + chunks + embeddings → conditions → controls → accounts. The Monitoring Agent needs all 6 controls populated, including their `check_sql`, before it can run.

3. **Verify vector index built:** `SELECT * FROM system.data_skipping_indices WHERE table='policy_embeddings'` should show the HNSW index.

4. **The `applicable_policies` array on accounts is the "tag" that lets the Monitoring Agent filter quickly.** Populate it at seed time based on the account's state, product_type, and lifecycle stage.

5. **When the demo trigger fires `dispute_filed`, the test code MUST write to behavior_events**, not just update credit_card_accounts. The poller listens to behavior_events.
