-- ════════════════════════════════════════════════════════════════
-- RegRadar — ClickHouse Schema (credit card / TILA / FCRA domain)
--
-- Apply with: python scripts/apply_schema.py
-- Or:         clickhouse-client --multiquery < backend/data/schema.sql
--
-- See docs/DATA_MODEL.md for column-by-column documentation.
-- ════════════════════════════════════════════════════════════════

CREATE DATABASE IF NOT EXISTS regradar;
USE regradar;


-- ─── Credit Card Accounts (synthetic portfolio) ──────────────────

CREATE TABLE IF NOT EXISTS credit_card_accounts (
    account_id              String,
    customer_id             String,
    state                   LowCardinality(String),          -- US state code
    product_type            LowCardinality(String),          -- "standard", "rewards", "secured", "student"
    credit_limit_usd        Float64,
    balance_usd             Float64,
    apr                     Float32,                          -- effective APR

    -- TILA / Reg Z fields
    promo_rate              Nullable(Float32),                -- promotional APR if active
    promo_rate_end_date     Nullable(Date),
    promo_notice_sent_date  Nullable(Date),                   -- when 45-day notice was sent
    penalty_rate_applied    Bool DEFAULT false,
    penalty_rate_applied_date Nullable(Date),
    penalty_rate_notice_sent_date Nullable(Date),

    -- Billing dispute fields (TILA + FCRA)
    dispute_filed           Bool DEFAULT false,
    dispute_filed_date      Nullable(Date),
    dispute_acknowledged_date Nullable(Date),
    dispute_resolved_date   Nullable(Date),
    dispute_bureau_flag     Nullable(Bool),                   -- FCRA: must be true while dispute active

    -- FCRA / bureau reporting fields
    bureau_reported         Bool DEFAULT false,
    bureau_reported_status  Nullable(String),                 -- "current", "30dpd", "60dpd", "90dpd", "charged_off"
    payment_status          LowCardinality(String),           -- actual status: "current", "30dpd", etc.
    original_delinquency_date Nullable(Date),                 -- when current negative reporting began
    charge_off_date         Nullable(Date),

    -- Lifecycle
    origination_date        Date,
    status                  LowCardinality(String),           -- "active", "closed", "frozen"
    last_payment_date       Nullable(Date),
    last_statement_date     Nullable(Date),

    -- Audit
    applicable_policies     Array(String) DEFAULT [],         -- IDs of regulations governing this account
    last_updated            DateTime DEFAULT now(),
    attributes_json         String DEFAULT '{}',
)
ENGINE = ReplacingMergeTree(last_updated)
ORDER BY (state, product_type, account_id);


-- ─── Regulations: Versions and Policy Embeddings ─────────────────

CREATE TABLE IF NOT EXISTS reg_versions (
    regulation_id           String,                           -- e.g., "tila_1026_9g", "fcra_605"
    version_id              String,                           -- content sha256
    title                   String,
    regulator               LowCardinality(String),           -- "CFPB", "FRB", "FDIC", "FTC", "CFR"
    regulation_section      String,                           -- "12 CFR 1026.9(g)" or "FCRA Section 605"
    source_url              String,
    content_markdown        String,
    content_hash            String,
    is_active               Bool DEFAULT true,
    effective_date          Nullable(Date),
    scraped_at              DateTime,
    scraper_used            LowCardinality(String),           -- "nimble" | "firecrawl"
    created_at              DateTime DEFAULT now(),
)
ENGINE = ReplacingMergeTree(scraped_at)
ORDER BY (regulation_id, version_id);


CREATE TABLE IF NOT EXISTS policy_embeddings (
    embedding_id            String,
    regulation_id           String,
    regulation_section      String,
    chunk_text              String,
    chunk_index             UInt32,
    embedding               Array(Float32),                   -- 768-dim from text-embedding-005
    created_at              DateTime DEFAULT now(),
)
ENGINE = MergeTree()
ORDER BY (regulation_id, chunk_index);

-- HNSW index (ClickHouse 25.8+ vector search GA)
ALTER TABLE policy_embeddings
ADD INDEX IF NOT EXISTS embedding_hnsw_idx embedding
TYPE vector_similarity('hnsw', 'cosineDistance', 768)
GRANULARITY 1;


