# SEED_DATA.md

Every piece of data that must be pre-loaded before the demo. With generation scripts.

---

## 1. Load Order

Run `seed/load_seed.py` which executes these in order:

1. `company_profile` -- NovaPay
2. `kg_nodes` -- data objects, regulators, jurisdictions (static taxonomy)
3. `reg_versions` -- 20 core regulations (scraped + embedded)
4. `kg_nodes` -- regulation nodes (from reg_versions)
5. `kg_edges` -- ~80 initial edges
6. `derivatives_portfolio` -- 3000 positions (synthetic)
7. `bonds_portfolio` -- 1500 positions (synthetic)
8. `lending_portfolio` -- 50,000 accounts (synthetic)
9. `controls` -- 8 pre-defined CTRL-001 through CTRL-008
10. `control_test_results` -- initial test of each control (so dashboard isn't empty)

Expected total runtime: ~3 minutes.

---

## 2. Company Profile

```json
// seed/novapay_profile.json
{
  "company_id": "novapay_demo",
  "name": "NovaPay",
  "type": "cross_border_neobank_with_treasury_and_bnpl",
  "annual_volume_usd": 2100000000,
  "employee_count": 85,
  "headquarters": "Jersey City, NJ, USA",
  "founded": 2022,
  "sponsor_bank": "Evolve Bank & Trust",
  "services": [
    "consumer_checking",
    "cross_border_remittances",
    "debit_card_visa",
    "p2p_transfers",
    "savings_accounts",
    "treasury_bond_holdings",
    "fx_hedging_derivatives",
    "bnpl_lending",
    "personal_loans"
  ],
  "customer_segments": [
    "us_consumers",
    "us_immigrants_remittance",
    "eu_consumers_beta",
    "us_smb"
  ],
  "data_objects": [
    "customer_pii",
    "customer_ssn",
    "transaction_records",
    "cross_border_transfers",
    "kyc_documents",
    "customer_communications",
    "marketing_materials",
    "sanctions_screening_logs",
    "suspicious_activity_reports",
    "vendor_data",
    "derivatives_portfolio",
    "bonds_portfolio",
    "lending_portfolio",
    "incident_logs",
    "audit_records"
  ],
  "states_operating_in": ["NY", "CA", "TX", "FL", "NJ", "IL"],
  "current_policies": {
    "incident_response_sla_hours": 72,
    "transaction_record_retention_years": 5,
    "kyc_doc_retention_years": 5,
    "current_disclosure_version": "v3",
    "im_threshold_percent": 6.0,
    "kyc_review_cadence_months": 12
  }
}
```

---

## 3. The 20 Core Regulations

Load via `seed/regulations.json` (each entry has metadata + URL to scrape).

```json
[
  {
    "regulation_id": "sec_17a4",
    "title": "SEC Rule 17a-4 -- Records To Be Preserved By Certain Exchange Members",
    "regulator": ["SEC"],
    "jurisdiction": ["us_federal"],
    "topic": ["recordkeeping"],
    "source_url": "https://www.ecfr.gov/current/title-17/chapter-II/part-240/section-240.17a-4",
    "priority": 1
  },
  {
    "regulation_id": "sec_reg_sp",
    "title": "SEC Regulation S-P -- Privacy of Consumer Financial Information",
    "regulator": ["SEC"],
    "jurisdiction": ["us_federal"],
    "topic": ["data_privacy"],
    "source_url": "https://www.ecfr.gov/current/title-17/chapter-II/part-248",
    "priority": 1
  },
  {
    "regulation_id": "sec_cyber_disclosure",
    "title": "SEC Cybersecurity Risk Management Disclosure Rule (2023)",
    "regulator": ["SEC"],
    "jurisdiction": ["us_federal"],
    "topic": ["cybersecurity_incident", "reporting_disclosure"],
    "source_url": "https://www.sec.gov/files/rules/final/2023/33-11216.pdf",
    "priority": 1
  },
  {
    "regulation_id": "sec_17a8",
    "title": "SEC Rule 17a-8 -- Financial Reports",
    "regulator": ["SEC"],
    "jurisdiction": ["us_federal"],
    "topic": ["reporting_disclosure"],
    "source_url": "https://www.ecfr.gov/current/title-17/chapter-II/part-240/section-240.17a-8",
    "priority": 2
  },
  {
    "regulation_id": "cftc_margin_rule",
    "title": "CFTC Margin Requirements for Uncleared Swaps",
    "regulator": ["CFTC"],
    "jurisdiction": ["us_federal"],
    "topic": ["margin_collateral", "swap_reporting"],
    "source_url": "https://www.ecfr.gov/current/title-17/chapter-I/part-23/subpart-E",
    "priority": 1
  },
  {
    "regulation_id": "cftc_swap_reporting",
    "title": "CFTC Swap Data Reporting (Part 45)",
    "regulator": ["CFTC"],
    "jurisdiction": ["us_federal"],
    "topic": ["swap_reporting", "reporting_disclosure"],
    "source_url": "https://www.ecfr.gov/current/title-17/chapter-I/part-45",
    "priority": 2
  },
  {
    "regulation_id": "cftc_position_limits",
    "title": "CFTC Position Limits for Derivatives",
    "regulator": ["CFTC"],
    "jurisdiction": ["us_federal"],
    "topic": ["margin_collateral"],
    "source_url": "https://www.ecfr.gov/current/title-17/chapter-I/part-150",
    "priority": 2
  },
  {
    "regulation_id": "finra_3110",
    "title": "FINRA Rule 3110 -- Supervision",
    "regulator": ["FINRA"],
    "jurisdiction": ["us_federal"],
    "topic": ["conduct_governance"],
    "source_url": "https://www.finra.org/rules-guidance/rulebooks/finra-rules/3110",
    "priority": 2
  },
  {
    "regulation_id": "finra_4511",
    "title": "FINRA Rule 4511 -- General Requirements (Recordkeeping)",
    "regulator": ["FINRA"],
    "jurisdiction": ["us_federal"],
    "topic": ["recordkeeping"],
    "source_url": "https://www.finra.org/rules-guidance/rulebooks/finra-rules/4511",
    "priority": 2
  },
  {
    "regulation_id": "finra_trace",
    "title": "FINRA TRACE Reporting Rules",
    "regulator": ["FINRA"],
    "jurisdiction": ["us_federal"],
    "topic": ["reporting_disclosure"],
    "source_url": "https://www.finra.org/filing-reporting/trace",
    "priority": 3
  },
  {
    "regulation_id": "fincen_bsa",
    "title": "Bank Secrecy Act -- General Provisions",
    "regulator": ["FinCEN"],
    "jurisdiction": ["us_federal"],
    "topic": ["aml_kyc", "recordkeeping"],
    "source_url": "https://www.fincen.gov/resources/statutes-regulations/bank-secrecy-act",
    "priority": 1
  },
  {
    "regulation_id": "fincen_cdd",
    "title": "FinCEN Customer Due Diligence Rule",
    "regulator": ["FinCEN"],
    "jurisdiction": ["us_federal"],
    "topic": ["aml_kyc"],
    "source_url": "https://www.fincen.gov/resources/statutes-regulations/cdd-final-rule",
    "priority": 1
  },
  {
    "regulation_id": "fincen_sar",
    "title": "FinCEN Suspicious Activity Report Filing Requirements",
    "regulator": ["FinCEN"],
    "jurisdiction": ["us_federal"],
    "topic": ["aml_kyc", "reporting_disclosure"],
    "source_url": "https://www.fincen.gov/resources/filing-information",
    "priority": 1
  },
  {
    "regulation_id": "cfpb_reg_e",
    "title": "Regulation E -- Electronic Fund Transfers",
    "regulator": ["CFPB"],
    "jurisdiction": ["us_federal"],
    "topic": ["consumer_protection"],
    "source_url": "https://www.ecfr.gov/current/title-12/chapter-X/part-1005",
    "priority": 1
  },
  {
    "regulation_id": "cfpb_reg_z",
    "title": "Regulation Z -- Truth in Lending Act",
    "regulator": ["CFPB"],
    "jurisdiction": ["us_federal"],
    "topic": ["consumer_protection", "lending_credit"],
    "source_url": "https://www.ecfr.gov/current/title-12/chapter-X/part-1026",
    "priority": 1
  },
  {
    "regulation_id": "cfpb_udaap",
    "title": "CFPB UDAAP Guidance",
    "regulator": ["CFPB"],
    "jurisdiction": ["us_federal"],
    "topic": ["consumer_protection", "advertising_marketing"],
    "source_url": "https://www.consumerfinance.gov/compliance/supervisory-guidance/",
    "priority": 2
  },
  {
    "regulation_id": "occ_third_party",
    "title": "OCC Bulletin 2013-29 -- Third-Party Risk Management",
    "regulator": ["OCC"],
    "jurisdiction": ["us_federal"],
    "topic": ["third_party_vendor"],
    "source_url": "https://www.occ.gov/news-issuances/bulletins/2013/bulletin-2013-29.html",
    "priority": 2
  },
  {
    "regulation_id": "ccpa_cpra",
    "title": "California Consumer Privacy Act (as amended by CPRA)",
    "regulator": ["STATE_CA"],
    "jurisdiction": ["us_state_ca"],
    "topic": ["data_privacy", "consumer_protection"],
    "source_url": "https://oag.ca.gov/privacy/ccpa",
    "priority": 1
  },
  {
    "regulation_id": "ny_dfs_500",
    "title": "NY DFS 23 NYCRR 500 -- Cybersecurity Requirements",
    "regulator": ["STATE_NY"],
    "jurisdiction": ["us_state_ny"],
    "topic": ["cybersecurity_incident"],
    "source_url": "https://www.dfs.ny.gov/industry_guidance/cybersecurity",
    "priority": 1
  },
  {
    "regulation_id": "gdpr_core",
    "title": "EU GDPR -- Core Articles 6, 17, 44",
    "regulator": ["EU_COMMISSION"],
    "jurisdiction": ["eu"],
    "topic": ["data_privacy", "cross_border_payments"],
    "source_url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
    "priority": 1
  }
]
```

### Loading Algorithm

```python
# seed/load_seed.py (excerpt)

async def load_regulations(client):
    """Fetch + embed + insert all regulations."""
    from backend.integrations.nimble_client import NimbleClient
    from backend.integrations.firecrawl_client import FirecrawlClient
    from backend.integrations.vertex_ai import VertexAIClient
    
    regs = json.loads(Path("seed/regulations.json").read_text())
    nimble = NimbleClient()
    firecrawl = FirecrawlClient()
    vertex = VertexAIClient()
    
    for reg in regs:
        # 1. Scrape (Nimble primary, Firecrawl fallback)
        try:
            text = await nimble.fetch_url_text(reg["source_url"])
        except Exception:
            text = await firecrawl.fetch_url_text(reg["source_url"])
        
        # 2. Embed
        embedding = await vertex.embed(text[:8000])
        
        # 3. Insert
        await client.insert(
            "regradar.reg_versions",
            {
                "version_id": str(uuid7()),
                "regulation_id": reg["regulation_id"],
                "source_url": reg["source_url"],
                "source_name": "seed",
                "fetched_at": now(),
                "title": reg["title"],
                "text": text,
                "text_hash": sha256(text),
                "embedding": embedding,
                "metadata": json.dumps(reg),
                "change_type": "new_regulation",
                "is_latest": 1,
            }
        )
        
        # 4. Also insert a kg_node for this regulation
        await client.insert(
            "regradar.kg_nodes",
            {
                "node_id": reg["regulation_id"],
                "node_type": "regulation",
                "name": reg["title"],
                "metadata": json.dumps(reg),
                "embedding": embedding,
                "source_url": reg["source_url"],
                "created_at": now(),
                "updated_at": now(),
            }
        )
```

---

## 4. Initial KG Edges (~80)

```json
// seed/kg_edges.json (excerpt -- full file has all ~80)
[
  {
    "source_id": "customer_pii",
    "target_id": "ccpa_cpra",
    "edge_type": "applies_to",
    "confidence": 0.99,
    "reasoning": "CCPA explicitly governs personal information"
  },
  {
    "source_id": "customer_pii",
    "target_id": "gdpr_core",
    "edge_type": "applies_to",
    "confidence": 0.95,
    "reasoning": "GDPR applies to PII when EU residents are served"
  },
  {
    "source_id": "customer_pii",
    "target_id": "sec_reg_sp",
    "edge_type": "applies_to",
    "confidence": 0.92,
    "reasoning": "Reg S-P covers consumer financial information privacy"
  },
  {
    "source_id": "customer_pii",
    "target_id": "ny_dfs_500",
    "edge_type": "applies_to",
    "confidence": 0.90,
    "reasoning": "NY DFS 500 requires PII protection for covered entities"
  },
  {
    "source_id": "transaction_records",
    "target_id": "fincen_bsa",
    "edge_type": "applies_to",
    "confidence": 0.99,
    "reasoning": "BSA mandates transaction recordkeeping"
  },
  {
    "source_id": "transaction_records",
    "target_id": "sec_17a4",
    "edge_type": "applies_to",
    "confidence": 0.97,
    "reasoning": "17a-4 requires preservation of transaction records"
  },
  {
    "source_id": "transaction_records",
    "target_id": "finra_4511",
    "edge_type": "applies_to",
    "confidence": 0.95
  },
  {
    "source_id": "cross_border_transfers",
    "target_id": "fincen_bsa",
    "edge_type": "applies_to",
    "confidence": 0.99
  },
  {
    "source_id": "cross_border_transfers",
    "target_id": "fincen_sar",
    "edge_type": "applies_to",
    "confidence": 0.98
  },
  {
    "source_id": "cross_border_transfers",
    "target_id": "cfpb_reg_e",
    "edge_type": "applies_to",
    "confidence": 0.93
  },
  {
    "source_id": "kyc_documents",
    "target_id": "fincen_cdd",
    "edge_type": "applies_to",
    "confidence": 0.99
  },
  {
    "source_id": "kyc_documents",
    "target_id": "fincen_bsa",
    "edge_type": "applies_to",
    "confidence": 0.96
  },
  {
    "source_id": "derivatives_portfolio",
    "target_id": "cftc_margin_rule",
    "edge_type": "applies_to",
    "confidence": 0.99,
    "reasoning": "CFTC margin rule governs uncleared derivative positions"
  },
  {
    "source_id": "derivatives_portfolio",
    "target_id": "cftc_swap_reporting",
    "edge_type": "applies_to",
    "confidence": 0.97
  },
  {
    "source_id": "derivatives_portfolio",
    "target_id": "cftc_position_limits",
    "edge_type": "applies_to",
    "confidence": 0.85
  },
  {
    "source_id": "bonds_portfolio",
    "target_id": "finra_trace",
    "edge_type": "applies_to",
    "confidence": 0.95
  },
  {
    "source_id": "bonds_portfolio",
    "target_id": "sec_17a4",
    "edge_type": "applies_to",
    "confidence": 0.90
  },
  {
    "source_id": "lending_portfolio",
    "target_id": "cfpb_reg_z",
    "edge_type": "applies_to",
    "confidence": 0.99
  },
  {
    "source_id": "lending_portfolio",
    "target_id": "cfpb_reg_e",
    "edge_type": "applies_to",
    "confidence": 0.88
  },
  {
    "source_id": "lending_portfolio",
    "target_id": "cfpb_udaap",
    "edge_type": "applies_to",
    "confidence": 0.85
  },
  {
    "source_id": "incident_logs",
    "target_id": "sec_cyber_disclosure",
    "edge_type": "applies_to",
    "confidence": 0.96
  },
  {
    "source_id": "incident_logs",
    "target_id": "ny_dfs_500",
    "edge_type": "applies_to",
    "confidence": 0.94
  },
  {
    "source_id": "sanctions_screening_logs",
    "target_id": "fincen_bsa",
    "edge_type": "applies_to",
    "confidence": 0.92
  },
  {
    "source_id": "vendor_data",
    "target_id": "occ_third_party",
    "edge_type": "applies_to",
    "confidence": 0.99
  }
]
```

**Continue with remaining edges:** for each data object, include all relevant edges. Target ~80 total to give the demo density.

---

## 5. The 8 Pre-Defined Controls

```json
// seed/controls.json
[
  {
    "control_id": "CTRL-001",
    "name": "IM Adequacy on Uncleared IR Swaps",
    "description": "Initial margin must be >= 6% of notional on uncleared interest rate swaps",
    "regulation_ids": ["cftc_margin_rule"],
    "metric": "initial_margin",
    "threshold_value": 0.06,
    "threshold_operator": "gte",
    "threshold_unit": "percent_notional",
    "test_sql": "SELECT count() FROM regradar.derivatives_portfolio WHERE instrument_type='IR_SWAP' AND cleared=0 AND margin_ratio < 0.06 AND status='active'",
    "owner_team": "risk_team",
    "test_frequency": "daily",
    "current_status": "PASSING"
  },
  {
    "control_id": "CTRL-002",
    "name": "Cyber Incident Disclosure SLA",
    "description": "Cybersecurity incidents must be disclosed within 96 hours (per SEC)",
    "regulation_ids": ["sec_cyber_disclosure", "ny_dfs_500"],
    "metric": "incident_disclosure_hours",
    "threshold_value": 96,
    "threshold_operator": "lte",
    "threshold_unit": "hours",
    "test_sql": "SELECT count() FROM regradar.audit_trail WHERE event_type='incident_logged' AND duration_ms > 96*3600*1000",
    "owner_team": "security_team",
    "test_frequency": "realtime",
    "current_status": "AT_RISK"
  },
  {
    "control_id": "CTRL-003",
    "name": "OFAC Sanctions Screening Coverage",
    "description": "100% of cross-border transfers must be screened against OFAC SDN list",
    "regulation_ids": ["fincen_bsa"],
    "metric": "screening_coverage_pct",
    "threshold_value": 100.0,
    "threshold_operator": "gte",
    "threshold_unit": "percent",
    "test_sql": "SELECT 100.0 * sum(if(screened, 1, 0)) / count() FROM regradar.audit_trail WHERE event_type='cross_border_transfer'",
    "owner_team": "compliance_team",
    "test_frequency": "hourly",
    "current_status": "PASSING"
  },
  {
    "control_id": "CTRL-004",
    "name": "Transaction Record 6-Year Retention",
    "description": "Transaction records must be retained for at least 6 years (FINRA 4511, SEC 17a-4)",
    "regulation_ids": ["sec_17a4", "finra_4511"],
    "metric": "oldest_required_record_age_years",
    "threshold_value": 6.0,
    "threshold_operator": "gte",
    "threshold_unit": "years",
    "test_sql": "SELECT datediff('year', min(created_at), now()) FROM regradar.audit_trail WHERE event_type IN ('transaction_recorded')",
    "owner_team": "operations_team",
    "test_frequency": "daily",
    "current_status": "PASSING"
  },
  {
    "control_id": "CTRL-005",
    "name": "BSA/AML CDD Annual Review",
    "description": "Customer due diligence reviews must occur at least annually",
    "regulation_ids": ["fincen_cdd"],
    "metric": "max_days_since_cdd_review",
    "threshold_value": 365,
    "threshold_operator": "lte",
    "threshold_unit": "days",
    "test_sql": "SELECT max(datediff('day', last_cdd_review, now())) FROM customer_profile",
    "owner_team": "compliance_team",
    "test_frequency": "weekly",
    "current_status": "PASSING"
  },
  {
    "control_id": "CTRL-006",
    "name": "CFPB BNPL Disclosure Currency",
    "description": "All active BNPL accounts must use the current disclosure version",
    "regulation_ids": ["cfpb_reg_z", "cfpb_udaap"],
    "metric": "stale_disclosure_accounts",
    "threshold_value": 0,
    "threshold_operator": "eq",
    "threshold_unit": "count",
    "test_sql": "SELECT count() FROM regradar.lending_portfolio WHERE product_type='BNPL' AND status='active' AND disclosure_version != 'v3'",
    "owner_team": "legal_team",
    "test_frequency": "daily",
    "current_status": "FAILING"
  },
  {
    "control_id": "CTRL-007",
    "name": "GDPR Data Subject Request SLA",
    "description": "DSAR responses must complete within 30 days",
    "regulation_ids": ["gdpr_core"],
    "metric": "dsar_max_open_days",
    "threshold_value": 30,
    "threshold_operator": "lte",
    "threshold_unit": "days",
    "test_sql": "SELECT max(datediff('day', request_date, now())) FROM dsar_requests WHERE status='open'",
    "owner_team": "privacy_team",
    "test_frequency": "daily",
    "current_status": "PASSING"
  },
  {
    "control_id": "CTRL-008",
    "name": "NY DFS Annual Cybersecurity Certification",
    "description": "Annual cybersecurity certification must be filed by April 15 each year",
    "regulation_ids": ["ny_dfs_500"],
    "metric": "days_until_dfs_cert_deadline",
    "threshold_value": 0,
    "threshold_operator": "gt",
    "threshold_unit": "days",
    "test_sql": "SELECT datediff('day', now(), '2027-04-15')",
    "owner_team": "security_team",
    "test_frequency": "monthly",
    "current_status": "PASSING"
  }
]
```

---

## 6. Synthetic Portfolio Generator

```python
# seed/generate_portfolios.py

import json
import numpy as np
from faker import Faker
from datetime import datetime, timedelta
from uuid import uuid4
from pathlib import Path

fake = Faker()
np.random.seed(42)
Faker.seed(42)

# ====== DERIVATIVES (3000 positions) ======

INSTRUMENT_TYPES = ["IR_SWAP", "CDS", "FX_FORWARD", "OPTION"]
INSTRUMENT_WEIGHTS = [0.67, 0.13, 0.17, 0.03]

COUNTERPARTIES = [
    f"{c} {s}" for c in ["Bank", "Capital", "Securities", "Markets"]
    for s in ["Goldman", "JPMorgan", "Citi", "Barclays", "Deutsche",
              "Nomura", "HSBC", "UBS", "BNP", "Wells", "BofA", "RBC"]
][:50]
COUNTERPARTY_RATINGS = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"]

def gen_derivative():
    inst_type = np.random.choice(INSTRUMENT_TYPES, p=INSTRUMENT_WEIGHTS)
    notional = float(np.random.lognormal(mean=14, sigma=2))
    margin_ratio = float(np.clip(np.random.normal(0.075, 0.025), 0.01, 0.30))
    margin_posted = notional * margin_ratio
    trade_date = fake.date_between(start_date="-2y", end_date="today")
    maturity_date = trade_date + timedelta(days=np.random.randint(180, 7 * 365))
    
    record = {
        "instrument_id": str(uuid4()),
        "instrument_type": inst_type,
        "notional_usd": round(notional, 2),
        "market_value_usd": round(notional * np.random.uniform(0.95, 1.05), 2),
        "margin_posted_usd": round(margin_posted, 2),
        "margin_ratio": round(margin_ratio, 4),
        "counterparty": str(np.random.choice(COUNTERPARTIES)),
        "counterparty_rating": str(np.random.choice(COUNTERPARTY_RATINGS)),
        "cleared": int(np.random.random() < 0.30),
        "clearinghouse": "LCH" if np.random.random() < 0.30 else None,
        "jurisdiction": str(np.random.choice(["us_federal", "eu", "uk"], p=[0.80, 0.15, 0.05])),
        "trade_date": trade_date.isoformat(),
        "maturity_date": maturity_date.isoformat(),
        "status": "active",
    }
    
    if inst_type == "FX_FORWARD":
        record["fx_pair"] = str(np.random.choice(
            ["EUR/USD", "USD/JPY", "GBP/USD", "USD/CHF", "USD/CAD"]
        ))
    elif inst_type == "OPTION":
        record["underlying"] = fake.ticker()
        record["strike_usd"] = round(notional * np.random.uniform(0.9, 1.1) / 100, 2)
        record["option_type"] = str(np.random.choice(["call", "put"]))
    
    return record


def generate_derivatives(n=3000):
    return [gen_derivative() for _ in range(n)]


# ====== BONDS (1500 positions) ======

BOND_TYPES = ["corporate", "municipal", "treasury", "agency"]
BOND_WEIGHTS = [0.47, 0.27, 0.17, 0.09]
CREDIT_RATINGS = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB"]
CREDIT_WEIGHTS = [0.15, 0.10, 0.10, 0.05, 0.10, 0.15, 0.05, 0.10, 0.07, 0.03, 0.05, 0.05]

PAYMENT_FREQ = ["monthly", "quarterly", "semi_annual", "annual"]

def gen_bond():
    bond_type = np.random.choice(BOND_TYPES, p=BOND_WEIGHTS)
    par = float(np.random.lognormal(mean=14, sigma=1.5))
    coupon = float(np.clip(np.random.normal(0.045, 0.015), 0.005, 0.12))
    issue_date = fake.date_between(start_date="-5y", end_date="-1y")
    maturity_date = issue_date + timedelta(days=np.random.randint(2 * 365, 30 * 365))
    
    return {
        "position_id": str(uuid4()),
        "cusip": "".join(np.random.choice(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"), 9)),
        "issuer": fake.company(),
        "bond_type": bond_type,
        "par_value_usd": round(par, 2),
        "market_value_usd": round(par * np.random.uniform(0.92, 1.08), 2),
        "purchase_price_usd": round(par * np.random.uniform(0.95, 1.02), 2),
        "coupon_rate": round(coupon, 4),
        "payment_frequency": str(np.random.choice(PAYMENT_FREQ)),
        "credit_rating": str(np.random.choice(CREDIT_RATINGS, p=CREDIT_WEIGHTS)),
        "jurisdiction": str(np.random.choice(["us_federal", "us_state_ca", "us_state_ny", "us_state_tx"])),
        "tax_exempt": int(bond_type == "municipal" and np.random.random() < 0.7),
        "issue_date": issue_date.isoformat(),
        "maturity_date": maturity_date.isoformat(),
        "status": "held",
    }


def generate_bonds(n=1500):
    return [gen_bond() for _ in range(n)]


# ====== LENDING (50,000 accounts) ======

STATE_WEIGHTS = {
    "CA": 0.12, "TX": 0.09, "FL": 0.07, "NY": 0.06,
    "PA": 0.04, "IL": 0.04, "OH": 0.04, "GA": 0.03,
    "NC": 0.03, "MI": 0.03, "NJ": 0.03,
    # ... rest distributed
}

def gen_lending():
    product = np.random.choice(["BNPL", "PERSONAL_LOAN", "AUTO_LOAN"], p=[0.70, 0.25, 0.05])
    principal = float(np.random.lognormal(mean=6.5, sigma=1.5))
    apr = float(np.clip(np.random.normal(0.18, 0.08), 0.02, 0.36))
    term = int(np.random.choice([3, 6, 12, 24, 36, 48, 60]))
    payments_made = int(np.random.uniform(0, term))
    outstanding = principal * (1 - payments_made / term) if payments_made < term else 0
    
    status = np.random.choice(
        ["active", "paid_off", "delinquent", "charged_off"],
        p=[0.85, 0.08, 0.05, 0.02]
    )
    disclosure_version = np.random.choice(["v3", "v2", "v1"], p=[0.60, 0.30, 0.10])
    state = np.random.choice(list(STATE_WEIGHTS.keys()),
                             p=list(STATE_WEIGHTS.values()))
    origination_date = fake.date_between(start_date="-3y", end_date="today")
    
    return {
        "account_id": str(uuid4()),
        "customer_id": str(uuid4()),
        "product_type": str(product),
        "principal_usd": round(principal, 2),
        "outstanding_usd": round(outstanding, 2),
        "apr": round(apr, 4),
        "term_months": term,
        "payments_made": payments_made,
        "status": str(status),
        "origination_date": origination_date.isoformat(),
        "state": str(state),
        "disclosure_version": str(disclosure_version),
        "last_payment_date": (origination_date + timedelta(days=payments_made * 30)).isoformat() if payments_made > 0 else None,
        "next_payment_date": (origination_date + timedelta(days=(payments_made + 1) * 30)).isoformat() if status == "active" else None,
    }


def generate_lending(n=50_000):
    return [gen_lending() for _ in range(n)]


# ====== MAIN ======

def main():
    out_dir = Path(__file__).parent / "portfolios"
    out_dir.mkdir(exist_ok=True)
    
    print("Generating derivatives (3000)...")
    (out_dir / "derivatives.json").write_text(
        json.dumps(generate_derivatives(3000), indent=2)
    )
    
    print("Generating bonds (1500)...")
    (out_dir / "bonds.json").write_text(
        json.dumps(generate_bonds(1500), indent=2)
    )
    
    print("Generating lending (50000)...")
    # Lending is too big for JSON readability -- use JSONL
    with open(out_dir / "lending.jsonl", "w") as f:
        for row in generate_lending(50_000):
            f.write(json.dumps(row) + "\n")
    
    print("Done. Files written to seed/portfolios/")


if __name__ == "__main__":
    main()
```

---

## 7. Pre-Staged Demo Events

These regulations get inserted INTO `reg_versions` as "previous version" so when the demo "triggers" them, the diff is real.

```json
// seed/demo_events.json
[
  {
    "scenario": "cftc_margin_amendment",
    "previous_version": {
      "regulation_id": "cftc_margin_rule",
      "text_contains": "initial margin requirement of 6 percent"
    },
    "new_version": {
      "regulation_id": "cftc_margin_rule",
      "title": "CFTC Margin Requirements for Uncleared Swaps (2026 Amendment)",
      "summary": "Amendment increases initial margin requirement on uncleared IR swaps from 6% to 8% of notional value. Effective in 60 days.",
      "text_changes": "...replaces 'initial margin requirement of 6 percent' with 'initial margin requirement of 8 percent'...",
      "change_type": "reg_amended",
      "expected_severity": "HIGH",
      "expected_threshold_changes": [
        {"metric": "initial_margin", "old": 0.06, "new": 0.08, "unit": "percent_notional"}
      ]
    }
  },
  {
    "scenario": "sec_cyber_disclosure",
    "new_version": {
      "regulation_id": "sec_cyber_disclosure_v2",
      "title": "SEC Cybersecurity Disclosure Update -- Material Incident SLA Tightened",
      "summary": "SLA for material cybersecurity incident disclosure reduced from 96 hours to 72 hours.",
      "change_type": "reg_amended",
      "expected_severity": "HIGH",
      "expected_threshold_changes": [
        {"metric": "incident_disclosure_hours", "old": 96, "new": 72, "unit": "hours"}
      ]
    }
  },
  {
    "scenario": "ofac_sanctions_add",
    "new_version": {
      "regulation_id": "ofac_sdn_2026_05_23",
      "title": "OFAC SDN List Update -- New Entities Added",
      "summary": "12 new entities added to OFAC Specially Designated Nationals list across Russia and Iran-linked operations.",
      "change_type": "new_regulation",
      "expected_severity": "CRITICAL"
    }
  },
  {
    "scenario": "ny_dfs_amendment",
    "new_version": {
      "regulation_id": "ny_dfs_500_2026_amendment",
      "title": "NY DFS Part 500 Amendment -- Expanded Covered Entities",
      "summary": "Amendment expands covered entity definition to include fintechs with NY customer base > 1000.",
      "change_type": "reg_amended",
      "expected_severity": "HIGH"
    }
  },
  {
    "scenario": "cfpb_disclosure_update",
    "new_version": {
      "regulation_id": "cfpb_bnpl_disclosure_v4",
      "title": "CFPB BNPL Disclosure Form -- Version 4 Issued",
      "summary": "Updated disclosure form replaces v3 for all BNPL accounts. Compliance required within 90 days.",
      "change_type": "reg_amended",
      "expected_severity": "MEDIUM"
    }
  }
]
```

The demo trigger endpoint (`POST /api/demo/trigger`) loads one of these and posts to the blackboard.

---

## 8. The Load Order Script

```python
# seed/load_seed.py
"""
Idempotent. Run after setup_clickhouse.py.
"""
import asyncio
import json
import os
from pathlib import Path
import clickhouse_connect
from backend.integrations.vertex_ai import VertexAIClient
from backend.integrations.nimble_client import NimbleClient
from backend.integrations.firecrawl_client import FirecrawlClient
from backend.utils.hashing import hash_document, now_dt

ROOT = Path(__file__).parent


async def main():
    client = clickhouse_connect.get_async_client(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.environ.get("CLICKHOUSE_PORT", 8443)),
        username=os.environ["CLICKHOUSE_USER"],
        password=os.environ["CLICKHOUSE_PASSWORD"],
        secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
    )
    
    # 1. Company profile
    print("Loading company profile...")
    profile = json.loads((ROOT / "novapay_profile.json").read_text())
    await load_company(client, profile)
    
    # 2. Static taxonomy nodes (data_objects, regulators, jurisdictions)
    print("Loading taxonomy nodes...")
    await load_taxonomy_nodes(client, profile)
    
    # 3. Regulations (scrape + embed + insert)
    print("Loading 20 regulations (scraping + embedding -- takes ~2 min)...")
    regs = json.loads((ROOT / "regulations.json").read_text())
    await load_regulations(client, regs)
    
    # 4. KG edges
    print("Loading initial KG edges...")
    edges = json.loads((ROOT / "kg_edges.json").read_text())
    await load_edges(client, edges)
    
    # 5. Portfolios -- check if already generated
    portfolios_dir = ROOT / "portfolios"
    if not portfolios_dir.exists():
        print("Generating synthetic portfolios first...")
        from seed.generate_portfolios import main as gen_main
        gen_main()
    
    print("Loading derivatives portfolio...")
    await load_derivatives(client, portfolios_dir / "derivatives.json")
    
    print("Loading bonds portfolio...")
    await load_bonds(client, portfolios_dir / "bonds.json")
    
    print("Loading lending portfolio (50k rows -- takes a minute)...")
    await load_lending(client, portfolios_dir / "lending.jsonl")
    
    # 6. Controls
    print("Loading 8 governance controls...")
    controls = json.loads((ROOT / "controls.json").read_text())
    await load_controls(client, controls)
    
    # 7. Initial control test
    print("Running initial control tests...")
    await test_all_controls(client, controls)
    
    print("\n✓ Seed data load complete.")
    print(f"  Regulations: {len(regs)}")
    print(f"  KG edges: {len(edges)}")
    print(f"  Controls: {len(controls)}")
    print(f"  Portfolios: 3000 derivatives + 1500 bonds + 50000 lending")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 9. Agent System Prompts -- File References

Each agent loads its prompt from `backend/agents/prompts/<agent_id>.txt`. Prompts must be saved as plain text exactly as written in [AGENTS.md](AGENTS.md) -- or copy from the Master Plan PDF Part VII.

Files required:
- `backend/agents/prompts/classifier.txt`
- `backend/agents/prompts/mapper.txt`
- `backend/agents/prompts/analyst.txt`
- `backend/agents/prompts/advisor.txt`
- `backend/agents/prompts/auditor.txt`

(The Watcher has no prompt.)

---

Read [INTEGRATIONS.md](INTEGRATIONS.md) next.
