#!/usr/bin/env bash
# Run the existing Policy Crawler under Lapdog. One LLM call per material
# regulation change; each becomes a session at https://lapdog.datadoghq.com.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
exec "${REPO_ROOT}/scripts/run_with_lapdog.sh" python -m backend.agents.policy_crawler "$@"
