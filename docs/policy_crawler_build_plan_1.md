# RegRadar — Policy Crawler Build Plan

---

## Overview

The Policy Crawler has three discrete skills that compose into one scheduled agent:

1. **URL Scanner** — Nimble fetches raw regulatory content from four sources
2. **Condition Extractor** — DeepMind gemini-2.5-flash parses raw text into structured compliance conditions (one LLM call per regulation section)
3. **Embedding Generator** — DeepMind text-embedding-004 chunks policy text and stores vectors in ClickHouse

These run in sequence per URL. The LLM call happens exactly once per regulation section per version. Everything else is deterministic.

---

## Skill 1 — URL Scanner (Nimble)

### URL Manifest

Four policy embeddings. Four primary URLs. Four fallback URLs.

| Embedding Key | Regulation | Primary URL | Fallback URL |
|---|---|---|---|
| `REG-Z-1026-9G` | Reg Z § 1026.9(g) — 45-day notice | `https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.9` | `https://www.consumerfinance.gov/rules-policy/regulations/1026/9/` |
| `REG-Z-1026-13` | Reg Z § 1026.13 — Billing disputes | `https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.13` | `https://www.consumerfinance.gov/rules-policy/regulations/1026/13/` |
| `FCRA-605` | FCRA § 605 — 7-year stale data | `https://www.law.cornell.edu/uscode/text/15/1681c` | `https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1681c` |
| `FCRA-623A` | FCRA § 623(a) — Furnisher accuracy + dispute | `https://www.law.cornell.edu/uscode/text/15/1681s-2` | `https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1681s-2` |

### Change Detection URLs

Polled hourly to detect new guidance, amendments, or enforcement actions:

| Source | URL | What to watch for |
|---|---|---|
| CFPB Final Rules | `https://www.consumerfinance.gov/rules-policy/final-rules/` | New Reg Z amendments |
| CFPB Supervisory Guidance | `https://www.consumerfinance.gov/rules-policy/guidance/` | TILA/FCRA interpretive guidance |
| Federal Register CFPB | `https://www.federalregister.gov/agencies/consumer-financial-protection-bureau` | Proposed and final rules |
| FTC FCRA Updates | `https://www.ftc.gov/legal-library/browse/statutes/fair-credit-reporting-act` | FCRA statute amendments |

### Nimble Scraper Skill

```python
import os
import httpx
import hashlib
from datetime import datetime, timezone

NIMBLE_API_URL = "https://api.nimbleway.com/v1/realtime/web"
NIMBLE_API_KEY = os.environ["NIMBLE_API_KEY"]

URL_MANIFEST = [
    {
        "embedding_key": "REG-Z-1026-9G",
        "regulation_id": "TILA-REG-Z-1026-9-G",
        "url": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.9",
        "fallback_url": "https://www.consumerfinance.gov/rules-policy/regulations/1026/9/",
        "section": "1026.9(g)",
        "source": "eCFR"
    },
    {
        "embedding_key": "REG-Z-1026-13",
        "regulation_id": "TILA-REG-Z-1026-13",
        "url": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.13",
        "fallback_url": "https://www.consumerfinance.gov/rules-policy/regulations/1026/13/",
        "section": "1026.13",
        "source": "eCFR"
    },
    {
        "embedding_key": "FCRA-605",
        "regulation_id": "FCRA-15-USC-1681C",
        "url": "https://www.law.cornell.edu/uscode/text/15/1681c",
        "fallback_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1681c",
        "section": "Section 605",
        "source": "Cornell LII"
    },
    {
        "embedding_key": "FCRA-623A",
        "regulation_id": "FCRA-15-USC-1681S-2",
        "url": "https://www.law.cornell.edu/uscode/text/15/1681s-2",
        "fallback_url": "https://uscode.house.gov/view.xhtml?req=granuleid:USC-prelim-title15-section1681s-2",
        "section": "Section 623(a)",
        "source": "Cornell LII"
    },
]

async def scrape_url(url: str) -> dict:
    """Fetch regulatory text via Nimble. Returns raw text and content hash."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            NIMBLE_API_URL,
            json={
                "url": url,
                "render_js": False,
                "parse": False,
            },
            headers={
                "Authorization": f"Basic {NIMBLE_API_KEY}",
                "Content-Type": "application/json"
            }
        )
        response.raise_for_status()
        data = response.json()
        text = data.get("text", "") or data.get("html_text", "")
        return {
            "text": text,
            "content_hash": hashlib.sha256(text.encode()).hexdigest(),
            "scraped_at": datetime.now(timezone.utc).isoformat()
        }

async def scrape_with_fallback(entry: dict) -> dict:
    """Try primary URL, fall back to secondary on failure."""
    try:
        result = await scrape_url(entry["url"])
        result["url_used"] = entry["url"]
    except Exception:
        result = await scrape_url(entry["fallback_url"])
        result["url_used"] = entry["fallback_url"]
    result.update(entry)
    return result

def has_changed(regulation_id: str, new_hash: str, clickhouse_client) -> bool:
    """Compare content hash against last stored version."""
    row = clickhouse_client.query(
        "SELECT content_hash FROM regulatory_documents "
        "WHERE regulation_id = %(rid)s "
        "ORDER BY published_date DESC LIMIT 1",
        {"rid": regulation_id}
    ).first_row
    if not row:
        return True
    return row[0] != new_hash
```

