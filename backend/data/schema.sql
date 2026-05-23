-- ════════════════════════════════════════════════════════════════
-- RegRadar -- ClickHouse Schema
--
-- Apply with:  python scripts/apply_schema.py
-- Or:          clickhouse-client --multiquery < backend/data/schema.sql
--
-- See docs/DATA_MODEL.md for column-by-column documentation.
-- ════════════════════════════════════════════════════════════════

CREATE DATABASE IF NOT EXISTS regradar;
USE regradar;


-- ─── Company / Tenant ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS company_profile (
    company_id         String,
    name               String,
    company_type       String,
    annual_volume_usd  Float64,
    employee_count     UInt32,
    headquarters       String,
    founded_year       UInt16,
    sponsor_bank       String,
    services           Array(String),
    customer_jurisdictions Array(String),
    profile_json       String,                       -- full JSON
    created_at         DateTime DEFAULT now(),
    updated_at         DateTime DEFAULT now(),
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY company_id;


-- ─── Regulations ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS reg_versions (
    reg_id             String,
    version_id         String,                       -- sha256 of content
    title              String,
    regulator          String,                       -- SEC, CFTC, FINRA, OCC, etc.
    jurisdiction       String,                       -- us_federal, ny_state, eu, etc.
    topics             Array(String),                -- ["margin", "swaps"]
    severity           Enum('LOW' = 1, 'MEDIUM' = 2, 'HIGH' = 3, 'CRITICAL' = 4),
    effective_date     Date,
    deadline_date      Nullable(Date),
    source_url         String,
    content_markdown   String,
    content_hash       String,                       -- sha256
    embedding          Array(Float32),               -- 768-dim
    scraped_at         DateTime,
    scraper_used       LowCardinality(String),       -- nimble, firecrawl
    classification_json String,                      -- classifier output cache
    created_at         DateTime DEFAULT now(),
)
ENGINE = ReplacingMergeTree(scraped_at)
ORDER BY (regulator, jurisdiction, reg_id, version_id);


-- ─── Knowledge Graph ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS kg_nodes (
    node_id            String,
    node_type          LowCardinality(String),       -- regulation, regulator, jurisdiction, data_object, control
    label              String,                       -- human-readable
    attributes_json    String,                       -- flexible attributes
    embedding          Array(Float32),               -- 768-dim, for similarity search
    created_at         DateTime DEFAULT now(),
    updated_at         DateTime DEFAULT now(),
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (node_type, node_id);


CREATE TABLE IF NOT EXISTS kg_edges (
    edge_id            String,
    source_node_id     String,
    target_node_id     String,
    edge_type          LowCardinality(String),       -- GOVERNS, APPLIES_TO, REQUIRES, CONFLICTS_WITH, etc.
    confidence         Float32,                      -- 0.0 - 1.0
    evidence_json      String,                       -- supporting citations
    created_by_agent   LowCardinality(String),       -- mapper, manual, etc.
    created_at         DateTime DEFAULT now(),
)
ENGINE = MergeTree()
ORDER BY (source_node_id, target_node_id, edge_type);


-- ─── Portfolios ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS derivatives_portfolio (
    position_id        String,
    instrument_type    LowCardinality(String),       -- IRS, CDS, FRA, FX_swap, etc.
    notional_usd       Float64,
    counterparty       String,
    counterparty_jurisdiction String,
    booking_jurisdiction String,
    trade_date         Date,
    maturity_date      Date,
    is_cleared         Bool,
    initial_margin_pct Float32,                      -- e.g. 0.06 for 6%
    attributes_json    String,
    created_at         DateTime DEFAULT now(),
)
ENGINE = MergeTree()
ORDER BY (instrument_type, booking_jurisdiction, position_id);


CREATE TABLE IF NOT EXISTS bonds_portfolio (
    position_id        String,
    bond_type          LowCardinality(String),       -- treasury, corporate, muni, sovereign
    issuer             String,
    cusip              String,
    par_value_usd      Float64,
    coupon_rate        Float32,
    maturity_date      Date,
    credit_rating      LowCardinality(String),       -- AAA, AA, A, BBB, BB, etc.
    is_callable        Bool,
    attributes_json    String,
    created_at         DateTime DEFAULT now(),
)
ENGINE = MergeTree()
ORDER BY (bond_type, position_id);


CREATE TABLE IF NOT EXISTS lending_portfolio (
    account_id         String,
    product_type       LowCardinality(String),       -- bnpl, personal_loan, credit_card
    customer_id        String,
    customer_jurisdiction String,
    principal_usd      Float64,
    interest_rate      Float32,
    origination_date   Date,
    term_months        UInt16,
    status             LowCardinality(String),       -- current, delinquent_30, delinquent_60, charged_off
    customer_fico      UInt16,
    attributes_json    String,
    created_at         DateTime DEFAULT now(),
)
ENGINE = MergeTree()
ORDER BY (product_type, customer_jurisdiction, account_id);


-- ─── Governance Controls ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS controls (
    control_id         String,                       -- CTRL-001 through CTRL-008
    name               String,
    description        String,
    related_regulation_id String,
    threshold_value    Float64,
    threshold_unit     String,                       -- e.g. "pct", "usd", "days"
    threshold_comparison Enum('lt' = 1, 'lte' = 2, 'eq' = 3, 'gte' = 4, 'gt' = 5),
    owner_team         String,
    test_frequency     LowCardinality(String),       -- daily, weekly, monthly
    status             Enum('PASSING' = 1, 'WARNING' = 2, 'FAILING' = 3, 'UNTESTED' = 4),
    last_tested_at     DateTime,
    attributes_json    String,
    created_at         DateTime DEFAULT now(),
    updated_at         DateTime DEFAULT now(),
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY control_id;


CREATE TABLE IF NOT EXISTS control_test_results (
    test_id            String,
    control_id         String,
    tested_at          DateTime,
    result             Enum('PASS' = 1, 'WARN' = 2, 'FAIL' = 3),
    observed_value     Float64,
    threshold_value    Float64,
    breach_position_count UInt32,
    breach_notional_usd Float64,
    notes              String,
)
ENGINE = MergeTree()
ORDER BY (control_id, tested_at)
PARTITION BY toYYYYMM(tested_at);


-- ─── Agent Activity / Audit Trail ─────────────────────────────

CREATE TABLE IF NOT EXISTS agent_outputs (
    trigger_id         String,
    agent_id           LowCardinality(String),
    response_type      LowCardinality(String),       -- primary, supporting, cross_talk
    relevance_score    Float32,
    started_at         DateTime,
    completed_at       DateTime,
    duration_ms        UInt32,
    payload_json       String,
    error              String,
    auditor_verdict    LowCardinality(String),       -- approved, approved_with_warnings, rejected
    auditor_notes      String,
    created_at         DateTime DEFAULT now(),
)
ENGINE = MergeTree()
ORDER BY (trigger_id, started_at, agent_id)
PARTITION BY toYYYYMM(started_at);


CREATE TABLE IF NOT EXISTS triggers (
    trigger_id         String,
    trigger_type       LowCardinality(String),
    payload_json       String,
    created_at         DateTime DEFAULT now(),
    completed_at       Nullable(DateTime),
    state              LowCardinality(String),       -- received, in_progress, completed, failed
)
ENGINE = ReplacingMergeTree(created_at)
ORDER BY trigger_id;


-- ─── Action / Workflow Execution ──────────────────────────────

CREATE TABLE IF NOT EXISTS actions (
    action_id          String,
    trigger_id         String,
    action_type        LowCardinality(String),       -- update_control, file_sar, send_notification, etc.
    target             String,                       -- e.g. CTRL-001
    status             LowCardinality(String),       -- pending, in_progress, completed, failed
    luminai_execution_id Nullable(String),
    sop_json           String,
    result_json        String,
    requested_at       DateTime,
    completed_at       Nullable(DateTime),
)
ENGINE = ReplacingMergeTree(requested_at)
ORDER BY action_id;


-- ─── Datadog Alerts (mirror for UI display) ───────────────────

CREATE TABLE IF NOT EXISTS dd_alerts (
    alert_id           String,
    control_id         String,
    severity           LowCardinality(String),       -- info, warning, critical
    title              String,
    body               String,
    owner_team         String,
    sent_at            DateTime,
    acknowledged_at    Nullable(DateTime),
)
ENGINE = MergeTree()
ORDER BY (sent_at, alert_id)
PARTITION BY toYYYYMM(sent_at);


-- ─── Indexes for vector search ────────────────────────────────
-- ClickHouse 24.10+ supports approximate vector indexes (USearch backend)

ALTER TABLE kg_nodes
ADD INDEX IF NOT EXISTS embedding_idx embedding
TYPE vector_similarity('hnsw', 'cosineDistance', 768);

ALTER TABLE reg_versions
ADD INDEX IF NOT EXISTS embedding_idx embedding
TYPE vector_similarity('hnsw', 'cosineDistance', 768);


-- ─── Done ─────────────────────────────────────────────────────
-- Verify with:  SELECT name FROM system.tables WHERE database='regradar';
