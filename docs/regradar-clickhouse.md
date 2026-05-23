# RegRadar — ClickHouse Schema Reference

Database: `regradar`  
Schema file: [`backend/data/schema.sql`](../backend/data/schema.sql)  
Apply with: `python scripts/apply_schema.py`  
Full column docs: [`docs/DATA_MODEL.md`](DATA_MODEL.md)

---

## Tables Overview

| Table | Engine | Purpose |
|---|---|---|
| `company_profile` | ReplacingMergeTree | Tenant configuration |
| `reg_versions` | ReplacingMergeTree | Regulatory content + embeddings |
| `kg_nodes` | ReplacingMergeTree | Knowledge graph nodes |
| `kg_edges` | MergeTree | Knowledge graph edges |
| `derivatives_portfolio` | MergeTree | OTC derivatives positions |
| `bonds_portfolio` | MergeTree | Fixed income positions |
| `lending_portfolio` | MergeTree | Consumer lending accounts |
| `controls` | ReplacingMergeTree | Governance controls |
| `control_test_results` | MergeTree (partitioned) | Control test audit log |
| `agent_outputs` | MergeTree (partitioned) | Agent execution audit log |
| `triggers` | ReplacingMergeTree | Workflow trigger events |
| `actions` | ReplacingMergeTree | Workflow action executions |
| `dd_alerts` | MergeTree (partitioned) | Datadog alert mirror |

---

## Company / Tenant

### `company_profile`
Stores one record per fintech tenant. Re-upserts deduplicate on `updated_at`.

| Column | Type | Notes |
|---|---|---|
| `company_id` | String | Primary key |
| `name` | String | |
| `company_type` | String | e.g. fintech, broker-dealer |
| `annual_volume_usd` | Float64 | |
| `employee_count` | UInt32 | |
| `headquarters` | String | |
| `founded_year` | UInt16 | |
| `sponsor_bank` | String | |
| `services` | Array(String) | |
| `customer_jurisdictions` | Array(String) | |
| `profile_json` | String | Full JSON blob |
| `created_at` | DateTime | |
| `updated_at` | DateTime | ReplacingMergeTree version key |

**Engine:** `ReplacingMergeTree(updated_at)` — `ORDER BY company_id`

---

## Regulations

### `reg_versions`
Core regulatory content store. Each row is a unique version of a regulation, keyed by `(reg_id, version_id)` where `version_id` is the sha256 of the content. Carries the full markdown text and a 768-dim embedding for semantic search.

| Column | Type | Notes |
|---|---|---|
| `reg_id` | String | Stable regulation identifier |
| `version_id` | String | sha256 of content |
| `title` | String | |
| `regulator` | String | SEC, CFTC, FINRA, OCC, etc. |
| `jurisdiction` | String | us_federal, ny_state, eu, etc. |
| `topics` | Array(String) | e.g. ["margin", "swaps"] |
| `severity` | Enum | LOW / MEDIUM / HIGH / CRITICAL |
| `effective_date` | Date | |
| `deadline_date` | Nullable(Date) | |
| `source_url` | String | |
| `content_markdown` | String | Full regulation text |
| `content_hash` | String | sha256 |
| `embedding` | Array(Float32) | 768-dim vector |
| `scraped_at` | DateTime | ReplacingMergeTree version key |
| `scraper_used` | LowCardinality(String) | nimble, firecrawl |
| `classification_json` | String | Classifier output cache |
| `created_at` | DateTime | |

**Engine:** `ReplacingMergeTree(scraped_at)` — `ORDER BY (regulator, jurisdiction, reg_id, version_id)`  
**Vector index:** HNSW cosine distance, 768-dim on `embedding`

---

## Knowledge Graph

### `kg_nodes`
Nodes in the regulatory knowledge graph. Node types include `regulation`, `regulator`, `jurisdiction`, `data_object`, and `control`. Each node carries a 768-dim embedding for similarity search.

| Column | Type | Notes |
|---|---|---|
| `node_id` | String | |
| `node_type` | LowCardinality(String) | regulation, regulator, jurisdiction, data_object, control |
| `label` | String | Human-readable display name |
| `attributes_json` | String | Flexible node attributes |
| `embedding` | Array(Float32) | 768-dim vector |
| `created_at` | DateTime | |
| `updated_at` | DateTime | ReplacingMergeTree version key |