CREATE TABLE IF NOT EXISTS compliance_conditions (
    condition_id            String,
    regulation_id           String,
    regulation_section      String,
    condition_kind          LowCardinality(String),           -- advance_notice | time_window | field_match | stale_data_limit | dispute_flag_required
    field_required          String,                           -- column on credit_card_accounts
    operator                LowCardinality(String),           -- lt | lte | eq | gte | gt | exists | matches
    threshold_value         String,                           -- stored as string; parsed by operator+unit
    threshold_unit          LowCardinality(String),           -- days | years | boolean | string_match | field_equality
    account_scope_json      String DEFAULT '{}',
    citation_text           String,
    severity                LowCardinality(String),           -- LOW | MEDIUM | HIGH | CRITICAL
    is_active               Bool DEFAULT true,
    extracted_at            DateTime DEFAULT now(),
    extracted_by_agent      LowCardinality(String) DEFAULT 'policy_crawler',
)
ENGINE = ReplacingMergeTree(extracted_at)
ORDER BY (regulation_id, condition_id);


-- ─── Triggers (the three paths) ──────────────────────────────────

CREATE TABLE IF NOT EXISTS policy_changes (
    trigger_id              String,
    regulation_id           String,
    prior_version_id        Nullable(String),
    new_version_id          String,
    is_material_change      Bool,
    change_summary          String,
    detected_at             DateTime DEFAULT now(),
    processed               Bool DEFAULT false,
    processed_at            Nullable(DateTime),
)
ENGINE = ReplacingMergeTree(detected_at)
ORDER BY (detected_at, trigger_id);


CREATE TABLE IF NOT EXISTS schema_events (
    trigger_id              String,
    event_type              LowCardinality(String),           -- column_added | column_populated | column_dropped
    table_name              String,
    column_name             String,
    event_payload_json      String DEFAULT '{}',
    occurred_at             DateTime,
    processed               Bool DEFAULT false,
    processed_at            Nullable(DateTime),
)
ENGINE = ReplacingMergeTree(occurred_at)
ORDER BY (occurred_at, trigger_id);


CREATE TABLE IF NOT EXISTS behavior_events (
    trigger_id              String,
    event_type              LowCardinality(String),           -- dispute_filed | penalty_rate_applied | promo_rate_assigned | charge_off | payment_missed
    account_id              String,
    event_payload_json      String DEFAULT '{}',
    occurred_at             DateTime,
    processed               Bool DEFAULT false,
    processed_at            Nullable(DateTime),
)
ENGINE = ReplacingMergeTree(occurred_at)
ORDER BY (occurred_at, trigger_id);


-- ─── Governance Controls (6 controls) ────────────────────────────

