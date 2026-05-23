#!/usr/bin/env bash
# Run the Asset Scanner under Lapdog so any LLM-classification call is captured.
#
# Usage:
#   ./scripts/run_asset_scanner.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODULE_CANDIDATES=(
  "backend.agents.asset_scanner"
  "backend.agents.scanner"
)

for mod in "${MODULE_CANDIDATES[@]}"; do
  if python -c "import importlib; importlib.import_module('${mod}')" 2>/dev/null; then
    echo "[run_asset_scanner] using module: ${mod}"
    exec "${REPO_ROOT}/scripts/run_with_lapdog.sh" python -m "${mod}" "$@"
  fi
done

echo "ERROR: no asset-scanner module found among: ${MODULE_CANDIDATES[*]}" >&2
exit 1
