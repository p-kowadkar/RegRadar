#!/usr/bin/env python3
"""
scripts/setup_cc_accounts.py

Prepares regradar.cc_accounts for the RegRadar demo in three steps:

  Step 1 — ADD 9 missing columns (idempotent via IF NOT EXISTS)
  Step 2 — TRUNCATE 23 test rows; generate + insert 50,000 synthetic accounts (5k batches)
  Step 3 — Run 4 verification queries; print breach counts

DO NOT add original_delinquency_date here. That column is the headline demo trigger:
  scripts/demo_trigger.py backfills it on accounts where days_past_due > 60 (~6,000 rows),
  and ~21% of those will have dates > 7 years ago → ~1,247 FCRA Section 605 violations.

Run with:
  python scripts/setup_cc_accounts.py

Expected runtime: < 60 seconds against ClickHouse Cloud.
"""

from __future__ import annotations

import asyncio
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Ensure the project root is on sys.path so backend.* imports resolve
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from faker import Faker

# Load .env and check only the ClickHouse vars this script needs
import os
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

_REQUIRED = ["CLICKHOUSE_HOST", "CLICKHOUSE_PORT", "CLICKHOUSE_USER"]
_missing = [v for v in _REQUIRED if not os.environ.get(v)]
if _missing:
    print("ERROR: Missing required env vars:")
    for v in _missing:
        print(f"  {v}")
    print("\nCreate a .env file (copy from .env.example) and fill in CLICKHOUSE_* vars.")
    sys.exit(1)

from backend.integrations.clickhouse_client import get_client  # noqa: E402
from backend.utils.logging import configure_logging, get_logger  # noqa: E402

configure_logging()
log = get_logger(__name__)


# ════════════════════════════════════════════════════════════════
# Seeds + constants
# ════════════════════════════════════════════════════════════════

TOTAL_ACCOUNTS = 50_000
BATCH_SIZE = 5_000
TABLE = "regradar.cc_accounts"
TODAY = date.today()
NOW = datetime.now()

random.seed(42)
np.random.seed(42)
fake = Faker()
Faker.seed(42)

# ── Account type ──────────────────────────────────────────────
ACCOUNT_TYPES = ["standard", "rewards", "secured", "student"]
ACCOUNT_TYPE_WEIGHTS = np.array([0.70, 0.20, 0.05, 0.05])

# ── State distribution: CA 12%, TX 9%, FL 7%, NY 6%, rest even ──
_TOP_STATES = {"CA": 0.12, "TX": 0.09, "FL": 0.07, "NY": 0.06}
_ALL_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
]
_remaining_states = [s for s in _ALL_STATES if s not in _TOP_STATES]
_each_remaining = (1.0 - sum(_TOP_STATES.values())) / len(_remaining_states)
_state_weights_raw = {**_TOP_STATES, **{s: _each_remaining for s in _remaining_states}}
STATES = list(_ALL_STATES)
_state_probs = np.array([_state_weights_raw.get(s, _each_remaining) for s in STATES])
_state_probs /= _state_probs.sum()  # normalize to exactly 1.0

# ── Payment statuses ──────────────────────────────────────────
ALL_PAYMENT_STATUSES = ["CURRENT", "30_DAYS_LATE", "60_DAYS_LATE", "90_DAYS_LATE", "CHARGE_OFF"]

# ── days_past_due distribution ────────────────────────────────
# Adjusted so days_past_due > 60 ≈ 12% ≈ 6,000 accounts.
# The demo migration will backfill original_delinquency_date on those ~6,000 rows;
# ~21% will be dated > 7 years ago → ~1,247 FCRA violations (the headline number).
DPD_BUCKETS = ["0", "1-30", "31-60", "61-90", "91+"]
DPD_WEIGHTS = np.array([0.76, 0.08, 0.04, 0.10, 0.02])
# > 60 = 10% + 2% = 12% = ~6,000 accounts  ✓
# charge_off (> 90) = 2% = ~1,000 accounts  ✓

APPLICABLE_POLICIES = ["REG-001", "REG-002", "REG-003", "REG-004", "REG-005", "REG-006", "REG-007"]

