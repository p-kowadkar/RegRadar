#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════
# RegRadar -- One-shot Development Setup
#
# Usage:  ./scripts/setup.sh
# Idempotent -- safe to run multiple times.
# ════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "▶ Setting up RegRadar in: $PROJECT_ROOT"

# ── 1. Verify .env exists ───────────────────────────────────────
if [[ ! -f .env ]]; then
    echo ""
    echo "✗ .env file not found. Copy template:"
    echo "    cp .env.example .env"
    echo "    # then edit .env and fill in API keys"
    exit 1
fi
echo "✓ .env file present"

# ── 2. Python virtual environment ───────────────────────────────
if [[ ! -d venv ]]; then
    echo "▶ Creating Python venv..."
    python -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip --quiet
echo "✓ Python venv ready"

# ── 3. Install Python dependencies ──────────────────────────────
echo "▶ Installing Python dependencies..."
pip install -r requirements.txt --quiet
echo "✓ Python deps installed"

# ── 4. Local ClickHouse via Docker ──────────────────────────────
if command -v docker &> /dev/null; then
    if ! docker ps --format '{{.Names}}' | grep -q regradar-clickhouse; then
        echo "▶ Starting local ClickHouse..."
        docker compose up -d clickhouse
        echo "  waiting for ClickHouse..."
        sleep 5
    fi
    echo "✓ Local ClickHouse running"
else
    echo "⚠ Docker not found -- ensure CLICKHOUSE_HOST in .env points to a reachable instance"
fi

# ── 5. Apply ClickHouse schema ──────────────────────────────────
echo "▶ Applying schema..."
python -c "
import os
import clickhouse_connect
from backend.utils import env
env.validate()
c = clickhouse_connect.get_client(
    host=env.get('CLICKHOUSE_HOST'),
    port=env.get_int('CLICKHOUSE_PORT'),
    username=env.get('CLICKHOUSE_USER'),
    password=env.get('CLICKHOUSE_PASSWORD'),
    secure=env.get_bool('CLICKHOUSE_SECURE'),
)
with open('backend/data/schema.sql') as f:
    sql = f.read()
for stmt in sql.split(';'):
    stmt = stmt.strip()
    if stmt and not stmt.startswith('--'):
        try:
            c.command(stmt)
        except Exception as e:
            # vector index DDL may fail on older ClickHouse -- non-fatal
            if 'vector_similarity' not in stmt.lower():
                raise
            print(f'  (skipping vector index -- requires ClickHouse 24.10+): {e}')
print('✓ Schema applied')
"

# ── 6. Generate portfolios (if not already) ─────────────────────
if [[ ! -f seed/portfolios/derivatives.parquet ]]; then
    echo "▶ Generating synthetic portfolios..."
    python seed/portfolios/generate_portfolios.py --type=all
fi
echo "✓ Portfolios generated"

# ── 7. Load seed data ───────────────────────────────────────────
echo "▶ Loading seed data into ClickHouse..."
python scripts/load_seed_data.py
echo "✓ Seed data loaded"

# ── 8. Frontend deps ────────────────────────────────────────────
if [[ -d frontend ]]; then
    echo "▶ Installing frontend dependencies..."
    (cd frontend && npm install --silent)
    echo "✓ Frontend deps installed"
fi

# ── 9. Smoke test ───────────────────────────────────────────────
echo "▶ Running smoke tests..."
python scripts/smoke_test.py || {
    echo ""
    echo "✗ Smoke tests failed. Fix before continuing."
    exit 1
}

# ── 10. All done ────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ RegRadar setup complete"
echo "═══════════════════════════════════════════════════"
echo ""
echo "Start the backend:"
echo "    ddtrace-run uvicorn backend.main:app --reload --port 8000"
echo ""
echo "Start the frontend (in another terminal):"
echo "    cd frontend && npm run dev"
echo ""
