# DATA_MODEL.md

Complete ClickHouse schema for RegRadar. Every table, every column, every constraint.

ClickHouse handles **all five domains**:
1. Knowledge graph (relational)
2. Regulatory text + embeddings (vector search)
3. Synthetic portfolios (analytical queries)
4. Governance controls (config + time-series test results)
5. Audit trail (append-only)

No Pinecone. No ChromaDB. No Postgres.

---

## 0. Setup Convention

All tables live in the `regradar` database. Create via:

```sql
CREATE DATABASE IF NOT EXISTS regradar;
USE regradar;
```

ClickHouse version: `25.x` (Cloud) or `clickhouse-server:latest` Docker.

All timestamps are `DateTime64(3)` (millisecond precision, UTC).
All UUIDs are stored as `String` (not `UUID` type) for portability.
All money amounts in **USD as Float64**.

---

## 1. Knowledge Graph -- `kg_nodes`

```sql
CREATE TABLE regradar.kg_nodes (
    node_id            String,
    node_type          Enum8(
        'data_object'        = 1,
        'regulation'         = 2,
        'article'            = 3,
        'obligation'         = 4,
        'jurisdiction'       = 5,
        'regulator'          = 6,
        'product'            = 7,
        'customer_segment'   = 8,
        'portfolio_position' = 9
    ),
    name               String,
    metadata           String CODEC(ZSTD(3)),    -- JSON blob
    embedding          Array(Float32),            -- 768-dim (Gemini)
    source_url         String DEFAULT '',
    created_at         DateTime64(3),
    updated_at         DateTime64(3),
    version            UInt32 DEFAULT 1,
    is_deleted         UInt8 DEFAULT 0
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (node_type, node_id);
```

### Indexes

```sql
-- Vector search index (HNSW)
ALTER TABLE regradar.kg_nodes
ADD INDEX embedding_idx embedding
TYPE vector_similarity('hnsw', 'cosineDistance', 768) GRANULARITY 1;

-- Lookup by name
ALTER TABLE regradar.kg_nodes
ADD INDEX name_idx name TYPE bloom_filter() GRANULARITY 1;
```

### Sample Rows

```sql
INSERT INTO regradar.kg_nodes (node_id, node_type, name, metadata, embedding, source_url, created_at, updated_at) VALUES
('customer_pii', 'data_object',
 'Customer Personally Identifiable Information',
 '{"fields":["name","address","dob","email","phone"],"sensitivity":"high"}',
 [/* 768 floats */], '',
 now64(3), now64(3)),

('cftc_margin_rule_2026', 'regulation',
 'CFTC Margin Requirements for Uncleared Swaps (2026 Amendment)',
 '{"regulator":"CFTC","effective_date":"2026-07-21"}',
 [/* 768 floats */],
 'https://www.cftc.gov/...',
 now64(3), now64(3));
```

---

## 2. Knowledge Graph -- `kg_edges`

```sql
CREATE TABLE regradar.kg_edges (
    edge_id            String,
    source_id          String,
    target_id          String,
    edge_type          Enum8(
        'applies_to'        = 1,
        'requires'          = 2,
        'exempts'           = 3,
        'cross_references'  = 4,
        'supersedes'        = 5,
        'amends'            = 6,
        'collects'          = 7,
        'processes'         = 8,
        'stores'            = 9,
        'classified_as'     = 10,
        'operates_in'       = 11,
        'serves'            = 12
    ),
    confidence         Float32,                  -- 0.0 - 1.0
    reasoning          String CODEC(ZSTD(3)),
    metadata           String DEFAULT '{}' CODEC(ZSTD(3)),
    created_by         String,                   -- agent_id or 'seed'
    created_at         DateTime64(3),
    version            UInt32 DEFAULT 1,
    is_deleted         UInt8 DEFAULT 0
)
ENGINE = ReplacingMergeTree(version)
ORDER BY (source_id, target_id, edge_type);
```

### Common Queries