# Column list — matches live table order (original + new columns appended)
COLUMN_NAMES = [
    # ── original columns ──
    "account_id",
    "account_type",
    "state",
    "credit_limit",
    "current_balance",
    "apr",
    "penalty_rate",
    "penalty_rate_applied",
    "penalty_rate_applied_date",
    "dispute_filed",
    "dispute_filed_date",
    "days_past_due",
    "charge_off_status",
    "applicable_policies",
    "created_at",
    "last_updated",
    # ── new columns added in Step 1 ──
    "penalty_rate_notice_sent_date",
    "promo_rate",
    "promo_rate_end_date",
    "promo_notice_sent_date",
    "dispute_acknowledged_date",
    "dispute_resolved_date",
    "dispute_bureau_flag",
    "bureau_reported_status",
    "payment_status",
]


# ════════════════════════════════════════════════════════════════
# Step 1 — ALTER TABLE
# ════════════════════════════════════════════════════════════════

_ALTER_STATEMENTS = [
    f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS penalty_rate_notice_sent_date Nullable(Date)",
    f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS promo_rate Nullable(Decimal(5,4))",
    f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS promo_rate_end_date Nullable(Date)",
    f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS promo_notice_sent_date Nullable(Date)",
    f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS dispute_acknowledged_date Nullable(Date)",
    f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS dispute_resolved_date Nullable(Date)",
    f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS dispute_bureau_flag Nullable(Bool)",
    f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS bureau_reported_status Nullable(String)",
    f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS payment_status Nullable(String)",
]


async def add_columns(client) -> None:
    for stmt in _ALTER_STATEMENTS:
        col = stmt.split("ADD COLUMN IF NOT EXISTS ")[1].split(" ")[0]
        await client.command(stmt)
        log.info("schema.column_added", column=col)


# ════════════════════════════════════════════════════════════════
# Account generator
# ════════════════════════════════════════════════════════════════

def _pick_dpd(bucket: str) -> int:
    if bucket == "0":
        return 0
    elif bucket == "1-30":
        return int(np.random.randint(1, 31))
    elif bucket == "31-60":
        return int(np.random.randint(31, 61))
    elif bucket == "61-90":
        return int(np.random.randint(61, 91))
    else:  # "91+"
        return int(np.random.randint(91, 366))


def _payment_status(dpd: int, charge_off: bool) -> str:
    if charge_off or dpd > 90:
        return "CHARGE_OFF"
    elif dpd > 60:
        return "90_DAYS_LATE"
    elif dpd > 30:
        return "60_DAYS_LATE"
    elif dpd > 0:
        return "30_DAYS_LATE"
    return "CURRENT"


