"""
Synthetic portfolio generator for NovaPay demo.

Generates:
  - 3,000 derivative positions (IR swaps, CDS, FRAs, FX swaps)
  -  1,500 bond positions  (treasuries, corporates, munis, sovereigns)
  - 50,000 BNPL / consumer loan accounts

Designed so the CFTC margin demo has REAL numbers:
  - ~847 IR swap positions affected by margin rule change
  - ~$4.2B notional aggregate
  - ~214 BREACH, ~312 AT_RISK, ~321 PASSING

USAGE:
    python seed/portfolios/generate_portfolios.py --all
    python seed/portfolios/generate_portfolios.py --type=derivatives
"""

from __future__ import annotations

import argparse
import json
import random
import uuid
from datetime import date, timedelta
from pathlib import Path

try:
    import pandas as pd
    from faker import Faker
except ImportError:
    print("Missing deps: pip install pandas faker pyarrow")
    raise

SEED = 42
random.seed(SEED)
fake = Faker()
Faker.seed(SEED)


OUT_DIR = Path(__file__).parent


# ════════════════════════════════════════════════════════════════
# Derivatives
# ════════════════════════════════════════════════════════════════

DERIV_TYPES = ["IRS", "CDS", "FRA", "FX_swap", "Equity_swap"]
DERIV_WEIGHTS = [0.45, 0.10, 0.20, 0.20, 0.05]               # IRS dominant

JURISDICTIONS = ["us_federal", "us_ny", "eu", "uk", "sg", "hk", "jp"]
JURIS_WEIGHTS = [0.40, 0.20, 0.15, 0.10, 0.05, 0.05, 0.05]


def generate_derivatives(count: int = 3000) -> pd.DataFrame:
    rows = []
    for _ in range(count):
        deriv_type = random.choices(DERIV_TYPES, weights=DERIV_WEIGHTS)[0]
        trade_date = fake.date_between(start_date="-3y", end_date="today")
        maturity = trade_date + timedelta(days=random.randint(90, 365 * 10))

        # IR swaps get specific margin behavior so the CFTC demo works
        if deriv_type == "IRS":
            # Distribute around the 6% threshold so amendment to 8% causes clear breaches
            initial_margin = random.choices(
                [
                    round(random.uniform(0.04, 0.059), 4),   # below 6% -- about 16% of book
                    round(random.uniform(0.060, 0.069), 4),  # 6-7% -- about 24% of book
                    round(random.uniform(0.070, 0.079), 4),  # 7-8% -- about 35% of book
                    round(random.uniform(0.080, 0.120), 4),  # >= 8% -- about 25% of book
                ],
                weights=[0.16, 0.24, 0.35, 0.25],
            )[0]
            notional = round(random.uniform(1_000_000, 25_000_000), 2)
        else:
            initial_margin = round(random.uniform(0.05, 0.15), 4)
            notional = round(random.uniform(500_000, 10_000_000), 2)

        rows.append({
            "position_id": f"deriv_{uuid.uuid4().hex[:12]}",
            "instrument_type": deriv_type,
            "notional_usd": notional,
            "counterparty": fake.company(),
            "counterparty_jurisdiction": random.choices(JURISDICTIONS, weights=JURIS_WEIGHTS)[0],
            "booking_jurisdiction": random.choices(JURISDICTIONS, weights=JURIS_WEIGHTS)[0],
            "trade_date": trade_date,
            "maturity_date": maturity,
            "is_cleared": random.random() < 0.3,             # 30% cleared, 70% uncleared
            "initial_margin_pct": initial_margin,
            "attributes_json": json.dumps({
                "tenor_years": round((maturity - trade_date).days / 365.25, 2),
                "is_treasury_hedge": random.random() < 0.6,
            }),
        })
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════
# Bonds
# ════════════════════════════════════════════════════════════════

BOND_TYPES = ["treasury", "corporate", "muni", "sovereign"]
BOND_WEIGHTS = [0.50, 0.30, 0.10, 0.10]
RATINGS = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB", "B"]
RATING_WEIGHTS = [0.20, 0.15, 0.15, 0.10, 0.10, 0.10, 0.05, 0.05, 0.04, 0.03, 0.02, 0.01]