```sql
-- Which regulations apply to customer_pii?
SELECT n.name, e.confidence
FROM kg_edges e
JOIN kg_nodes n ON n.node_id = e.target_id
WHERE e.source_id = 'customer_pii'
  AND e.edge_type = 'applies_to'
  AND e.is_deleted = 0
ORDER BY e.confidence DESC;

-- Which data objects are affected by CFTC margin rule?
SELECT n.name, e.confidence
FROM kg_edges e
JOIN kg_nodes n ON n.node_id = e.source_id
WHERE e.target_id = 'cftc_margin_rule_2026'
  AND e.edge_type = 'applies_to'
  AND e.is_deleted = 0;

-- Multi-hop: data_object -> regulation -> obligation
WITH first_hop AS (
    SELECT target_id AS reg_id FROM kg_edges
    WHERE source_id = 'transaction_records'
      AND edge_type = 'applies_to'
)
SELECT o.name AS obligation, fh.reg_id
FROM kg_edges e
JOIN kg_nodes o ON o.node_id = e.target_id
JOIN first_hop fh ON fh.reg_id = e.source_id
WHERE e.edge_type = 'requires';
```

---

## 3. Regulatory Documents -- `reg_versions`

Versioned regulatory text. Diff history of every regulation ever scraped.

```sql
CREATE TABLE regradar.reg_versions (
    version_id         String,                   -- UUID
    regulation_id      String,                   -- stable across versions
    source_url         String,
    source_name        String,                   -- e.g. "sec_edgar"
    fetched_at         DateTime64(3),
    published_at       Nullable(DateTime64(3)),
    title              String,
    text               String CODEC(ZSTD(3)),
    text_hash          String,                   -- SHA256
    embedding          Array(Float32),           -- 768-dim
    diff_from_previous String DEFAULT '' CODEC(ZSTD(3)),
    metadata           String DEFAULT '{}' CODEC(ZSTD(3)),
    change_type        Enum8(
        'new_regulation' = 1,
        'reg_amended'    = 2
    ) DEFAULT 'new_regulation',
    is_latest          UInt8 DEFAULT 1
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(fetched_at)
ORDER BY (regulation_id, fetched_at);
```

### Indexes

```sql
ALTER TABLE regradar.reg_versions
ADD INDEX reg_embedding_idx embedding
TYPE vector_similarity('hnsw', 'cosineDistance', 768) GRANULARITY 1;
```

### Common Queries

```sql
-- Latest version of a regulation
SELECT * FROM reg_versions
WHERE regulation_id = 'cftc_margin_rule'
  AND is_latest = 1
LIMIT 1;

-- All versions of a regulation (for diff view)
SELECT version_id, fetched_at, text_hash, change_type
FROM reg_versions
WHERE regulation_id = 'sec_17a4'
ORDER BY fetched_at DESC;

-- Semantic search across all regs
SELECT regulation_id, title,
       cosineDistance(embedding, [/* query embedding */]) AS dist
FROM reg_versions
WHERE is_latest = 1
ORDER BY dist ASC
LIMIT 10;
```

---

## 4. Derivatives Portfolio -- `derivatives_portfolio`

```sql
CREATE TABLE regradar.derivatives_portfolio (
    instrument_id      String,                   -- UUID
    instrument_type    Enum8(
        'IR_SWAP'      = 1,
        'CDS'          = 2,
        'FX_FORWARD'   = 3,
        'OPTION'       = 4
    ),
    notional_usd       Float64,
    market_value_usd   Float64,
    margin_posted_usd  Float64,
    margin_ratio       Float32,                  -- margin_posted / notional
    counterparty       String,
    counterparty_rating String,                  -- "AAA", "BB", etc.
    cleared            UInt8,                    -- 0 = uncleared, 1 = cleared
    clearinghouse      Nullable(String),
    jurisdiction       String,                   -- "us_federal", "eu", etc.
    trade_date         Date,
    maturity_date      Date,
    status             Enum8(
        'active'   = 1,
        'closed'   = 2,
        'pending'  = 3
    ) DEFAULT 'active',
    fx_pair            Nullable(String),         -- only for FX_FORWARD
    underlying         Nullable(String),         -- for OPTION
    strike_usd         Nullable(Float64),
    option_type        Nullable(String),         -- "call" / "put"
    created_at         DateTime64(3),
    updated_at         DateTime64(3)
)
ENGINE = MergeTree()
ORDER BY (instrument_type, cleared, instrument_id);
```