CREATE TABLE IF NOT EXISTS controls (
    control_id              String,                           -- e.g., "CTRL-TILA-PENALTY-RATE-NOTICE"
    name                    String,
    description             String,
    related_regulation_id   String,
    related_regulation_section String,
    threshold_value         Float64,
    threshold_unit          String,                           -- days | years | boolean | fraction
    threshold_comparison    Enum('lt'=1, 'lte'=2, 'eq'=3, 'gte'=4, 'gt'=5, 'exists'=6, 'matches'=7),
    check_sql               String,                           -- the SQL the Monitoring Agent runs
    owner_team              String,
    test_frequency          LowCardinality(String),           -- daily | weekly | event_based
    status                  Enum('PASSING'=1, 'WARNING'=2, 'FAILING'=3, 'UNTESTED'=4),
    last_tested_at          Nullable(DateTime),
    created_at              DateTime DEFAULT now(),
    updated_at              DateTime DEFAULT now(),
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY control_id;


CREATE TABLE IF NOT EXISTS compliance_scans (
    scan_id                 String,
    control_id              String,
    scanned_at              DateTime,
    scan_source             LowCardinality(String),           -- daily_monitoring | event_driven | manual
    result                  Enum('PASS'=1, 'WARN'=2, 'FAIL'=3),
    breach_count            UInt32,
    at_risk_count           UInt32,
    breach_balance_usd      Float64,
    total_evaluated         UInt32,
    notes                   String DEFAULT '',
)
ENGINE = MergeTree()
ORDER BY (control_id, scanned_at)
PARTITION BY toYYYYMM(scanned_at);


-- ─── Agent Outputs / Audit Trail ─────────────────────────────────

CREATE TABLE IF NOT EXISTS impact_reports (
    trigger_id              String,
    source_event_type       LowCardinality(String),
    affected_controls_json  String,                           -- list[ControlUpdate]
    classifications_json    String,                           -- dict[account_id, AccountClassification]
    total_breach_count      UInt32,
    total_at_risk_count     UInt32,
    total_balance_at_risk_usd Float64,
    citations               Array(String),
    suggested_remediation   Array(String),
    reasoning               String,
    generated_at            DateTime,
    generated_by_agent      LowCardinality(String) DEFAULT 'impact_analysis',
    llm_model_used          LowCardinality(String),
    llm_tokens_in           UInt32,
    llm_tokens_out          UInt32,
)
ENGINE = ReplacingMergeTree(generated_at)
ORDER BY (generated_at, trigger_id);


CREATE TABLE IF NOT EXISTS auditor_verdicts (
    trigger_id              String,
    verdict                 LowCardinality(String),           -- approved | approved_with_warnings | rejected
    overall_confidence      Float32,
    claims_audited_json     String,                           -- list[ClaimAudit]
    warnings                Array(String),
    rejection_reasons       Array(String),
    safe_to_publish         Bool,
    safe_to_alert           Bool,
    audited_at              DateTime,
    audited_by_agent        LowCardinality(String) DEFAULT 'auditor',
    llm_model_used          LowCardinality(String),
)
ENGINE = ReplacingMergeTree(audited_at)
ORDER BY (audited_at, trigger_id);


CREATE TABLE IF NOT EXISTS audit_trail (
    audit_id                String,
    trigger_id              String,
    agent_id                LowCardinality(String),
    event_kind              LowCardinality(String),           -- agent_started | agent_completed | agent_failed | grounding_failed | published | alerted
    payload_json            String,
    occurred_at             DateTime DEFAULT now(),
)
ENGINE = MergeTree()
ORDER BY (occurred_at, trigger_id, agent_id)
PARTITION BY toYYYYMM(occurred_at);


-- ─── Senso cited.md publication tracking ──────────────────────────

CREATE TABLE IF NOT EXISTS published_briefs (
    brief_id                String,
    trigger_id              String,
    slug                    String,
    cited_md_url            String,
    senso_remediate_id      String,
    title                   String,
    body_markdown           String,
    tags                    Array(String),
    related_regulation_id   String,
    affected_account_count  UInt32,
    published_at            DateTime,
    fetch_count             UInt32 DEFAULT 0,
    paid_fetch_count        UInt32 DEFAULT 0,                 -- via x402
    total_usdc_earned       Float64 DEFAULT 0.0,
)
ENGINE = ReplacingMergeTree(published_at)
ORDER BY published_at;


-- ─── Datadog alert tracking ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS dd_alerts (
    alert_id                String,
    control_id              String,
    trigger_id              Nullable(String),
    severity                LowCardinality(String),           -- info | warning | critical
    title                   String,
    body                    String,
    owner_team              String,
    cited_md_url            Nullable(String),
    source                  LowCardinality(String),           -- event_driven | daily_monitoring
    sent_at                 DateTime,
    acknowledged_at         Nullable(DateTime),
)
ENGINE = MergeTree()
ORDER BY (sent_at, alert_id)
PARTITION BY toYYYYMM(sent_at);


-- ─── x402 payment tracking ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS x402_fetches (
    fetch_id                String,
    brief_id                String,
    fetcher_wallet          String,                           -- buyer's onchain address
    amount_usdc             Float64,
    network                 LowCardinality(String) DEFAULT 'base',
    tx_hash                 String,
    settled_at              DateTime,
)
ENGINE = MergeTree()
ORDER BY (settled_at, fetch_id)
PARTITION BY toYYYYMM(settled_at);


-- ─── Done. Verify with:
-- SELECT name FROM system.tables WHERE database='regradar';
