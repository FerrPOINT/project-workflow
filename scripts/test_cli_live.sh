#!/usr/bin/env bash
# Two real Wizard calls: complete and incomplete YAML workfiles.
set -euo pipefail

cd "$(dirname "$0")/.."
CLI="${PROJECT_WORKFLOW_COMMAND:-project-workflow}"
PYTHON="${PYTHON:-python3}"
EXPECTED_MODEL="${OLLAMA_MODEL:?OLLAMA_MODEL is required}"
: "${OLLAMA_API_KEY:?OLLAMA_API_KEY is required}"

json_field() {
  "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"
}

fill_report() {
  local path="$1"
  local mode="$2"
  "$PYTHON" - "$path" "$mode" <<'PY'
from pathlib import Path
import sys
import yaml

path = Path(sys.argv[1])
mode = sys.argv[2]
data = yaml.safe_load(path.read_text(encoding="utf-8"))
if mode == "complete":
    for item in data["instructions"]:
        item.update(done=True, result="live smoke completed")
    for item in data["checks"]:
        item.update(status="passed", evidence=["live-smoke://readback"])
    for item in data["evidence"]:
        item.update(status="passed", refs=["live-smoke://artifact"])
    data["summary"] = "All current phase items completed for live smoke"
else:
    data["summary"] = "Current phase intentionally left incomplete"
path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
PY
}

run_smoke() {
  local task="$1"
  local mode="$2"
  local expected="$3"
  local current report_file result verdict model
  current=$("$CLI" --json step --task "$task")
  report_file=$(printf '%s' "$current" | json_field report_file)
  fill_report "$report_file" "$mode"
  result=$("$CLI" --json step --task "$task" --report "$report_file")
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