**Engine:** `ReplacingMergeTree(updated_at)` — `ORDER BY (node_type, node_id)`  
**Vector index:** HNSW cosine distance, 768-dim on `embedding`

---

### `kg_edges`
Directed edges between knowledge graph nodes. Edge types include `GOVERNS`, `APPLIES_TO`, `REQUIRES`, and `CONFLICTS_WITH`. Includes a confidence score and supporting evidence.

| Column | Type | Notes |
|---|---|---|
| `edge_id` | String | |
| `source_node_id` | String | FK → kg_nodes.node_id |
| `target_node_id` | String | FK → kg_nodes.node_id |
| `edge_type` | LowCardinality(String) | GOVERNS, APPLIES_TO, REQUIRES, CONFLICTS_WITH, etc. |
| `confidence` | Float32 | 0.0 – 1.0 |
| `evidence_json` | String | Supporting citations |
| `created_by_agent` | LowCardinality(String) | mapper, manual, etc. |
| `created_at` | DateTime | |

**Engine:** `MergeTree()` — `ORDER BY (source_node_id, target_node_id, edge_type)`

---

## Portfolios

### `derivatives_portfolio`
OTC derivatives positions across instrument types.

| Column | Type | Notes |
|---|---|---|
| `position_id` | String | |
| `instrument_type` | LowCardinality(String) | IRS, CDS, FRA, FX_swap, etc. |
| `notional_usd` | Float64 | |
| `counterparty` | String | |
| `counterparty_jurisdiction` | String | |
| `booking_jurisdiction` | String | |
| `trade_date` | Date | |
| `maturity_date` | Date | |
| `is_cleared` | Bool | |
| `initial_margin_pct` | Float32 | e.g. 0.06 for 6% |
| `attributes_json` | String | |
| `created_at` | DateTime | |

**Engine:** `MergeTree()` — `ORDER BY (instrument_type, booking_jurisdiction, position_id)`

---

### `bonds_portfolio`
Fixed income positions with credit metadata.

| Column | Type | Notes |
|---|---|---|
| `position_id` | String | |
| `bond_type` | LowCardinality(String) | treasury, corporate, muni, sovereign |
| `issuer` | String | |
| `cusip` | String | |
| `par_value_usd` | Float64 | |
| `coupon_rate` | Float32 | |
| `maturity_date` | Date | |
| `credit_rating` | LowCardinality(String) | AAA, AA, A, BBB, BB, etc. |
| `is_callable` | Bool | |
| `attributes_json` | String | |
| `created_at` | DateTime | |

**Engine:** `MergeTree()` — `ORDER BY (bond_type, position_id)`

---

### `lending_portfolio`
Consumer lending accounts including BNPL, personal loans, and credit cards.

| Column | Type | Notes |
|---|---|---|
| `account_id` | String | |
| `product_type` | LowCardinality(String) | bnpl, personal_loan, credit_card |
| `customer_id` | String | |
| `customer_jurisdiction` | String | |
| `principal_usd` | Float64 | |
| `interest_rate` | Float32 | |
| `origination_date` | Date | |
| `term_months` | UInt16 | |
| `status` | LowCardinality(String) | current, delinquent_30, delinquent_60, charged_off |
| `customer_fico` | UInt16 | |
| `attributes_json` | String | |
| `created_at` | DateTime | |

**Engine:** `MergeTree()` — `ORDER BY (product_type, customer_jurisdiction, account_id)`

---

## Governance Controls

### `controls`
The 8 compliance controls (CTRL-001 through CTRL-008). Each defines a threshold rule with an owner team and test cadence.

| Column | Type | Notes |
|---|---|---|
| `control_id` | String | CTRL-001 through CTRL-008 |
| `name` | String | |
| `description` | String | |
| `related_regulation_id` | String | FK → reg_versions.reg_id |
| `threshold_value` | Float64 | |
| `threshold_unit` | String | pct, usd, days |
| `threshold_comparison` | Enum | lt / lte / eq / gte / gt |
| `owner_team` | String | |
| `test_frequency` | LowCardinality(String) | daily, weekly, monthly |
| `status` | Enum | PASSING / WARNING / FAILING / UNTESTED |
| `last_tested_at` | DateTime | |
| `attributes_json` | String | |
| `created_at` | DateTime | |
| `updated_at` | DateTime | ReplacingMergeTree version key |

**Engine:** `ReplacingMergeTree(updated_at)` — `ORDER BY control_id`

---