### Common Queries

```sql
-- Find all IR swaps below new margin threshold
SELECT instrument_id, notional_usd, margin_ratio, counterparty
FROM derivatives_portfolio
WHERE instrument_type = 'IR_SWAP'
  AND cleared = 0
  AND margin_ratio < 0.08
  AND status = 'active'
ORDER BY notional_usd DESC;

-- Classify positions
SELECT
    countIf(margin_ratio < 0.08) AS breach,
    countIf(margin_ratio >= 0.08 AND margin_ratio < 0.096) AS at_risk,
    countIf(margin_ratio >= 0.096) AS monitoring
FROM derivatives_portfolio
WHERE instrument_type = 'IR_SWAP' AND cleared = 0 AND status = 'active';

-- Total exposure by counterparty
SELECT counterparty, sum(notional_usd) AS total_notional
FROM derivatives_portfolio
WHERE status = 'active'
GROUP BY counterparty
ORDER BY total_notional DESC;
```

### Synthetic Data Distribution

When generating ~3,000 positions:

| Field | Distribution |
|---|---|
| `instrument_type` | 67% IR_SWAP, 13% CDS, 17% FX_FORWARD, 3% OPTION |
| `notional_usd` | log-normal: μ=14 (≈$1.2M), σ=2 |
| `margin_ratio` | normal: μ=0.075, σ=0.025, clamped [0.01, 0.30] |
| `counterparty` | sample from 50 counterparty pool |
| `cleared` | 30% cleared, 70% uncleared |
| `jurisdiction` | 80% us_federal, 15% eu, 5% uk |
| `trade_date` | uniform between 2024-01-01 and today |
| `maturity_date` | trade_date + 1-7 years |

---

## 5. Bonds Portfolio -- `bonds_portfolio`

```sql
CREATE TABLE regradar.bonds_portfolio (
    position_id        String,
    cusip              String,                   -- 9-char CUSIP
    issuer             String,
    bond_type          Enum8(
        'corporate' = 1,
        'municipal' = 2,
        'treasury'  = 3,
        'agency'    = 4
    ),
    par_value_usd      Float64,
    market_value_usd   Float64,
    purchase_price_usd Float64,
    coupon_rate        Float32,                  -- annual %
    payment_frequency  Enum8(
        'monthly'      = 1,
        'quarterly'    = 2,
        'semi_annual'  = 3,
        'annual'       = 4
    ),
    credit_rating      String,                   -- "AAA", "AA+", etc.
    jurisdiction       String,                   -- "us_federal", "us_state_ca"
    tax_exempt         UInt8,                    -- 1 if muni tax-exempt
    issue_date         Date,
    maturity_date      Date,
    status             Enum8('held'=1, 'sold'=2) DEFAULT 'held',
    created_at         DateTime64(3),
    updated_at         DateTime64(3)
)
ENGINE = MergeTree()
ORDER BY (bond_type, position_id);
```

### Synthetic Distribution

For ~1,500 positions:
- 47% corporate, 27% municipal, 17% treasury, 9% agency
- `par_value_usd`: log-normal μ=14, σ=1.5
- `coupon_rate`: normal μ=4.5%, σ=1.5%, clamped [0.5%, 12%]
- `credit_rating`: weighted -- AAA 15%, AA 25%, A 30%, BBB 20%, BB 7%, B/CCC 3%

---

## 6. Lending / BNPL Portfolio -- `lending_portfolio`