---

## Skill 2 — Condition Extractor (DeepMind Agent)

This is the single non-deterministic step in the Policy Crawler. One LLM call per regulation section. The output is a structured JSON object that defines every compliance control the Monitoring Agent will later execute as SQL.

### The Prompt

```python
import google.generativeai as genai
import json

genai.configure(api_key=os.environ["DEEPMIND_API_KEY"])

EXTRACTION_SYSTEM_PROMPT = """
You are a regulatory compliance engineer. Your job is to read raw regulatory
text and extract precise, machine-executable compliance conditions.

You must return valid JSON only. No preamble, no markdown, no explanation.

For each compliance control in the text, extract:
- control_id: short snake_case identifier
- description: one sentence plain English
- trigger_type: one of [behavior, schema_change, time_based]
- trigger_field: the account field that triggers this check
- trigger_value: the value or condition that fires the trigger
- compliance_conditions: array of {field, operator, value, unit}
- account_scope: array of account types this applies to
- threshold_days: integer if time-based, null otherwise
- sql_condition: the WHERE clause that identifies non-compliant accounts
- controls_covered: array of control names this embedding covers
"""

EXTRACTION_USER_TEMPLATE = """
Regulation: {regulation_name}
Section: {section}
Embedding key: {embedding_key}

Raw regulatory text:
---
{raw_text}
---

Extract all compliance controls. Map to fields in this credit card account schema:
- account_id, account_type, state
- days_past_due, payment_status
- penalty_rate_applied, penalty_notice_sent_date, rate_change_date
- promo_rate_end_date, promo_notice_sent_date
- dispute_filed, dispute_filed_date, dispute_acknowledged_date, dispute_resolved_date
- bureau_reported_status, bureau_dispute_flag
- original_delinquency_date, charged_off, bureau_still_reporting
- applicable_policies (Array of strings)

Return JSON matching this schema:
{{
  "regulation_id": string,
  "regulation_name": string,
  "section": string,
  "embedding_key": string,
  "version_date": string (ISO date),
  "controls": [
    {{
      "control_id": string,
      "description": string,
      "trigger_type": "behavior" | "schema_change" | "time_based",
      "trigger_field": string,
      "trigger_value": string,
      "compliance_conditions": [
        {{ "field": string, "operator": string, "value": string, "unit": string | null }}
      ],
      "account_scope": [string],
      "threshold_days": integer | null,
      "sql_condition": string,
      "controls_covered": [string]
    }}
  ]
}}
"""

def extract_compliance_conditions(scraped: dict) -> dict:
    """
    Single LLM call per regulation section.
    Returns structured compliance conditions ready for ClickHouse storage.
    """
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0          # deterministic extraction
        },
        system_instruction=EXTRACTION_SYSTEM_PROMPT
    )

    prompt = EXTRACTION_USER_TEMPLATE.format(
        regulation_name=scraped["regulation_id"],
        section=scraped["section"],
        embedding_key=scraped["embedding_key"],
        raw_text=scraped["text"][:8000]   # token budget guard
    )

    response = model.generate_content(prompt)
    return json.loads(response.text)
```

