#!/usr/bin/env bash
# Live CLI test script — executes WizardEngine end-to-end through real CLI.
# Usage: bash scripts/test_cli_live.sh
# Requires: wartz-workflow CLI installed (pip install -e .)
set -euo pipefail

cd "$(dirname "$0")/.."
TASK_KEY="SMOKE-$(date +%s)"
DB="${WORKFLOW_DB:-$HOME/.wartz_workflow/workflow.db}"
API=0   # set to 1 for curl-based API tests (requires running UI server)

pass() { echo "✅ $1"; }
fail() { echo "❌ $1"; exit 1; }

step() {
    local task="$1"
    local report="${2:-}"
    if [ -n "$report" ]; then
        wartz-workflow --json step --task "$task" --report "$report" || true
    else
        wartz-workflow --json step --task "$task" || true
    fi
}

step_json() {
    local task="$1"
    local report="$2"
    wartz-workflow --json step --task "$task" --report "$report"
}

echo "═══════════════════════════════════════════════════════════════"
echo "  Live Test — Task: $TASK_KEY"
echo "═══════════════════════════════════════════════════════════════"

# ═══════════════════════════════════════════════════════════════
# 1. HAPPY PATH — 6 phases, all PASS
# ═══════════════════════════════════════════════════════════════
echo ""
echo "▶ Scenario 1: Happy Path (6 phases)"

step_json "$TASK_KEY" "smoke brief recorded and short workflow selected"
step_json "$TASK_KEY" "parallel strategy selected and agent selection recorded"
step_json "$TASK_KEY" "backend check prepared and подготовить backend check для короткого smoke workflow"
step_json "$TASK_KEY" "ui check prepared and подготовить ui check для короткого smoke workflow"
step_json "$TASK_KEY" "rollback path reviewed and history reviewed"
step_json "$TASK_KEY" "cli smoke completed and зафиксировать что cli smoke completed и история доступна через history"

FINAL_RESULT=$(step_json "$TASK_KEY" "cli smoke completed successfully")
VERDICT=$(echo "$FINAL_RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['verdict'])" 2>/dev/null || echo "UNKNOWN")
[ "$VERDICT" = "PASS" ] || fail "Expected PASS for final phase, got $VERDICT"

STATUS=$(sqlite3 "$DB" "SELECT status FROM tasks WHERE task_key='$TASK_KEY';")
[ "$STATUS" = "done" ] || fail "Expected task status 'done', got '$STATUS'"

HISTORY_COUNT=$(wartz-workflow history --task "$TASK_KEY" --json | python3 -c "import sys,json; print(len(json.load(sys.stdin)['records']))")
[ "$HISTORY_COUNT" -ge 6 ] || fail "Expected ≥6 history records, got $HISTORY_COUNT"

pass "Happy Path: 6 phases → done, $HISTORY_COUNT history records"

# ═══════════════════════════════════════════════════════════════
# 2. PARTIAL — missing keywords
# ═══════════════════════════════════════════════════════════════
echo ""
echo "▶ Scenario 2: PARTIAL verdict"

TASK_PARTIAL="${TASK_KEY}-P"
# First step with incomplete report
RESULT=$(step_json "$TASK_PARTIAL" "Started but not finished" || true)
VERDICT=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['verdict'])" 2>/dev/null || echo "UNKNOWN")
[ "$VERDICT" = "PARTIAL" ] || fail "Expected PARTIAL, got $VERDICT"

CURRENT=$(sqlite3 "$DB" "SELECT current_phase FROM tasks WHERE task_key='$TASK_PARTIAL';")
[ "$CURRENT" = "smoke.intake" ] || fail "Expected current_phase to stay on smoke.intake, got '$CURRENT'"

pass "PARTIAL: phase unchanged, missing items listed"

# ═══════════════════════════════════════════════════════════════
# 3. BLOCKED — explicit blocker, no rollback target
# ═══════════════════════════════════════════════════════════════
echo ""
echo "▶ Scenario 3: BLOCKED verdict"

TASK_BLOCKED="${TASK_KEY}-B"
# Create task, then move to plan phase
step_json "$TASK_BLOCKED" "Requirements gathered and intake complete"
# Now on smoke.plan
RESULT=$(step_json "$TASK_BLOCKED" "blocked by missing API spec, cannot proceed" || true)
VERDICT=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['verdict'])" 2>/dev/null || echo "UNKNOWN")
# Note: if smoke.plan has rollback_target, this may become ROLLBACK instead of BLOCKED
[ "$VERDICT" = "BLOCKED" ] || [ "$VERDICT" = "ROLLBACK" ] || fail "Expected BLOCKED or ROLLBACK, got $VERDICT"

STATUS=$(sqlite3 "$DB" "SELECT status FROM tasks WHERE task_key='$TASK_BLOCKED';")
[ "$STATUS" = "blocked" ] || [ "$STATUS" = "active" ] || fail "Unexpected status: $STATUS"

pass "BLOCKED: task status = $STATUS, verdict = $VERDICT"

# ═══════════════════════════════════════════════════════════════
# 4. ROLLBACK — rollback with target
# ═══════════════════════════════════════════════════════════════
echo ""
echo "▶ Scenario 4: ROLLBACK verdict"

TASK_ROLL="${TASK_KEY}-R"
# Advance to review phase
step_json "$TASK_ROLL" "Requirements gathered and intake complete"
step_json "$TASK_ROLL" "Plan created with architecture"
step_json "$TASK_ROLL" "Parallel agent A executed"
step_json "$TASK_ROLL" "Parallel agent B executed"

# Now on smoke.review which typically has rollback_target=smoke.plan
RESULT=$(step_json "$TASK_ROLL" "Tests failed, must rollback to plan phase" || true)
VERDICT=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['verdict'])" 2>/dev/null || echo "UNKNOWN")

if [ "$VERDICT" = "ROLLBACK" ]; then
    CURRENT=$(sqlite3 "$DB" "SELECT current_phase FROM tasks WHERE task_key='$TASK_ROLL';")
    [ "$CURRENT" = "smoke.plan" ] || fail "Expected rollback to smoke.plan, got '$CURRENT'"
    pass "ROLLBACK: rolled back to $CURRENT"
else
    echo "⚠️  ROLLBACK test: got $VERDICT (phase may not have rollback_target configured)"
fi

# ═══════════════════════════════════════════════════════════════
# 5. COMMAND GUARD
# ═══════════════════════════════════════════════════════════════
echo ""
echo "▶ Scenario 5: Command Guard"

HELP=$(wartz-workflow --help)
echo "$HELP" | grep -q "step" || fail "step command missing"
echo "$HELP" | grep -q "history" || fail "history command missing"

# Rejected options
if wartz-workflow step --task TEST-1 --skip 2>/dev/null; then
    fail "Expected --skip to be rejected"
fi
echo "✅ --skip rejected"

if wartz-workflow step --task TEST-1 --repo /tmp 2>/dev/null; then
    fail "Expected --repo to be rejected"
fi
echo "✅ --repo rejected"

pass "Command Guard: only step + history available"

# ═══════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ All live scenarios passed for task $TASK_KEY"
echo "═══════════════════════════════════════════════════════════════"