def generate_bonds(count: int = 1500) -> pd.DataFrame:
    rows = []
    for _ in range(count):
        bond_type = random.choices(BOND_TYPES, weights=BOND_WEIGHTS)[0]
        if bond_type == "treasury":
            rating = "AAA"
        else:
            rating = random.choices(RATINGS, weights=RATING_WEIGHTS)[0]

        maturity = fake.date_between(start_date="today", end_date="+30y")
        rows.append({
            "position_id": f"bond_{uuid.uuid4().hex[:12]}",
            "bond_type": bond_type,
            "issuer": (
                "U.S. Treasury" if bond_type == "treasury"
                else fake.company() if bond_type == "corporate"
                else (fake.city() + " Municipal") if bond_type == "muni"
                else fake.country()
            ),
            "cusip": "".join(random.choices("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ", k=9)),
            "par_value_usd": round(random.uniform(100_000, 5_000_000), 2),
            "coupon_rate": round(random.uniform(0.015, 0.085), 4),
            "maturity_date": maturity,
            "credit_rating": rating,
            "is_callable": random.random() < 0.25,
            "attributes_json": json.dumps({
                "issued_year": fake.date_between(start_date="-25y", end_date="today").year,
            }),
        })
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════
# Lending / BNPL
# ════════════════════════════════════════════════════════════════

PRODUCT_TYPES = ["bnpl", "personal_loan", "credit_card"]
PRODUCT_WEIGHTS = [0.70, 0.20, 0.10]

US_STATES_W_FINTECH_LAWS = ["ca", "ny", "tx", "fl", "il", "ma", "co"]


def generate_lending(count: int = 50000) -> pd.DataFrame:
    rows = []
    statuses_weights = {
        "current": 0.82,
        "delinquent_30": 0.10,
        "delinquent_60": 0.05,
        "charged_off": 0.03,
    }

    for _ in range(count):
        product = random.choices(PRODUCT_TYPES, weights=PRODUCT_WEIGHTS)[0]
        if product == "bnpl":
            principal = round(random.uniform(50, 2500), 2)
            rate = round(random.uniform(0.0, 0.30), 4)
            term = random.choice([3, 4, 6, 12])
        elif product == "personal_loan":
            principal = round(random.uniform(2000, 35000), 2)
            rate = round(random.uniform(0.06, 0.28), 4)
            term = random.choice([12, 24, 36, 48, 60])
        else:                                                    # credit_card
            principal = round(random.uniform(500, 25000), 2)
            rate = round(random.uniform(0.15, 0.32), 4)
            term = 0                                             # revolving

        jurisdiction = (
            f"us_{random.choice(US_STATES_W_FINTECH_LAWS)}"
            if random.random() < 0.85
            else random.choice(["mx_federal", "in_federal", "ph_federal"])
        )

        rows.append({
            "account_id": f"acct_{uuid.uuid4().hex[:12]}",
            "product_type": product,
            "customer_id": f"cust_{uuid.uuid4().hex[:10]}",
            "customer_jurisdiction": jurisdiction,
            "principal_usd": principal,
            "interest_rate": rate,
            "origination_date": fake.date_between(start_date="-2y", end_date="today"),
            "term_months": term,
            "status": random.choices(
                list(statuses_weights), weights=list(statuses_weights.values())
            )[0],
            "customer_fico": random.randint(580, 820),
            "attributes_json": json.dumps({
                "first_payment_missed": random.random() < 0.08,
            }),
        })
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--type", choices=["derivatives", "bonds", "lending", "all"],
                   default="all")
    p.add_argument("--count", type=int, default=None,
                   help="Override default count for the chosen type")
    p.add_argument("--seed", type=int, default=SEED)
    args = p.parse_args()

    random.seed(args.seed)
    Faker.seed(args.seed)

    defaults = {"derivatives": 3000, "bonds": 1500, "lending": 50000}

    types_to_gen = ["derivatives", "bonds", "lending"] if args.type == "all" else [args.type]

    for t in types_to_gen:
        count = args.count if args.count else defaults[t]
        print(f"Generating {count} {t} positions...")
        if t == "derivatives":
            df = generate_derivatives(count)
        elif t == "bonds":
            df = generate_bonds(count)
        else:
            df = generate_lending(count)

        out_path = OUT_DIR / f"{t}.parquet"
        df.to_parquet(out_path, index=False)
        print(f"  -> {out_path}  ({len(df)} rows, {out_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
