# RegRadar — System Design
### 3-Agent Architecture · Case 2 Scope: SEC Reg BI Form CRS Consent Violation

---

## The Real-World Anchor

The SEC fined Citigroup Global Markets $1.975 million in September 2023 for programming approximately 360,000 retail accounts for electronic disclosure delivery and Form CRS without documented customer consent. The breach existed entirely in queryable account data. RegRadar runs continuous compliance monitoring against exactly this class of violation — both for known existing regulations and for policy changes as they happen.

---

## Three Agents

| Agent | Trigger | Responsibility |
|---|---|---|
| Policy Crawler | Scheduled — every hour | Scrape policies via Nimble, chunk, embed, store in ClickHouse, detect version changes |
| Monitoring Agent | Scheduled — every 24 hours | Scan assets tagged with active policies, run compliance checks, store results, alert on breach |
| Impact Analysis Agent | Event-driven — policy change in ClickHouse | Diff old vs new policy, query tagged assets, quantify newly non-compliant delta, generate impact report |

The key architectural concept tying all three together: **asset tagging**. Every row in retail_accounts carries an `applicable_policies` array. Agents 2 and 3 both filter by this tag — they never scan assets blind. The Policy Crawler is responsible for keeping policy definitions current. The other two agents consume them.

---

## Agent 1 — Policy Crawler

**Trigger:** Scheduler — runs every hour

**What it does:**
Polls Nimble for new or updated regulatory documents across configured sources (SEC, CFPB, FINRA). For each document it chunks the text, generates embeddings via the DeepMind embedding API, and stores them in ClickHouse. It then extracts structured policy metadata and upserts the policies table. If it detects a version change against the prior stored version, it writes an event to policy_changes — which triggers Agent 3.

**DeepMind API call:**
```python
# One call per chunk — embedding only
response = genai.embed_content(
    model="models/text-embedding-004",
    content=chunk_text,
    task_type="retrieval_document"
)
embedding = response['embedding']   # Array(Float32), 768 dimensions
```

**Tools:**
- `scrape_policy_source(url)` — Nimble
- `chunk_and_embed(text)` — splits text, calls embedding API per chunk
- `upsert_policy(policy_metadata)` — writes to ClickHouse policies table
- `detect_version_change(policy_id, new_text)` — compares embedding similarity against prior version
- `log_policy_change(change_event)` — writes to policy_changes, triggering Agent 3

**Writes to ClickHouse:** regulatory_documents, policies, policy_changes

---

## Agent 2 — Monitoring Agent

**Trigger:** Scheduler — runs every 24 hours (or configurable per policy)

**What it does:**
Reads active policies from ClickHouse. For each policy, queries retail_accounts filtered by `applicable_policies` tag. Constructs and runs the compliance check query against those assets. Stores the scan result in compliance_scans as a time-series entry. If breach count exceeds the policy threshold, fires a Datadog alert.

**DeepMind API call:**
```python
# Function calling — constructs the compliance query from policy definition
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    tools=monitoring_tools
)

prompt = f"""
Policy: {policy_definition}
Compliance condition: {policy.compliance_conditions}

Query the retail_accounts table for assets tagged with this policy.
Return breach count, breakdown by state, and severity classification.
"""
```

**Tools:**
- `get_active_policies()` — reads policies table
- `get_tagged_assets(policy_id)` — queries retail_accounts WHERE has(applicable_policies, policy_id)
- `run_compliance_check(policy_id, conditions)` — executes parameterised ClickHouse query
- `store_scan_result(result)` — writes to compliance_scans
- `trigger_datadog_alert(breach_summary)` — fires if breach_count > threshold

**Core ClickHouse query:**
```sql
SELECT
    state,
    COUNT(*)              AS breach_count,
    SUM(COUNT(*)) OVER () AS total_breach
FROM retail_accounts
WHERE has(applicable_policies, 'SEC-REG-BI')
  AND delivery_method  = 'electronic'
  AND consent_obtained = false
  AND active           = true
GROUP BY state
ORDER BY breach_count DESC
```

**Writes to ClickHouse:** compliance_scans, audit_trail

---

## Agent 3 — Impact Analysis Agent

**Trigger:** Event-driven — new row written to policy_changes by Agent 1

**What it does:**
The most analytically interesting agent. When a policy version changes, it needs to understand *what specifically changed* and *which assets are now newly non-compliant* under the new version that were previously compliant. This delta — not the total breach count, which Agent 2 already tracks — is the material number. It is the answer to "how many accounts just became a problem because of this rule change."

**DeepMind API call:**
```python
model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    tools=impact_tools,
    generation_config={"response_mime_type": "application/json"}
)

prompt = f"""
A policy has changed. Analyse the impact.

Previous version text: {old_policy_text}
New version text: {new_policy_text}
Vector similarity score: {similarity_score}   # from ClickHouse ANN search

1. What specifically changed? (threshold, new field requirement, jurisdiction change, effective date)
2. Under the new requirements, construct the updated compliance query for retail_accounts tagged with this policy
3. Run the query and compare against the last compliance_scans result
4. Return: newly_non_compliant_count, newly_compliant_count, unchanged_breach_count, impact_summary

Return JSON only.
"""
```

**Tools:**
- `get_policy_change(change_id)` — reads policy_changes event
- `get_policy_versions(policy_id)` — fetches old and new version text from regulatory_documents
- `diff_policy_versions(old_embedding, new_embedding)` — vector similarity in ClickHouse to characterise magnitude of change
- `get_last_scan(policy_id)` — reads most recent compliance_scans row for baseline
- `run_impact_query(policy_id, new_conditions)` — queries tagged assets under new requirements
- `generate_impact_report(delta)` — structured JSON output
- `write_audit_entry(event)` — writes to audit_trail
- `trigger_datadog_alert(impact_report)` — fires critical alert with delta

