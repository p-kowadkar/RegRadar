#!/usr/bin/env bash
# Run the Impact Analysis Agent under Lapdog so each LLM call is captured.
#
# Usage:
#   ./scripts/run_impact_agent.sh            # run once, exit
#   ./scripts/run_impact_agent.sh --watch    # if/when the team adds a watch loop
#
# Lapdog will capture every Gemini call as an LLM span, with the FastAPI
# request span (if any) as parent. Open https://lapdog.datadoghq.com to inspect.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Pick whichever module the team ships under. We try the canonical module path
# first, then fall back to the legacy mvp impact_agent so this script stays
# useful right up until they push.
MODULE_CANDIDATES=(
  "backend.agents.impact_analysis"
  "backend.agents.impact_agent"
)

for mod in "${MODULE_CANDIDATES[@]}"; do
  if python -c "import importlib; importlib.import_module('${mod}')" 2>/dev/null; then
    echo "[run_impact_agent] using module: ${mod}"
    exec "${REPO_ROOT}/scripts/run_with_lapdog.sh" python -m "${mod}" "$@"
  fi
done

echo "ERROR: no impact-analysis module found among: ${MODULE_CANDIDATES[*]}" >&2
exit 1