### `control_test_results`
Immutable audit log of every control test run. Records observed vs. threshold values, breach counts, and breach notional.

| Column | Type | Notes |
|---|---|---|
| `test_id` | String | |
| `control_id` | String | FK → controls.control_id |
| `tested_at` | DateTime | Partition key |
| `result` | Enum | PASS / WARN / FAIL |
| `observed_value` | Float64 | |
| `threshold_value` | Float64 | |
| `breach_position_count` | UInt32 | |
| `breach_notional_usd` | Float64 | |
| `notes` | String | |

**Engine:** `MergeTree()` — `ORDER BY (control_id, tested_at)` — `PARTITION BY toYYYYMM(tested_at)`

---

## Agent Activity / Audit Trail

### `triggers`
Incoming events that initiate agent workflows (e.g., new regulation detected, scheduled scan).

| Column | Type | Notes |
|---|---|---|
| `trigger_id` | String | |
| `trigger_type` | LowCardinality(String) | |
| `payload_json` | String | |
| `created_at` | DateTime | ReplacingMergeTree version key |
| `completed_at` | Nullable(DateTime) | |
| `state` | LowCardinality(String) | received, in_progress, completed, failed |

**Engine:** `ReplacingMergeTree(created_at)` — `ORDER BY trigger_id`

---

### `agent_outputs`
Log of every agent execution. Tied to a `trigger_id`, stores the full response payload, timing, error info, and auditor verdict.

| Column | Type | Notes |
|---|---|---|
| `trigger_id` | String | FK → triggers.trigger_id |
| `agent_id` | LowCardinality(String) | |
| `response_type` | LowCardinality(String) | primary, supporting, cross_talk |
| `relevance_score` | Float32 | |
| `started_at` | DateTime | Partition key |
| `completed_at` | DateTime | |
| `duration_ms` | UInt32 | |
| `payload_json` | String | Full agent response |
| `error` | String | |
| `auditor_verdict` | LowCardinality(String) | approved, approved_with_warnings, rejected |
| `auditor_notes` | String | |
| `created_at` | DateTime | |

**Engine:** `MergeTree()` — `ORDER BY (trigger_id, started_at, agent_id)` — `PARTITION BY toYYYYMM(started_at)`

---

### `actions`
Workflow actions spawned from triggers (e.g., `update_control`, `file_sar`, `send_notification`). Optionally links to an external LuminAI execution.

| Column | Type | Notes |
|---|---|---|
| `action_id` | String | |
| `trigger_id` | String | FK → triggers.trigger_id |
| `action_type` | LowCardinality(String) | update_control, file_sar, send_notification, etc. |
| `target` | String | e.g. CTRL-001 |
| `status` | LowCardinality(String) | pending, in_progress, completed, failed |
| `luminai_execution_id` | Nullable(String) | External workflow ID |
| `sop_json` | String | Standard operating procedure used |
| `result_json` | String | |
| `requested_at` | DateTime | ReplacingMergeTree version key |
| `completed_at` | Nullable(DateTime) | |

**Engine:** `ReplacingMergeTree(requested_at)` — `ORDER BY action_id`

---

## Monitoring

### `dd_alerts`
Mirror of Datadog alerts for UI display. Tied to a `control_id` with severity and acknowledgement tracking.

| Column | Type | Notes |
|---|---|---|
| `alert_id` | String | |
| `control_id` | String | FK → controls.control_id |
| `severity` | LowCardinality(String) | info, warning, critical |
| `title` | String | |
| `body` | String | |
| `owner_team` | String | |
| `sent_at` | DateTime | Partition key |
| `acknowledged_at` | Nullable(DateTime) | |

**Engine:** `MergeTree()` — `ORDER BY (sent_at, alert_id)` — `PARTITION BY toYYYYMM(sent_at)`

---

## Design Notes

**`ReplacingMergeTree`** is used for mutable entities (company profile, regulation versions, controls, triggers, actions) so upserts naturally deduplicate on the version key column.

**`MergeTree` with monthly partitions** is used for append-only audit logs (control test results, agent outputs, Datadog alerts) to keep queries fast as data grows.

**Vector similarity indexes** (HNSW backend, cosine distance, 768-dim) are applied to `reg_versions.embedding` and `kg_nodes.embedding` for semantic search. Requires ClickHouse 24.10+.

**`LowCardinality`** is applied to enum-like string columns (instrument type, bond type, scraper name, etc.) to reduce storage and improve filter performance.