**Output:**
```json
{
  "policy_id": "SEC-REG-BI",
  "change_summary": "Consent requirement extended to voice-authorised accounts effective 2026-09-01",
  "previously_non_compliant": 12400,
  "newly_non_compliant": 3200,
  "total_non_compliant": 15600,
  "newly_compliant": 0,
  "severity": "CRITICAL",
  "action_required": "Update consent collection for 3,200 voice-authorised retail accounts before 2026-09-01"
}
```

**Writes to ClickHouse:** compliance_scans, audit_trail, updates policies table with new version

---

## ClickHouse Schema

### policies
```sql
CREATE TABLE policies (
    policy_id       String,
    source          LowCardinality(String),
    title           String,
    current_version String,
    compliance_conditions String,   -- JSON: field, operator, value
    threshold       Int32,          -- max allowed breach count (usually 0)
    owner           String,
    active          Bool,
    effective_date  Date,
    updated_at      DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY policy_id;
```

### policy_changes
```sql
CREATE TABLE policy_changes (
    change_id       UUID DEFAULT generateUUIDv4(),
    policy_id       String,
    old_version     String,
    new_version     String,
    change_summary  String,
    detected_at     DateTime DEFAULT now(),
    processed       Bool DEFAULT false   -- set true once Agent 3 completes
) ENGINE = MergeTree()
ORDER BY (policy_id, detected_at);
```

### regulatory_documents
```sql
CREATE TABLE regulatory_documents (
    doc_id          UUID DEFAULT generateUUIDv4(),
    policy_id       String,
    source          LowCardinality(String),
    chunk_text      String,
    embedding       Array(Float32),
    version         String,
    published_date  DateTime,
    INDEX emb_idx embedding TYPE usearch(L2Distance) GRANULARITY 1
) ENGINE = MergeTree()
ORDER BY (policy_id, published_date);
```

### retail_accounts — synthetic asset
```sql
CREATE TABLE retail_accounts (
    account_id           UUID DEFAULT generateUUIDv4(),
    account_type         LowCardinality(String),   -- 'retail', 'institutional'
    state                LowCardinality(String),
    opened_date          Date,
    delivery_method      LowCardinality(String),   -- 'electronic', 'paper', 'none'
    consent_obtained     Bool,
    consent_date         Nullable(Date),
    form_crs_delivered   Bool,
    disclosure_version   LowCardinality(String),
    applicable_policies  Array(String),            -- e.g. ['SEC-REG-BI', 'CFPB-BNPL']
    active               Bool,
    created_at           DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (state, account_type, opened_date);
```

Seeded with 50,000 rows. ~25% non-compliant weighted toward CA, TX, NY.

### compliance_scans
```sql
CREATE TABLE compliance_scans (
    scan_id          UUID DEFAULT generateUUIDv4(),
    policy_id        String,
    triggered_by     LowCardinality(String),   -- 'monitoring_agent', 'impact_agent'
    breach_count     Int32,
    delta            Nullable(Int32),           -- newly non-compliant vs prior scan
    status           LowCardinality(String),   -- 'PASSING', 'FAILING'
    details          String,                    -- JSON breakdown by state
    scanned_at       DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (policy_id, scanned_at);
```

### audit_trail
```sql
CREATE TABLE audit_trail (
    event_id      UUID DEFAULT generateUUIDv4(),
    event_type    String,
    policy_id     Nullable(String),
    account_count Nullable(Int32),
    agent         LowCardinality(String),
    description   String,
    created_at    DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY created_at;
```

---

## DeepMind API Usage Summary

| Agent | Model | Pattern |
|---|---|---|
| Policy Crawler | text-embedding-004 | Embedding per chunk — no reasoning required |
| Monitoring Agent | gemini-2.5-flash | Function calling — constructs compliance query from policy definition |
| Impact Analysis Agent | gemini-2.5-flash | Function calling + structured JSON output — diffs policy versions, quantifies delta |

---

## Build Sequence for Saturday

Pre-build before Saturday: ClickHouse schema, seed script, Nimble source configuration, Reg BI document pre-parsed and ready to load.

| Hour | Task |
|---|---|
| 0–1 | ClickHouse up. Schema created. 50,000 retail_accounts seeded with applicable_policies tags. |
| 1–2 | Policy Crawler live. Reg BI ingested, embedded, stored. policies table populated. |
| 2–4 | Monitoring Agent live. Compliance check query running against tagged accounts. Breach count confirmed. Scan result stored. |
| 4–6 | Impact Analysis Agent live. Simulate a policy version change. Delta quantified. Impact report generated. |
| 6–7 | Datadog alerts configured. Dashboard showing compliance_scans time-series. |
| 7–8 | UI connected to ClickHouse. Demo arc rehearsed. |

---

## Demo Arc

**Step 1 — Monitoring Agent fires on scheduled scan**
12,400 retail accounts tagged with SEC-REG-BI are non-compliant. Datadog alert fires. Compliance scan stored.

**Step 2 — Policy Crawler detects a Reg BI update**
A new SEC guidance extends consent requirements to voice-authorised accounts. Version change written to policy_changes.

**Step 3 — Impact Analysis Agent triggers**
Diffs old vs new policy. Queries the 3,200 voice-authorised accounts now in scope. Delta: 3,200 newly non-compliant. Total breach: 15,600. Critical alert fires.

**Closing line:**
> "Citigroup paid $1.975 million for a query that takes 4 seconds to run."