```sql
CREATE TABLE regradar.lending_portfolio (
    account_id         String,
    customer_id        String,
    product_type       Enum8(
        'BNPL'           = 1,
        'PERSONAL_LOAN'  = 2,
        'AUTO_LOAN'      = 3
    ),
    principal_usd      Float64,
    outstanding_usd    Float64,
    apr                Float32,
    term_months        UInt16,
    payments_made      UInt16,
    status             Enum8(
        'active'         = 1,
        'paid_off'       = 2,
        'delinquent'     = 3,
        'charged_off'    = 4
    ) DEFAULT 'active',
    origination_date   Date,
    state              String,                   -- 2-char state code
    disclosure_version String,                   -- e.g. "v3"
    last_payment_date  Nullable(Date),
    next_payment_date  Nullable(Date),
    created_at         DateTime64(3),
    updated_at         DateTime64(3)
)
ENGINE = MergeTree()
ORDER BY (product_type, state, account_id);
```

### Synthetic Distribution

For ~50,000 accounts:
- 70% BNPL, 25% personal loan, 5% auto loan
- `principal_usd`: log-normal μ=6.5 ($665), σ=1.5
- `state`: weighted by US population (CA 12%, TX 9%, FL 7%, NY 6%, ...)
- `disclosure_version`: 60% v3, 30% v2, 10% v1 (intentional staleness for demo)
- `status`: 85% active, 8% paid_off, 5% delinquent, 2% charged_off

### Common Queries

```sql
-- Count California BNPL accounts on stale disclosure
SELECT count() FROM lending_portfolio
WHERE product_type = 'BNPL'
  AND state = 'CA'
  AND disclosure_version != 'v3'
  AND status = 'active';
```

---

## 7. Governance Controls -- `controls`

```sql
CREATE TABLE regradar.controls (
    control_id         String,                   -- "CTRL-001"
    name               String,
    description        String,
    regulation_ids     Array(String),            -- linked regs
    metric             String,                   -- "initial_margin", "incident_sla_hours"
    threshold_value    Float64,
    threshold_operator Enum8(
        'gte'  = 1,    -- >=
        'gt'   = 2,    -- >
        'lte'  = 3,    -- <=
        'lt'   = 4,    -- <
        'eq'   = 5,    -- ==
        'neq'  = 6     -- !=
    ),
    threshold_unit     String,                   -- "percent_notional", "hours"
    test_sql           String CODEC(ZSTD(3)),    -- the SQL test query
    owner_team         String,                   -- "risk_team", "compliance_team"
    test_frequency     Enum8(
        'realtime' = 1,
        'hourly'   = 2,
        'daily'    = 3,
        'weekly'   = 4,
        'monthly'  = 5
    ),
    current_status     Enum8(
        'PASSING'        = 1,
        'AT_RISK'        = 2,
        'FAILING'        = 3,
        'NOT_APPLICABLE' = 4,
        'PENDING_RETEST' = 5
    ) DEFAULT 'PENDING_RETEST',
    last_tested_at     Nullable(DateTime64(3)),
    last_passing_at    Nullable(DateTime64(3)),
    created_at         DateTime64(3),
    updated_at         DateTime64(3),
    version            UInt32 DEFAULT 1
)
ENGINE = ReplacingMergeTree(version)
ORDER BY control_id;
```

### Sample Row (CTRL-001 after CFTC amendment)

```sql
INSERT INTO regradar.controls VALUES (
    'CTRL-001',
    'IM Adequacy on Uncleared IR Swaps',
    'Initial margin must be >= 8% of notional on uncleared interest rate swaps',
    ['cftc_margin_rule_2026'],
    'initial_margin',
    0.08,                                     -- was 0.06
    'gte',
    'percent_notional',
    $$SELECT count() FROM derivatives_portfolio
      WHERE instrument_type='IR_SWAP' AND cleared=0
        AND margin_ratio < 0.08 AND status='active'$$,
    'risk_team',
    'daily',
    'FAILING',
    now64(3),
    null,
    now64(3),
    now64(3),
    2                                          -- bumped from v1
);
```

---

## 8. Control Test Results (Time Series) -- `control_test_results`

Every control test run goes here. Used for trends, dashboards.