### Expected Output — Reg Z 1026.9(g)

```json
{
  "regulation_id": "TILA-REG-Z-1026-9-G",
  "regulation_name": "Regulation Z Section 1026.9(g) — Rate Change Notice",
  "section": "1026.9(g)",
  "embedding_key": "REG-Z-1026-9G",
  "version_date": "2024-01-01",
  "controls": [
    {
      "control_id": "CTRL-TILA-PENALTY-NOTICE",
      "description": "Creditor must provide 45-day written notice before applying a penalty rate",
      "trigger_type": "behavior",
      "trigger_field": "penalty_rate_applied",
      "trigger_value": "true",
      "compliance_conditions": [
        { "field": "penalty_notice_sent_date", "operator": "IS NOT NULL", "value": null, "unit": null },
        { "field": "rate_change_date - penalty_notice_sent_date", "operator": ">=", "value": "45", "unit": "days" }
      ],
      "account_scope": ["retail", "open-end-credit"],
      "threshold_days": 45,
      "sql_condition": "penalty_rate_applied = true AND (penalty_notice_sent_date IS NULL OR date_diff('day', penalty_notice_sent_date, rate_change_date) < 45)",
      "controls_covered": ["Penalty Rate Notice", "Promo Rate Expiry"]
    },
    {
      "control_id": "CTRL-TILA-PROMO-NOTICE",
      "description": "Creditor must provide 45-day written notice before a promotional rate expires",
      "trigger_type": "time_based",
      "trigger_field": "promo_rate_end_date",
      "trigger_value": "within 45 days",
      "compliance_conditions": [
        { "field": "date_diff('day', today(), promo_rate_end_date)", "operator": "<=", "value": "45", "unit": "days" },
        { "field": "promo_notice_sent_date", "operator": "IS NULL", "value": null, "unit": null }
      ],
      "account_scope": ["retail", "open-end-credit"],
      "threshold_days": 45,
      "sql_condition": "promo_rate_end_date IS NOT NULL AND date_diff('day', today(), promo_rate_end_date) <= 45 AND promo_notice_sent_date IS NULL",
      "controls_covered": ["Promo Rate Expiry"]
    }
  ]
}
```

---

## Skill 3 — Embedding Generator (DeepMind text-embedding-004)

Runs after Skill 2. Chunks the raw policy text and generates one embedding per chunk. All embeddings stored in ClickHouse `regulatory_documents` with the usearch ANN index for later retrieval.

### Chunking Strategy

```python
from typing import Generator

def chunk_policy_text(
    text: str,
    chunk_size: int = 512,
    overlap: int = 64
) -> Generator[str, None, None]:
    """
    Split on paragraph boundaries first, then by token budget.
    Regulatory text is structured by subsection — respect those breaks.
    """
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    current_chunk = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para.split())
        if current_size + para_size > chunk_size and current_chunk:
            yield ' '.join(current_chunk)
            # keep last paragraph as overlap context
            overlap_text = current_chunk[-1] if current_chunk else ""
            current_chunk = [overlap_text, para]
            current_size = len(overlap_text.split()) + para_size
        else:
            current_chunk.append(para)
            current_size += para_size

    if current_chunk:
        yield ' '.join(current_chunk)
```

### Embedding Call

```python
def generate_embedding(text: str) -> list[float]:
    """Single embedding call. Returns 768-dim vector."""
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document",
        title="Regulatory policy text"
    )
    return result["embedding"]

def embed_and_store(scraped: dict, conditions: dict, clickhouse_client) -> int:
    """
    Chunk policy text, generate embeddings, insert into ClickHouse.
    Returns number of chunks stored.
    """
    chunks = list(chunk_policy_text(scraped["text"]))
    rows = []

    for i, chunk in enumerate(chunks):
        embedding = generate_embedding(chunk)
        rows.append({
            "policy_id":       conditions["regulation_id"],
            "source":          scraped["source"],
            "section":         scraped["section"],
            "chunk_index":     i,
            "chunk_text":      chunk,
            "embedding":       embedding,
            "content_hash":    scraped["content_hash"],
            "version":         conditions["version_date"],
            "published_date":  datetime.now(timezone.utc)
        })

    clickhouse_client.insert("regulatory_documents", rows)
    return len(rows)
```

