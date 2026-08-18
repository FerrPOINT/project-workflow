#!/usr/bin/env bash
# Two real Wizard calls: complete and incomplete text reports.
set -euo pipefail

cd "$(dirname "$0")/.."
CLI="${PROJECT_WORKFLOW_COMMAND:-project-workflow}"
PYTHON="${PYTHON:-python3}"
EXPECTED_MODEL="${OLLAMA_MODEL:?OLLAMA_MODEL is required}"
: "${OLLAMA_API_KEY:?OLLAMA_API_KEY is required}"

json_field() {
  "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

run_smoke() {
  local task="$1"
  local mode="$2"
  local expected="$3"
  local report result verdict model
  "$CLI" --json step --task "$task" >/dev/null
  if [ "$mode" = "complete" ]; then
    report='All current phase instructions completed; checks passed; evidence: live-smoke://readback, live-smoke://artifact'
  else
    report='Current phase is incomplete; required checks and evidence are missing'
  fi
  result=$("$CLI" --json step --task "$task" --report "$report")
  verdict=$(printf '%s' "$result" | json_field verdict)
  model=$(printf '%s' "$result" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["wizard"]["model"])')
  [ "$model" = "$EXPECTED_MODEL" ] || { echo "unexpected model: $model" >&2; exit 1; }
  printf '%s\n' "$expected" | grep -qw "$verdict" || { echo "unexpected verdict: $verdict" >&2; exit 1; }
  "$CLI" --json history --task "$task" --n 20 >/dev/null
  echo "$task: $verdict via $model"
}

stamp=$(date +%s)
run_smoke "SMOKE-$stamp" complete "PASS"
run_smoke "SMOKE-$((stamp + 1))" incomplete "SOFT_FAIL BLOCKED"