```sql
CREATE TABLE regradar.control_test_results (
    test_id            String,
    control_id         String,
    tested_at          DateTime64(3),
    status             Enum8(
        'PASSING'        = 1,
        'AT_RISK'        = 2,
        'FAILING'        = 3,
        'NOT_APPLICABLE' = 4,
        'ERROR'          = 5
    ),
    result_metric_value Float64,               -- raw count or value
    breach_count       UInt32 DEFAULT 0,
    at_risk_count      UInt32 DEFAULT 0,
    sample_breach_ids  Array(String) DEFAULT [],
    notes              String DEFAULT '',
    execution_time_ms  UInt32
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(tested_at)
ORDER BY (control_id, tested_at);
```

### Common Queries

```sql
-- Most recent status of each control
SELECT control_id,
       argMax(status, tested_at) AS latest_status,
       argMax(breach_count, tested_at) AS latest_breaches,
       max(tested_at) AS as_of
FROM control_test_results
GROUP BY control_id;

-- Trend of CTRL-001 over last 30 days
SELECT toDate(tested_at) AS day,
       avg(breach_count) AS avg_breaches
FROM control_test_results
WHERE control_id = 'CTRL-001'
  AND tested_at > now() - INTERVAL 30 DAY
GROUP BY day
ORDER BY day;
```

---

## 9. Audit Trail -- `audit_trail`

Append-only log of every agent action.

```sql
CREATE TABLE regradar.audit_trail (
    event_id           String,                   -- UUID
    task_id            String,                   -- ties to blackboard
    event_type         Enum8(
        'agent_claim_created'       = 1,
        'agent_claim_silent'        = 2,
        'agent_executed'            = 3,
        'agent_failed'              = 4,
        'control_updated'           = 5,
        'control_tested'            = 6,
        'kg_edge_added'             = 7,
        'kg_edge_removed'           = 8,
        'datadog_alert_sent'        = 9,
        'luminai_workflow_triggered' = 10,
        'luminai_workflow_completed' = 11,
        'auditor_approved'          = 12,
        'auditor_rejected'          = 13,
        'regulation_ingested'       = 14
    ),
    agent_id           String DEFAULT '',
    trigger_type       String DEFAULT '',
    payload            String CODEC(ZSTD(3)),    -- full JSON of event
    user_id            String DEFAULT '',
    occurred_at        DateTime64(3),
    duration_ms        Nullable(UInt32)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (occurred_at, task_id);
```

---

## 10. Company Profile -- `company_profile`

There's exactly ONE row for the demo (NovaPay), but the schema supports multi-tenant.

```sql
CREATE TABLE regradar.company_profile (
    company_id         String,
    name               String,
    type               String,
    annual_volume_usd  Float64,
    employee_count     UInt32,
    headquarters       String,
    founded            UInt16,
    sponsor_bank       Nullable(String),
    services           Array(String),
    data_objects       Array(String),
    states_operating_in Array(String),
    customer_segments  Array(String),
    current_policies   String,                   -- JSON
    created_at         DateTime64(3),
    updated_at         DateTime64(3),
    version            UInt32 DEFAULT 1
)
ENGINE = ReplacingMergeTree(version)
ORDER BY company_id;
```

---

## 11. The "Mega Query" -- Cross-Domain JOIN

This is the demo flex. One query touches 5 tables, returns sub-second.

```sql
-- "Show every IR swap below new margin threshold, with the
--  triggering regulation, affected control, and recent audit events."

SELECT
    d.instrument_id,
    d.counterparty,
    d.notional_usd,
    d.margin_ratio,
    r.title AS regulation,
    c.control_id,
    c.current_status,
    a.event_count
FROM derivatives_portfolio d
CROSS JOIN (
    SELECT regulation_id, title
    FROM reg_versions
    WHERE is_latest = 1
      AND regulation_id = 'cftc_margin_rule'
) r
JOIN controls c ON has(c.regulation_ids, r.regulation_id)
LEFT JOIN (
    SELECT task_id, count() AS event_count
    FROM audit_trail
    WHERE occurred_at > now() - INTERVAL 1 HOUR
    GROUP BY task_id
) a ON 1=1
WHERE d.instrument_type = 'IR_SWAP'
  AND d.cleared = 0
  AND d.status = 'active'
  AND d.margin_ratio < 0.08
  AND c.control_id = 'CTRL-001'
ORDER BY d.notional_usd DESC
LIMIT 50;
```