### ClickHouse Insert — regulatory_documents

```sql
CREATE TABLE IF NOT EXISTS regulatory_documents (
    doc_id          UUID DEFAULT generateUUIDv4(),
    policy_id       String,
    source          LowCardinality(String),
    section         String,
    chunk_index     UInt16,
    chunk_text      String,
    embedding       Array(Float32),
    content_hash    String,
    version         String,
    published_date  DateTime,
    INDEX emb_idx   embedding TYPE usearch(L2Distance) GRANULARITY 1
) ENGINE = MergeTree()
ORDER BY (policy_id, published_date, chunk_index);
```

---

## Policy Crawler — Composed Agent

All three skills run in sequence. One hourly execution per URL in the manifest.

```python
import asyncio
from clickhouse_driver import Client

async def run_policy_crawler():
    ch = Client(host=os.environ["CLICKHOUSE_HOST"])

    for entry in URL_MANIFEST:
        # Skill 1: Scrape
        scraped = await scrape_with_fallback(entry)

        # Change detection — skip if content unchanged
        if not has_changed(entry["regulation_id"], scraped["content_hash"], ch):
            print(f"No change: {entry['regulation_id']}")
            continue

        print(f"Change detected: {entry['regulation_id']}")

        # Skill 2: Extract compliance conditions (one LLM call)
        conditions = extract_compliance_conditions(scraped)

        # Skill 3: Generate embeddings and store
        chunk_count = embed_and_store(scraped, conditions, ch)

        # Store structured conditions in policies table
        store_policy_conditions(conditions, ch)

        # Write policy_changes event → triggers Impact Analysis Agent
        write_policy_change_event(entry["regulation_id"], conditions, ch)

        print(f"Stored {chunk_count} chunks for {entry['regulation_id']}")

def store_policy_conditions(conditions: dict, ch) -> None:
    for control in conditions["controls"]:
        ch.execute(
            """
            INSERT INTO governance_controls
            (control_id, regulation_id, title, description,
             query_template, threshold, owner, frequency, active)
            VALUES
            """,
            [{
                "control_id":     control["control_id"],
                "regulation_id":  conditions["regulation_id"],
                "title":          control["description"],
                "description":    control["description"],
                "query_template": control["sql_condition"],
                "threshold":      0,
                "owner":          "Compliance Team",
                "frequency":      "daily",
                "active":         True
            }]
        )

def write_policy_change_event(regulation_id: str, conditions: dict, ch) -> None:
    ch.execute(
        "INSERT INTO policy_changes "
        "(policy_id, new_version, change_summary, processed) VALUES",
        [{
            "policy_id":      regulation_id,
            "new_version":    conditions["version_date"],
            "change_summary": f"Policy updated — {len(conditions['controls'])} controls extracted",
            "processed":      False
        }]
    )

if __name__ == "__main__":
    asyncio.run(run_policy_crawler())
```

---

## Execution Order on Saturday

```
1. Verify Nimble API key and test scrape against ecfr.gov
2. Verify DeepMind API key and test extraction prompt against Reg Z 1026.9(g) text
3. Create ClickHouse tables: regulatory_documents, governance_controls, policy_changes
4. Run policy crawler once manually against all four URLs
5. Confirm four policy embeddings stored in regulatory_documents
6. Confirm governance_controls populated with six control SQL conditions
7. Schedule hourly cron for policy crawler
```

---

## Pre-build Validation Checklist

- [ ] Nimble scrape of `ecfr.gov/current/title-12/chapter-X/part-1026/section-1026.9` returns clean text
- [ ] Nimble scrape of `law.cornell.edu/uscode/text/15/1681c` returns clean text
- [ ] DeepMind extraction prompt on Reg Z 1026.9(g) returns valid JSON with `sql_condition` populated
- [ ] DeepMind extraction on FCRA 605 returns threshold_days = 2557 (7 years)
- [ ] text-embedding-004 returns 768-dimension vector for a sample chunk
- [ ] ClickHouse usearch index accepts Array(Float32) inserts without error
- [ ] content_hash comparison correctly skips unchanged regulations
