# SEED_DATA.md

Every piece of data that must be pre-loaded before the demo. With generation scripts.

This file replaces the old NovaPay/derivatives scope. Domain is now: **consumer credit card portfolios + TILA/Regulation Z + FCRA**.

---

## Table of Contents

1. [Load Order](#1-load-order)
2. [Company Profile -- Pinecrest Bank (Credit Card Issuer)](#2-company-profile)
3. [The Two Regulations](#3-the-two-regulations--tila--fcra)
4. [The 4 Policy Embeddings](#4-the-4-policy-embeddings)
5. [The 6 Compliance Controls (TILA + FCRA)](#5-the-6-compliance-controls)
6. [Synthetic Credit Card Portfolio (~50k accounts)](#6-synthetic-credit-card-portfolio)
7. [Pre-Staged Demo Events](#7-pre-staged-demo-events)
8. [Load Order Script](#8-load-order-script)
9. [Agent System Prompts -- File References](#9-agent-system-prompts)

---

## 1. Load Order

Run `python scripts/load_seed_data.py` which executes these in order:

1. Apply schema (`backend/data/schema.sql`)
2. Insert company profile -- Pinecrest Bank (`seed/issuer_profile.json`)
3. Insert 2 regulation versions -- TILA 12 CFR 1026 + FCRA 15 USC 1681 (`seed/regulations.json`)
4. Insert 4 policy embeddings (`seed/policy_embeddings.json` -- pre-computed at seed time)
5. Insert 6 compliance conditions (`seed/compliance_conditions.json`)
6. Generate + insert ~50,000 credit card accounts (`seed/credit_cards/generate_accounts.py`)
7. Insert 6 controls with their `check_sql` (`seed/controls.json`)
8. Run initial test of each control → insert into `compliance_scans`

Expected runtime: ~90 seconds locally, ~3 minutes against ClickHouse Cloud.

---

## 2. Company Profile

A small/mid-cap credit card issuer. Picked to be in Senso's ICP (community bank / credit union) so the cited.md publishing story lands.

```json
// seed/issuer_profile.json
{
  "company_id": "pinecrest_bank_demo",
  "name": "Pinecrest Bank",
  "type": "regional_credit_card_issuer",
  "annual_volume_usd": 850000000,
  "active_accounts": 52000,
  "employee_count": 240,
  "headquarters": "Denver, CO, USA",
  "founded": 2014,
  "products": [
    "standard_visa",
    "rewards_visa",
    "secured_visa",
    "student_visa"
  ],
  "customer_segments": [
    "us_consumers_prime",
    "us_consumers_subprime",
    "us_consumers_students",
    "us_consumers_credit_builder"
  ],
  "states_operating_in": "ALL_US_50_PLUS_DC",
  "regulators": [
    "CFPB",
    "FRB",
    "FDIC",
    "FTC"
  ],
  "applicable_regimes": [
    "TILA_Regulation_Z",
    "FCRA"
  ],
  "current_policies": {
    "promo_notice_lead_days": 45,
    "penalty_rate_notice_lead_days": 45,
    "dispute_acknowledgment_target_days": 30,
    "dispute_resolution_target_days": 90,
    "bureau_reporting_enabled": true,
    "stale_data_review_cadence_days": "ad_hoc"
  },
  "compliance_team_size": 6,
  "bureau_reporting_to": ["Experian", "Equifax", "TransUnion"]
}
```

---

## 3. The Two Regulations -- TILA + FCRA

Only two regulations. Six controls extracted from them. This is deliberately narrow -- depth over breadth lets us land every demo claim with full citations.

```json
// seed/regulations.json
[
  {
    "regulation_id": "tila_reg_z",
    "title": "Truth in Lending Act -- Regulation Z (12 CFR Part 1026)",
    "regulator": "CFPB",
    "regulation_section_top": "12 CFR 1026",
    "source_url": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026",
    "key_sections_for_controls": [
      "12 CFR 1026.9(g)",
      "12 CFR 1026.13"
    ],
    "priority": 1,
    "scrape_notes": "Reg Z is large. We pre-extract the relevant sections to keep the embedding corpus tight."
  },
  {
    "regulation_id": "fcra",
    "title": "Fair Credit Reporting Act (15 USC 1681)",
    "regulator": "FTC + CFPB",
    "regulation_section_top": "15 USC 1681",
    "source_url": "https://www.ftc.gov/legal-library/browse/statutes/fair-credit-reporting-act",
    "key_sections_for_controls": [
      "15 USC 1681c (Section 605)",
      "15 USC 1681s-2(a)(2) (Section 623(a)(2))",
      "15 USC 1681s-2(a)(3) (Section 623(a)(3))"
    ],
    "priority": 1,
    "scrape_notes": "FCRA has scattered amendments. We anchor on Sections 605 and 623 which power 3 of our 6 controls."
  }
]
```

### Why only two regulations

For a 3-minute demo, depth wins. Six controls across two regimes lets every demo claim cite an exact section. The Auditor's grounding check fires against a tight corpus -- ~4 embedded chunks -- so verification is fast and reliable.

In a production deployment, RegRadar scales horizontally: add more regulations → more embeddings → more compliance_conditions extracted by the Policy Crawler. The 4-agent architecture stays the same.

---

## 4. The 4 Policy Embeddings

Pre-computed at seed time so the demo doesn't depend on a live Gemini embedding call. Each chunk is exactly the regulatory text quoted by one of the 6 controls.

```json
// seed/policy_embeddings.json (excerpt -- full file has all 4 chunks)
[
  {
    "embedding_id": "tila_9g_chunk_1",
    "regulation_id": "tila_reg_z",
    "regulation_section": "12 CFR 1026.9(g)",
    "chunk_index": 0,
    "chunk_text": "For each account under an open-end (not home-secured) consumer credit plan, a creditor must provide a written notice to each consumer who will be affected, at least 45 days before any of the following actions takes effect: (i) An increase in an annual percentage rate; (ii) An increase in any fee; (iii) An increase in the minimum payment; (iv) Application of an existing penalty rate.",
    "embedding": "REPLACED_AT_SEED_TIME_WITH_3072_DIM_VECTOR",
    "embedding_model": "gemini-embedding-001",
    "embedding_dim": 768,
    "embedding_notes": "Matryoshka-truncated from 3072 to 768 for ClickHouse vector index efficiency"
  },
  {
    "embedding_id": "tila_13_chunk_1",
    "regulation_id": "tila_reg_z",
    "regulation_section": "12 CFR 1026.13",
    "chunk_index": 0,
    "chunk_text": "A creditor shall mail or deliver written acknowledgment of receipt of a billing error notice within 30 days of receiving it, unless the creditor has complied with the requirements of paragraph (e) of this section within the 30-day period. A creditor shall complete its investigation and resolve the dispute within two complete billing cycles (not more than 90 days) of receiving a billing error notice.",
    "embedding": "REPLACED_AT_SEED_TIME",
    "embedding_model": "gemini-embedding-001",
    "embedding_dim": 768
  },
  {
    "embedding_id": "fcra_605_chunk_1",
    "regulation_id": "fcra",
    "regulation_section": "15 USC 1681c (FCRA Section 605)",
    "chunk_index": 0,
    "chunk_text": "Except as authorized under subsection (b), no consumer reporting agency may make any consumer report containing any of the following items of information: ... (4) Accounts placed for collection or charged to profit and loss which antedate the report by more than seven years. (5) Any other adverse item of information, other than records of convictions of crimes which antedates the report by more than seven years. The 7-year period begins on the date of the first delinquency that immediately preceded collection or charge-off.",
    "embedding": "REPLACED_AT_SEED_TIME",
    "embedding_model": "gemini-embedding-001",
    "embedding_dim": 768
  },
  {
    "embedding_id": "fcra_623_chunk_1",
    "regulation_id": "fcra",
    "regulation_section": "15 USC 1681s-2(a) (FCRA Section 623(a))",
    "chunk_index": 0,
    "chunk_text": "A person who furnishes information to a consumer reporting agency shall: (2) ensure that the information furnished is accurate and not materially misleading; (3) notify the consumer reporting agency of any dispute received from a consumer regarding the completeness or accuracy of any information furnished, by including a notation that the information is disputed.",
    "embedding": "REPLACED_AT_SEED_TIME",
    "embedding_model": "gemini-embedding-001",
    "embedding_dim": 768
  }
]
```

### Generation script

`seed/credit_cards/embed_policy_chunks.py` reads the chunks above, calls `vertex_ai.embed_text()`, and writes the embedding arrays back. Matryoshka truncation to 768 dims keeps the ClickHouse HNSW index efficient at small scale.

```python
# Run once at seed time
python seed/credit_cards/embed_policy_chunks.py
```

---

## 5. The 6 Compliance Controls

Six SQL-evaluable controls. The Monitoring Agent runs all 6 daily with **zero LLM calls**.

```json
// seed/controls.json
[
  {
    "control_id": "CTRL-TILA-PENALTY-RATE-NOTICE",
    "name": "Penalty Rate 45-Day Notice (TILA)",
    "description": "Before applying a penalty APR to an account, the issuer must send written notice at least 45 days in advance.",
    "related_regulation_id": "tila_reg_z",
    "related_regulation_section": "12 CFR 1026.9(g)",
    "condition_kind": "advance_notice",
    "threshold_value": 45,
    "threshold_unit": "days",
    "threshold_comparison": "gte",
    "owner_team": "Customer Operations",
    "test_frequency": "event_based + daily",
    "check_sql": "SELECT count() AS breach_count, sum(balance_usd) AS breach_balance_usd, groupArraySample(20)(account_id) AS sample_account_ids FROM credit_card_accounts WHERE penalty_rate_applied = true AND penalty_rate_notice_sent_date IS NULL OR dateDiff('day', penalty_rate_notice_sent_date, penalty_rate_applied_date) < 45",
    "severity": "HIGH"
  },
  {
    "control_id": "CTRL-TILA-PROMO-RATE-NOTICE",
    "name": "Promo Rate 45-Day Expiry Notice (TILA)",
    "description": "Before a promotional rate expires and the standard APR resumes, the issuer must give 45 days' written notice.",
    "related_regulation_id": "tila_reg_z",
    "related_regulation_section": "12 CFR 1026.9(g)",
    "condition_kind": "advance_notice",
    "threshold_value": 45,
    "threshold_unit": "days",
    "threshold_comparison": "gte",
    "owner_team": "Customer Operations",
    "test_frequency": "daily",
    "check_sql": "SELECT count() AS breach_count, sum(balance_usd) AS breach_balance_usd, groupArraySample(20)(account_id) AS sample_account_ids FROM credit_card_accounts WHERE promo_rate IS NOT NULL AND promo_rate_end_date IS NOT NULL AND promo_rate_end_date > today() AND dateDiff('day', today(), promo_rate_end_date) < 45 AND promo_notice_sent_date IS NULL",
    "severity": "MEDIUM"
  },
  {
    "control_id": "CTRL-TILA-DISPUTE-RESOLUTION",
    "name": "Billing Dispute Resolution Clocks (TILA)",
    "description": "When a billing dispute is filed, the issuer must acknowledge within 30 days AND resolve within 90 days.",
    "related_regulation_id": "tila_reg_z",
    "related_regulation_section": "12 CFR 1026.13",
    "condition_kind": "time_window",
    "threshold_value": "30_and_90",
    "threshold_unit": "days",
    "threshold_comparison": "lte",
    "owner_team": "Customer Operations",
    "test_frequency": "event_based + daily",
    "check_sql": "SELECT count() AS breach_count, sum(balance_usd) AS breach_balance_usd, groupArraySample(20)(account_id) AS sample_account_ids FROM credit_card_accounts WHERE dispute_filed = true AND ((dispute_acknowledged_date IS NULL AND dateDiff('day', dispute_filed_date, today()) > 30) OR (dispute_resolved_date IS NULL AND dateDiff('day', dispute_filed_date, today()) > 90))",
    "severity": "HIGH"
  },
  {
    "control_id": "CTRL-FCRA-STALE-DATA",
    "name": "7-Year Reporting Limit (FCRA Section 605)",
    "description": "Accounts that became delinquent more than 7 years ago must not be reported to consumer reporting agencies.",
    "related_regulation_id": "fcra",
    "related_regulation_section": "15 USC 1681c (FCRA Section 605)",
    "condition_kind": "stale_data_limit",
    "threshold_value": 7,
    "threshold_unit": "years",
    "threshold_comparison": "lt",
    "owner_team": "Bureau Reporting",
    "test_frequency": "event_based (schema_event) + daily",
    "check_sql": "SELECT count() AS breach_count, sum(balance_usd) AS breach_balance_usd, groupArraySample(20)(account_id) AS sample_account_ids FROM credit_card_accounts WHERE bureau_reported = true AND original_delinquency_date IS NOT NULL AND dateDiff('year', original_delinquency_date, today()) > 7",
    "severity": "CRITICAL"
  },
  {
    "control_id": "CTRL-FCRA-BUREAU-ACCURACY",
    "name": "Bureau Status Accuracy (FCRA Section 623(a)(2))",
    "description": "What we tell the bureaus must match the customer's actual payment status. Mismatches are inaccurate reporting.",
    "related_regulation_id": "fcra",
    "related_regulation_section": "15 USC 1681s-2(a)(2)",
    "condition_kind": "field_match",
    "threshold_value": "field_equality",
    "threshold_unit": "string_match",
    "threshold_comparison": "eq",
    "owner_team": "Bureau Reporting",
    "test_frequency": "daily",
    "check_sql": "SELECT count() AS breach_count, sum(balance_usd) AS breach_balance_usd, groupArraySample(20)(account_id) AS sample_account_ids FROM credit_card_accounts WHERE bureau_reported = true AND bureau_reported_status IS NOT NULL AND bureau_reported_status != payment_status",
    "severity": "HIGH"
  },
  {
    "control_id": "CTRL-FCRA-DISPUTE-FLAG",
    "name": "Dispute Bureau Flag (FCRA Section 623(a)(3))",
    "description": "If a dispute is filed, the bureau record must be flagged 'disputed' until resolution.",
    "related_regulation_id": "fcra",
    "related_regulation_section": "15 USC 1681s-2(a)(3)",
    "condition_kind": "dispute_flag_required",
    "threshold_value": true,
    "threshold_unit": "boolean",
    "threshold_comparison": "eq",
    "owner_team": "Bureau Reporting",
    "test_frequency": "event_based + daily",
    "check_sql": "SELECT count() AS breach_count, sum(balance_usd) AS breach_balance_usd, groupArraySample(20)(account_id) AS sample_account_ids FROM credit_card_accounts WHERE dispute_filed = true AND dispute_resolved_date IS NULL AND (dispute_bureau_flag IS NULL OR dispute_bureau_flag = false)",
    "severity": "HIGH"
  }
]
```

### Why six and not more

Demo math: 3 minutes / 6 controls = 30 seconds per control if we wanted to show every one. We don't. The demo lands two of them visibly (CTRL-FCRA-STALE-DATA and CTRL-TILA-DISPUTE-RESOLUTION + CTRL-FCRA-DISPUTE-FLAG via the dispute_filed cross-trigger). The other three sit in the dashboard PASSING/AT_RISK/FAILING tally, showing the system has broader coverage than what we narrated.

---

## 6. Synthetic Credit Card Portfolio

50,000 accounts. Distribution carefully tuned so the demo produces sensible breach numbers without manual seeding of the demo accounts.

### Schema

See [DATA_MODEL.md](DATA_MODEL.md) section 2 for the full column list. Key fields the generator populates:

| Field | Distribution |
|---|---|
| `state` | Weighted: CA 12%, TX 9%, FL 7%, NY 6%, then evenly across 47 others |
| `product_type` | standard 70%, rewards 20%, secured 5%, student 5% |
| `credit_limit_usd` | log-normal, median $5,000, max $50,000 |
| `balance_usd` | uniform 0 to 0.85 × credit_limit |
| `apr` | normal mean 21%, std 4% |
| `promo_rate` | 25% of accounts have one assigned (active or recently expired) |
| `promo_rate_end_date` | for the 25%: spread evenly over next 18 months |
| `promo_notice_sent_date` | for the 25%: ~60% have it sent on time, ~30% sent late, ~10% NULL (gives us CTRL-TILA-PROMO-RATE-NOTICE failures) |
| `penalty_rate_applied` | 2% of accounts have penalty rates applied |
| `penalty_rate_notice_sent_date` | of those: ~85% have proper notice, ~15% don't (CTRL-TILA-PENALTY-RATE-NOTICE failures) |
| `dispute_filed` | 0.8% have active disputes (~400 accounts) |
| `dispute_filed_date` | uniform within last 120 days |
| `dispute_acknowledged_date` | of disputes: ~70% acknowledged within 30 days, ~30% NOT |
| `dispute_resolved_date` | of disputes: ~50% resolved within 90 days, ~50% NOT |
| `dispute_bureau_flag` | of disputes: ~80% flagged correctly, ~20% NOT (CTRL-FCRA-DISPUTE-FLAG failures) |
| `bureau_reported` | 95% of accounts |
| `bureau_reported_status` | matches payment_status for 97%, mismatch for 3% (~1500 accounts → CTRL-FCRA-BUREAU-ACCURACY) |
| `original_delinquency_date` | starts NULL on all accounts (demo trigger: backfill ~12% of accounts; of those, ~21% will be >7 years old → ~1,247 stale FCRA violations) |

### Why the headline numbers

- **CTRL-FCRA-STALE-DATA breach count ~1,247** -- punchier than 200, less suspicious than 10,000
- **dispute_filed ~400** -- big enough that the dashboard counter is visible, small enough to be a believable issuer-scale number
- **CTRL-FCRA-BUREAU-ACCURACY breach count ~1,500** -- shows another control in FAILING for breadth

### Generator script

```python
# seed/credit_cards/generate_accounts.py

"""
Generate ~50,000 synthetic credit card accounts.

Distributions tuned so the demo lands specific numbers:
  - CTRL-FCRA-STALE-DATA: ~1,247 accounts breach AFTER schema enrichment
  - CTRL-FCRA-BUREAU-ACCURACY: ~1,500 accounts breach
  - CTRL-FCRA-DISPUTE-FLAG: ~80 of the 400 disputes lack flag
  - CTRL-TILA-DISPUTE-RESOLUTION: ~120 disputes past acknowledgment or resolution clock
  - CTRL-TILA-PROMO-RATE-NOTICE: ~1,200 accounts missing notice
  - CTRL-TILA-PENALTY-RATE-NOTICE: ~150 accounts missing notice
"""

import json
import random
import os
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
from faker import Faker

random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

OUT_PATH = Path(__file__).parent / "accounts.jsonl"
N = int(os.environ.get("REGRADAR_SEED_ACCOUNTS", "50000"))

STATE_WEIGHTS = {
    "CA": 0.12, "TX": 0.09, "FL": 0.07, "NY": 0.06, "PA": 0.04,
    "IL": 0.04, "OH": 0.04, "GA": 0.03, "NC": 0.03, "MI": 0.03,
    "NJ": 0.03, "VA": 0.025, "WA": 0.025, "MA": 0.025, "AZ": 0.025,
    "TN": 0.02, "IN": 0.02, "MO": 0.02, "MD": 0.02, "WI": 0.02,
    "CO": 0.018, "MN": 0.018, "SC": 0.015, "AL": 0.015, "LA": 0.015,
    "KY": 0.012, "OR": 0.012, "OK": 0.012, "CT": 0.011, "UT": 0.011,
    # Rest distributed evenly
}

PRODUCT_TYPES = ["standard", "rewards", "secured", "student"]
PRODUCT_WEIGHTS = [0.70, 0.20, 0.05, 0.05]

PAYMENT_STATUSES = ["current", "30_days_late", "60_days_late", "90_days_late", "charge_off"]
PAYMENT_WEIGHTS = [0.92, 0.04, 0.02, 0.01, 0.01]


def gen_account(idx: int) -> dict:
    state = np.random.choice(list(STATE_WEIGHTS.keys()), p=_normalize(STATE_WEIGHTS.values()))
    product_type = np.random.choice(PRODUCT_TYPES, p=PRODUCT_WEIGHTS)
    credit_limit = round(float(np.clip(np.random.lognormal(8.5, 0.8), 500, 50000)), 2)
    balance = round(credit_limit * np.random.uniform(0, 0.85), 2)
    apr = round(float(np.clip(np.random.normal(0.21, 0.04), 0.05, 0.36)), 4)
    payment_status = np.random.choice(PAYMENT_STATUSES, p=PAYMENT_WEIGHTS)
    origination_date = fake.date_between(start_date="-5y", end_date="today")

    record = {
        "account_id": f"acct_{idx:06d}",
        "customer_id": f"cust_{uuid4().hex[:12]}",
        "state": state,
        "product_type": product_type,
        "credit_limit_usd": credit_limit,
        "balance_usd": balance,
        "apr": apr,
        "payment_status": payment_status,
        "origination_date": origination_date.isoformat(),
        "status": "active" if payment_status != "charge_off" else "closed",
        "bureau_reported": np.random.random() < 0.95,
        # The fields below are set conditionally by helper functions
        "promo_rate": None,
        "promo_rate_end_date": None,
        "promo_notice_sent_date": None,
        "penalty_rate_applied": False,
        "penalty_rate_applied_date": None,
        "penalty_rate_notice_sent_date": None,
        "dispute_filed": False,
        "dispute_filed_date": None,
        "dispute_acknowledged_date": None,
        "dispute_resolved_date": None,
        "dispute_bureau_flag": None,
        "bureau_reported_status": None,
        "original_delinquency_date": None,  # populated by demo schema_event, NOT at seed time
        "charge_off_date": None,
    }

    _maybe_assign_promo(record)
    _maybe_apply_penalty_rate(record)
    _maybe_file_dispute(record, origination_date)
    _maybe_set_bureau_status(record)
    _maybe_set_charge_off(record, origination_date)

    return record


def _maybe_assign_promo(rec: dict) -> None:
    if np.random.random() < 0.25:
        rec["promo_rate"] = round(float(np.random.uniform(0.0, 0.099)), 4)
        end_offset_days = int(np.random.uniform(-60, 540))  # some recently expired, some up to 18 months out
        rec["promo_rate_end_date"] = (date.today() + timedelta(days=end_offset_days)).isoformat()
        notice_status = np.random.choice(["on_time", "late", "missing"], p=[0.60, 0.30, 0.10])
        if notice_status == "on_time":
            rec["promo_notice_sent_date"] = (date.today() + timedelta(days=end_offset_days - 45)).isoformat()
        elif notice_status == "late":
            rec["promo_notice_sent_date"] = (date.today() + timedelta(days=end_offset_days - 20)).isoformat()
        # missing → stays None


def _maybe_apply_penalty_rate(rec: dict) -> None:
    if np.random.random() < 0.02:
        applied_offset = int(np.random.uniform(-180, 0))
        rec["penalty_rate_applied"] = True
        rec["penalty_rate_applied_date"] = (date.today() + timedelta(days=applied_offset)).isoformat()
        if np.random.random() < 0.85:
            rec["penalty_rate_notice_sent_date"] = (date.today() + timedelta(days=applied_offset - 45)).isoformat()


def _maybe_file_dispute(rec: dict, origination: date) -> None:
    if np.random.random() < 0.008:
        days_ago = int(np.random.uniform(0, 120))
        filed = date.today() - timedelta(days=days_ago)
        rec["dispute_filed"] = True
        rec["dispute_filed_date"] = filed.isoformat()
        if np.random.random() < 0.70:
            rec["dispute_acknowledged_date"] = (filed + timedelta(days=int(np.random.uniform(1, 25)))).isoformat()
        if np.random.random() < 0.50 and days_ago > 30:
            rec["dispute_resolved_date"] = (filed + timedelta(days=int(np.random.uniform(30, 85)))).isoformat()
        rec["dispute_bureau_flag"] = np.random.random() < 0.80


def _maybe_set_bureau_status(rec: dict) -> None:
    if rec["bureau_reported"]:
        if np.random.random() < 0.97:
            rec["bureau_reported_status"] = rec["payment_status"]  # accurate
        else:
            # 3% mismatch -- the wrong status from the list
            wrong = [s for s in PAYMENT_STATUSES if s != rec["payment_status"]]
            rec["bureau_reported_status"] = np.random.choice(wrong)


def _maybe_set_charge_off(rec: dict, origination: date) -> None:
    if rec["payment_status"] == "charge_off":
        rec["charge_off_date"] = fake.date_between(start_date=origination, end_date="today").isoformat()
        # Note: original_delinquency_date stays NULL at seed time. The demo's
        # schema_event populates it on a subset of accounts, surfacing FCRA violations.


def _normalize(weights):
    arr = np.array(list(weights))
    return arr / arr.sum()


def main():
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        for i in range(N):
            rec = gen_account(i)
            f.write(json.dumps(rec, default=str) + "\n")
    print(f"\u2713 Generated {N} accounts to {OUT_PATH}")


if __name__ == "__main__":
    main()
```

### Verification after seeding

```sql
-- Should return roughly the numbers we tuned for:
SELECT
    countIf(promo_rate IS NOT NULL) AS with_promo,                                                                   -- ~12,500
    countIf(penalty_rate_applied = true) AS penalty_applied,                                                          -- ~1,000
    countIf(dispute_filed = true) AS active_disputes,                                                                 -- ~400
    countIf(bureau_reported = true AND bureau_reported_status != payment_status) AS bureau_mismatch,                  -- ~1,500
    countIf(promo_rate IS NOT NULL AND promo_notice_sent_date IS NULL) AS missing_promo_notice                        -- ~1,250
FROM credit_card_accounts;
```

---

## 7. Pre-Staged Demo Events

These get inserted into `behavior_events` and `schema_events` by the demo trigger script. They are the second-by-second cues during the live cascade.

```json
// seed/demo_events.json
[
  {
    "scenario": "schema_enrichment_fcra",
    "label": "HEADLINE: backfill original_delinquency_date \u2192 surface FCRA 7-year violations",
    "kind": "schema_event",
    "trigger_payload": {
      "event_type": "column_populated",
      "table_name": "credit_card_accounts",
      "column_name": "original_delinquency_date",
      "event_payload_json": {
        "migration_id": "mig_2026_05_23_fcra_backfill",
        "rows_populated": 6240,
        "source": "ETL job migrating from legacy core banking system"
      }
    },
    "trigger_steps": [
      "Pick ~12% of accounts (those with payment_status in [30/60/90 days late, charge_off])",
      "Set original_delinquency_date to a random date in the past 10 years",
      "Of those, ~21% have date > 7 years ago (the violations)"
    ],
    "expected_breach_count": 1247,
    "expected_controls_to_fail": ["CTRL-FCRA-STALE-DATA"],
    "expected_demo_duration_seconds": 8
  },
  {
    "scenario": "dispute_filed_cross_trigger",
    "label": "SECONDARY: single dispute fires TILA + FCRA controls in parallel",
    "kind": "behavior_event",
    "trigger_payload": {
      "event_type": "dispute_filed",
      "account_id": "acct_002847",
      "event_payload_json": {
        "dispute_amount_usd": 1289.42,
        "merchant": "PERSEUS ONLINE LLC",
        "reason": "unauthorized_charge",
        "filed_via": "customer_portal"
      }
    },
    "trigger_steps": [
      "Pre-seed account acct_002847 with status=active, balance_usd=4200, no existing dispute",
      "INSERT INTO behavior_events the dispute_filed row",
      "Impact Analysis picks up within 500ms, fires both CTRL-TILA-DISPUTE-RESOLUTION (clock starts) and CTRL-FCRA-DISPUTE-FLAG (must flag bureau)"
    ],
    "expected_controls_to_move": ["CTRL-TILA-DISPUTE-RESOLUTION", "CTRL-FCRA-DISPUTE-FLAG"],
    "expected_demo_duration_seconds": 4
  },
  {
    "scenario": "policy_change_tila_promo_notice",
    "label": "TERTIARY (backup): TILA promo notice rule changes from 45 to 60 days",
    "kind": "policy_change",
    "trigger_payload": {
      "regulation_id": "tila_reg_z",
      "section": "12 CFR 1026.9(g)",
      "prior_version_summary": "45-day advance written notice required for promo rate expiry",
      "new_version_summary": "60-day advance written notice required for promo rate expiry (hypothetical 2026 amendment)",
      "is_material_change": true
    },
    "trigger_steps": [
      "Manually insert a row into policy_changes with the new 60-day threshold",
      "Impact Analysis re-scans the portfolio against the new threshold",
      "CTRL-TILA-PROMO-RATE-NOTICE breach_count jumps from ~1,200 (45-day baseline) to ~1,800 (60-day stricter)"
    ],
    "expected_breach_delta": 600,
    "expected_demo_duration_seconds": 6,
    "notes": "Only use this scenario if the headline schema_event demo fails. The CFPB amendment narrative is hypothetical and weaker than the schema-enrichment story."
  }
]
```

The demo trigger script (`scripts/demo_trigger.py`) loads one of these and either INSERTs the event row directly into ClickHouse (for behavior_events and schema_events) or calls the Policy Crawler with synthetic regulation text (for policy_change).

---

## 8. Load Order Script

```python
# scripts/load_seed_data.py
"""
Idempotent. Run after Docker ClickHouse is up.

Steps:
  1. Apply schema (backend/data/schema.sql)
  2. Insert issuer profile
  3. Insert 2 regulation versions
  4. Embed + insert 4 policy chunks
  5. Insert 6 compliance conditions
  6. Generate + insert 50k credit card accounts
  7. Insert 6 controls
  8. Run initial monitoring sweep (writes compliance_scans)
"""

import asyncio
import json
import sys
from pathlib import Path

from backend.data.repositories import (
    apply_schema,
    insert_issuer_profile,
    insert_regulation_versions,
    insert_policy_embeddings,
    insert_compliance_conditions,
    insert_credit_card_accounts_from_jsonl,
    insert_controls,
)
from backend.agents.monitoring import run_monitoring_sweep
from backend.integrations.vertex_ai import VertexAIClient


SEED_DIR = Path(__file__).parent.parent / "seed"


async def main():
    print("==> 1. Applying schema...")
    await apply_schema()

    print("==> 2. Inserting issuer profile...")
    profile = json.loads((SEED_DIR / "issuer_profile.json").read_text())
    await insert_issuer_profile(profile)

    print("==> 3. Inserting regulation versions...")
    regs = json.loads((SEED_DIR / "regulations.json").read_text())
    await insert_regulation_versions(regs)

    print("==> 4. Embedding policy chunks (4 chunks, ~5 seconds)...")
    chunks = json.loads((SEED_DIR / "policy_embeddings.json").read_text())
    from backend.integrations.vertex_ai import embed_text
    for chunk in chunks:
        embedding = await embed_text(
            text=chunk["chunk_text"],
            model="gemini-embedding-001",
            output_dim=768,                 # Matryoshka truncation
        )
        chunk["embedding"] = embedding
    await insert_policy_embeddings(chunks)

    print("==> 5. Inserting compliance conditions...")
    conds = json.loads((SEED_DIR / "compliance_conditions.json").read_text())
    await insert_compliance_conditions(conds)

    print("==> 6. Generating 50k credit card accounts...")
    accounts_jsonl = SEED_DIR / "credit_cards" / "accounts.jsonl"
    if not accounts_jsonl.exists():
        print("    accounts.jsonl missing -- running generate_accounts.py first")
        from seed.credit_cards.generate_accounts import main as gen_main
        gen_main()
    print("    Inserting accounts into ClickHouse...")
    await insert_credit_card_accounts_from_jsonl(accounts_jsonl)

    print("==> 7. Inserting 6 controls...")
    controls = json.loads((SEED_DIR / "controls.json").read_text())
    await insert_controls(controls)

    print("==> 8. Running initial monitoring sweep (zero LLM)...")
    summary = await run_monitoring_sweep()

    print("\n\u2713 Seed data load complete.")
    print(f"  2 regulations, 4 policy embeddings, 6 conditions, 6 controls")
    print(f"  50,000 credit card accounts")
    print(f"  Initial control statuses:")
    for control_id, scan in summary.items():
        result = scan.get("result", "?")
        breach = scan.get("breach_count", 0)
        print(f"    {control_id}: {result} ({breach} breaches)")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 9. Agent System Prompts

Each agent's system prompt lives inline in its module under `backend/agents/`:

- `backend/agents/policy_crawler.py` -- the `POLICY_CRAWLER_SYSTEM_PROMPT` constant
- `backend/agents/impact_analysis.py` -- the `IMPACT_ANALYSIS_SYSTEM_PROMPT` constant
- `backend/agents/auditor.py` -- the `AUDITOR_SYSTEM_PROMPT` constant
- `backend/agents/monitoring.py` -- no prompt (zero-LLM by design)

Prompt text is in [AGENTS.md](AGENTS.md) sections 2, 3, 4. Copy from there into the source files when implementing.

---

## AI Tool Hints

If you're an AI tool building this:

1. **Run `scripts/load_seed_data.py` before everything else.** The agents have nothing to work with until the schema is applied + accounts exist + conditions extracted.

2. **The `original_delinquency_date` column starts NULL on every account at seed time.** This is intentional. The demo trigger backfills it via a synthetic schema_event, which is what fires the headline FCRA violations cascade.

3. **Embeddings are pre-computed at seed time, not at trigger time.** This decouples the demo from live Gemini embedding latency. The Policy Crawler embeds NEW regulations live during operation; the initial 4 chunks are pre-warmed.

4. **The 6 controls all have their `check_sql` baked in.** The Monitoring Agent simply iterates `SELECT * FROM controls` and executes each `check_sql`. No LLM call needed.

5. **Verify the seeded distribution before going on stage.** Use the verification SQL in section 6. If breach numbers are off, regenerate with a different random seed or tweak the distribution constants.

6. **Don't add more regulations for the demo.** Depth > breadth at 3-minute scale. Adding TILA 1026.6, FCRA 615, etc. only dilutes the headline story without adding judgeable surface area.