Run this in front of judges. Sub-second across 5 tables.

---

## 12. Setup Script

`scripts/setup_clickhouse.py` creates all tables idempotently:

```python
# scripts/setup_clickhouse.py
"""
Create all RegRadar tables. Idempotent -- safe to re-run.
"""
import clickhouse_connect
import os
from pathlib import Path

SCHEMAS_DIR = Path(__file__).parent / "schemas"

def main():
    client = clickhouse_connect.get_client(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.environ.get("CLICKHOUSE_PORT", 8443)),
        username=os.environ["CLICKHOUSE_USER"],
        password=os.environ["CLICKHOUSE_PASSWORD"],
        secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
    )
    client.command("CREATE DATABASE IF NOT EXISTS regradar")
    
    for sql_file in sorted(SCHEMAS_DIR.glob("*.sql")):
        ddl = sql_file.read_text()
        for statement in ddl.split(";"):
            statement = statement.strip()
            if statement:
                client.command(statement)
        print(f"  ✓ Applied {sql_file.name}")
    
    print("\nAll tables ready.")

if __name__ == "__main__":
    main()
```

Schema files (in `scripts/schemas/`):
- `01_kg_nodes.sql`
- `02_kg_edges.sql`
- `03_reg_versions.sql`
- `04_derivatives_portfolio.sql`
- `05_bonds_portfolio.sql`
- `06_lending_portfolio.sql`
- `07_controls.sql`
- `08_control_test_results.sql`
- `09_audit_trail.sql`
- `10_company_profile.sql`

---

## 13. Repository Pattern

All ClickHouse access goes through repository classes. **No raw SQL in agents or routes.**

```python
# backend/data/kg_repo.py
import clickhouse_connect
from backend.data.schema import KGNode, KGEdge

class KGRepository:
    def __init__(self, client):
        self.client = client

    async def find_applicable_regulations(
        self, data_object_id: str
    ) -> list[KGNode]:
        """All regs that apply to this data object."""
        query = """
        SELECT n.* FROM regradar.kg_edges e
        JOIN regradar.kg_nodes n ON n.node_id = e.target_id
        WHERE e.source_id = {data_object_id:String}
          AND e.edge_type = 'applies_to'
          AND e.is_deleted = 0
        ORDER BY e.confidence DESC
        """
        result = await self.client.query(
            query, parameters={"data_object_id": data_object_id}
        )
        return [KGNode(**row) for row in result.result_rows]

    async def find_candidates(
        self, topics: list[str], jurisdictions: list[str], regulators: list[str]
    ) -> list[KGNode]:
        """Pre-filter likely-affected data objects for Mapper."""
        ...

    async def add_edge(self, edge: KGEdge) -> str:
        """Insert new edge, return edge_id."""
        ...

    async def multi_hop_traverse(
        self, start_node: str, max_hops: int,
        edge_types_filter: list[str] | None = None
    ) -> list[dict]:
        ...

    async def get_stats(self) -> dict:
        """For dashboard KPI cards."""
        return {
            "nodes_total": ...,
            "edges_total": ...,
            "by_type": ...,
        }
```

Similar repos:
- `backend/data/portfolio_repo.py` -- derivatives, bonds, lending
- `backend/data/controls_repo.py` -- controls + test results
- `backend/data/reg_repo.py` -- reg_versions
- `backend/data/audit_repo.py` -- audit_trail

---

## 14. Indexing & Performance Notes

- ClickHouse `ReplacingMergeTree` is used for any table that has updates (controls, kg_nodes, kg_edges, company_profile)
- All other tables are `MergeTree` (append-only)
- Partition by month for time-series tables (audit_trail, control_test_results, reg_versions)
- HNSW vector indexes on embeddings
- Bloom filter on `name` columns for fast lookups

**Sub-second query target** for all dashboard reads. If a query exceeds 500ms, profile + add index.

---

Read [API.md](API.md) next for the FastAPI endpoint spec.
