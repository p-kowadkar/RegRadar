#!/usr/bin/env bash
# Run any Python entrypoint under Lapdog tracing.
#
# Usage:
#   ./scripts/run_with_lapdog.sh python -m backend.scheduler
#   ./scripts/run_with_lapdog.sh python -m backend.agents.policy_crawler
#   ./scripts/run_with_lapdog.sh python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
#
# Behavior:
#   1. Starts the local Lapdog agent (idempotent).
#   2. Runs the given command with Lapdog auto-instrumentation.
#   3. With --forward, also ships spans to Datadog LLM Observability if
#      DD_API_KEY is set in .env.
#
# After the run, open https://lapdog.datadoghq.com to inspect the session.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Load .env so DD_API_KEY/etc. are visible (no override of existing values).
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -E '^[A-Z_]+=' .env)
  set +a
fi

# Defaults
FORWARD_FLAG=()
if [[ -n "${DD_API_KEY:-}" ]]; then
  FORWARD_FLAG=(--forward)
fi

if [[ "$#" -eq 0 ]]; then
  echo "usage: $0 <command> [args...]" >&2
  echo "examples:" >&2
  echo "  $0 python -m backend.scheduler" >&2
  echo "  $0 python -m backend.agents.policy_crawler" >&2
  echo "  $0 python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000" >&2
  exit 1
fi

# Make sure Lapdog is up.
lapdog start >/dev/null 2>&1 || true

echo "[lapdog] forwarding: ${#FORWARD_FLAG[@]} flags  command: $*"
exec lapdog "${FORWARD_FLAG[@]}" "$@"