def generate_account(idx: int) -> list:
    """Return one row as a list matching COLUMN_NAMES order."""

    # ── Core account fields ───────────────────────────────────
    account_id = f"acct_{idx:06d}"
    account_type = str(np.random.choice(ACCOUNT_TYPES, p=ACCOUNT_TYPE_WEIGHTS))
    state = str(np.random.choice(STATES, p=_state_probs))

    credit_limit = round(float(np.clip(np.random.lognormal(8.517, 0.8), 500.0, 50_000.0)), 2)
    current_balance = round(float(np.random.uniform(0.0, 0.85 * credit_limit)), 2)
    apr = round(float(np.clip(np.random.normal(0.21, 0.04), 0.05, 0.36)), 4)

    # ── Days past due + derived fields ────────────────────────
    dpd_bucket = str(np.random.choice(DPD_BUCKETS, p=DPD_WEIGHTS))
    days_past_due = _pick_dpd(dpd_bucket)
    charge_off_status = bool(days_past_due > 90)
    payment_status = _payment_status(days_past_due, charge_off_status)

    # ── TILA penalty rate (~2% of accounts) ──────────────────
    penalty_rate: float = 0.0
    penalty_rate_applied = bool(np.random.random() < 0.02)
    penalty_rate_applied_date: date | None = None
    penalty_rate_notice_sent_date: date | None = None

    if penalty_rate_applied:
        penalty_rate = round(float(np.random.uniform(0.24, 0.30)), 4)
        applied_offset = int(np.random.randint(90, 181))          # 90-180 days ago
        penalty_rate_applied_date = TODAY - timedelta(days=applied_offset)

        notice_roll = float(np.random.random())
        if notice_roll < 0.80:
            # Compliant: notice sent exactly 45 days before applied (≥ 45 days = OK)
            penalty_rate_notice_sent_date = penalty_rate_applied_date - timedelta(days=45)
        elif notice_roll < 0.95:
            # BREACH: only 20 days notice — late (< 45 days before applied)
            penalty_rate_notice_sent_date = penalty_rate_applied_date - timedelta(days=20)
        # else 5%: NULL → BREACH (no notice sent at all)

    # ── TILA promo rate (~25% of accounts) ───────────────────
    promo_rate: float | None = None
    promo_rate_end_date: date | None = None
    promo_notice_sent_date: date | None = None

    if np.random.random() < 0.25:
        promo_rate = round(float(np.random.uniform(0.0, 0.099)), 4)
        end_offset = int(np.random.randint(-60, 541))             # 60 days ago to 18 months out
        promo_rate_end_date = TODAY + timedelta(days=end_offset)

        notice_roll = float(np.random.random())
        if notice_roll < 0.60:
            # Compliant: sent 50 days before end (> 45-day window)
            promo_notice_sent_date = promo_rate_end_date - timedelta(days=50)
        elif notice_roll < 0.85:
            # BREACH if end is within 45 days: only 20 days before end
            promo_notice_sent_date = promo_rate_end_date - timedelta(days=20)
        # else 15%: NULL → BREACH if promo expires within 45 days from today

    # ── TILA/FCRA disputes (~0.8% of accounts) ───────────────
    dispute_filed = bool(np.random.random() < 0.008)
    dispute_filed_date: date | None = None
    dispute_acknowledged_date: date | None = None
    dispute_resolved_date: date | None = None
    dispute_bureau_flag: bool | None = None

    if dispute_filed:
        days_ago = int(np.random.randint(0, 121))                 # 0-120 days ago
        dispute_filed_date = TODAY - timedelta(days=days_ago)

        # Acknowledged? 65% within 30 days (compliant), 35% NULL (breach if filed > 30 days ago)
        if np.random.random() < 0.65:
            ack_days = int(np.random.randint(1, 26))
            dispute_acknowledged_date = dispute_filed_date + timedelta(days=ack_days)

        # Resolved? 50% of disputes filed > 30 days ago
        if days_ago > 30 and np.random.random() < 0.50:
            resolve_days = int(np.random.randint(30, 86))
            dispute_resolved_date = dispute_filed_date + timedelta(days=resolve_days)

        # Bureau flag: 80% True (compliant), 10% False (breach), 10% NULL (breach)
        flag_roll = float(np.random.random())
        if flag_roll < 0.80:
            dispute_bureau_flag = True
        elif flag_roll < 0.90:
            dispute_bureau_flag = False
        # else 10%: None (BREACH — flag missing)

    # ── FCRA bureau status (~3% mismatch = ~1,500 breaches) ──
    if np.random.random() < 0.97:
        bureau_reported_status: str | None = payment_status       # accurate
    else:
        wrong = [s for s in ALL_PAYMENT_STATUSES if s != payment_status]
        bureau_reported_status = str(np.random.choice(wrong))     # intentional mismatch

    # ── Account lifecycle ──────────────────────────────────────
    created_date = fake.date_between(start_date=date(2018, 1, 1), end_date=date(2024, 12, 31))
    created_at = datetime(created_date.year, created_date.month, created_date.day)

    return [
        account_id,                    # account_id
        account_type,                  # account_type
        state,                         # state
        credit_limit,                  # credit_limit
        current_balance,               # current_balance
        apr,                           # apr
        penalty_rate,                  # penalty_rate
        penalty_rate_applied,          # penalty_rate_applied
        penalty_rate_applied_date,     # penalty_rate_applied_date
        dispute_filed,                 # dispute_filed
        dispute_filed_date,            # dispute_filed_date
        days_past_due,                 # days_past_due
        charge_off_status,             # charge_off_status
        APPLICABLE_POLICIES,           # applicable_policies
        created_at,                    # created_at
        NOW,                           # last_updated
        # new columns
        penalty_rate_notice_sent_date, # penalty_rate_notice_sent_date
        promo_rate,                    # promo_rate
        promo_rate_end_date,           # promo_rate_end_date
        promo_notice_sent_date,        # promo_notice_sent_date
        dispute_acknowledged_date,     # dispute_acknowledged_date
        dispute_resolved_date,         # dispute_resolved_date
        dispute_bureau_flag,           # dispute_bureau_flag
        bureau_reported_status,        # bureau_reported_status
        payment_status,                # payment_status
    ]


# ════════════════════════════════════════════════════════════════
# Step 3 — Verification
# ════════════════════════════════════════════════════════════════

_VERIFICATIONS = [
    (
        "Total row count",
        f"SELECT count() FROM {TABLE}",
        "expect: 50,000",
    ),
    (
        "Penalty rate notice breaches",
        f"""SELECT countIf(
            penalty_rate_applied AND (
                penalty_rate_notice_sent_date IS NULL
                OR penalty_rate_notice_sent_date > penalty_rate_applied_date - 45
            )
        ) FROM {TABLE}""",
        "expect: 200-300",
    ),
    (
        "Dispute bureau flag breaches",
        f"""SELECT countIf(
            dispute_filed AND dispute_bureau_flag = false
            OR (dispute_filed AND dispute_bureau_flag IS NULL)
        ) FROM {TABLE}""",
        "expect: 60-100",
    ),
    (
        "Bureau accuracy breaches",
        f"""SELECT countIf(
            bureau_reported_status != payment_status
            AND bureau_reported_status IS NOT NULL
        ) FROM {TABLE}""",
        "expect: 1,200-1,800",
    ),
    (
        "Dispute acknowledgement breaches",
        f"""SELECT countIf(
            dispute_filed
            AND dispute_acknowledged_date IS NULL
            AND dispute_filed_date < today() - 30
        ) FROM {TABLE}""",
        "expect: 80-160",
    ),
]


async def run_verification(client) -> None:
    print("\n" + "=" * 60)
    print("VERIFICATION RESULTS")
    print("=" * 60)
    for label, sql, expected in _VERIFICATIONS:
        result = await client.query(sql)
        value = result.result_rows[0][0]
        print(f"  {label}: {value:,}  ({expected})")
    print("=" * 60)


# ════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════

async def main() -> None:
    client = await get_client()

    # ── Step 1: Add missing columns ───────────────────────────
    print("\nStep 1: Adding missing columns...")
    await add_columns(client)
    print(f"  Added 9 columns (IF NOT EXISTS — safe to re-run)")

    # ── Step 2: Truncate + generate + insert ──────────────────
    print(f"\nStep 2: Truncating existing rows...")
    await client.command(f"TRUNCATE TABLE {TABLE}")
    print(f"  Cleared existing rows")

    n_batches = TOTAL_ACCOUNTS // BATCH_SIZE
    print(f"\n  Generating {TOTAL_ACCOUNTS:,} accounts in {n_batches} batches of {BATCH_SIZE:,}...")

    for batch_num in range(n_batches):
        start_idx = batch_num * BATCH_SIZE
        rows = [generate_account(i) for i in range(start_idx, start_idx + BATCH_SIZE)]
        await client.insert(TABLE, rows, column_names=COLUMN_NAMES)
        inserted_so_far = (batch_num + 1) * BATCH_SIZE
        print(f"  Batch {batch_num + 1}/{n_batches}: {inserted_so_far:,} accounts inserted")

    print(f"\n  Done. {TOTAL_ACCOUNTS:,} accounts inserted into {TABLE}")

    # ── Step 3: Verification ──────────────────────────────────
    await run_verification(client)


async def _run() -> None:
    try:
        await main()
    finally:
        from backend.integrations.clickhouse_client import _ASYNC_CLIENT
        if _ASYNC_CLIENT is not None:
            await _ASYNC_CLIENT.close()


if __name__ == "__main__":
    asyncio.run(_run())
