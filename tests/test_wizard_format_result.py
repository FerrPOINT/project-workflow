"""Tests for format_result() human-readable output."""

import pytest
from wartz_workflow.wizard import format_result, VERDICT_LABELS


class TestFormatResult:
    """Cover all verdict branches and content rendering."""

    def _pass(self):
        return {
            "verdict": "PASS",
            "phase_name": "Smoke Plan",
            "phase": "smoke.plan",
            "covered": ["c1", "c2"],
            "missing": [],
            "blockers": [],
            "next_phase": "smoke.next",
            "next_phase_name": "Next Phase",
            "rollback_target": None,
            "message": "Go next",
        }

    def _partial(self):
        return {
            "verdict": "PARTIAL",
            "phase_name": "Smoke Plan",
            "phase": "smoke.plan",
            "covered": ["c1"],
            "missing": ["m1"],
            "blockers": [],
            "next_phase": None,
            "next_phase_name": None,
            "rollback_target": None,
            "message": "Need more",
        }

    def _blocked(self):
        return {
            "verdict": "BLOCKED",
            "phase_name": "Smoke Plan",
            "phase": "smoke.plan",
            "covered": [],
            "missing": ["m1"],
            "blockers": ["b1"],
            "next_phase": None,
            "next_phase_name": None,
            "rollback_target": None,
            "message": "Blocked msg",
        }

    def _rollback(self):
        return {
            "verdict": "ROLLBACK",
            "phase_name": "Smoke Plan",
            "phase": "smoke.plan",
            "covered": [],
            "missing": [],
            "blockers": [],
            "next_phase": None,
            "next_phase_name": None,
            "rollback_target": "smoke.prev",
            "message": "Roll back msg",
        }

    def _delegate(self):
        return {
            "verdict": "DELEGATE",
            "phase_name": "Smoke Plan",
            "phase": "smoke.plan",
            "covered": [],
            "missing": [],
            "blockers": [],
            "next_phase": None,
            "next_phase_name": None,
            "rollback_target": None,
            "message": "Delegated msg",
        }

    def _parallel_pass(self):
        return {
            "verdict": "PASS",
            "phase_name": "Parallel group: 1, 2",
            "phase": "1",
            "covered": ["c1", "c2"],
            "missing": [],
            "blockers": [],
            "next_phase": "3",
            "next_phase_name": "Next",
            "rollback_target": None,
            "message": "Proceed",
        }

    # ── Verdict headers ────────────────────────────────────────────────
    def test_pass_header(self):
        out = format_result(self._pass())
        assert "✅" in out
        assert "Smoke Plan" in out
        assert "Переход к: Next Phase" in out

    def test_partial_header(self):
        out = format_result(self._partial())
        assert "⚠️" in out
        assert "частично выполнена" in out

    def test_blocked_header(self):
        out = format_result(self._blocked())
        assert "🔴" in out
        assert "заблокирована" in out

    def test_rollback_header(self):
        out = format_result(self._rollback())
        assert "⬅️" in out
        assert "отклонена" in out

    def test_delegate_header(self):
        out = format_result(self._delegate())
        assert "📤" in out
        assert "делегирована" in out

    def test_unknown_header(self):
        out = format_result({"verdict": "UNKNOWN", "phase_name": "X"})
        assert "❓" in out
        assert "UNKNOWN" in out

    # ── Content sections ─────────────────────────────────────────────
    def test_covered_shown(self):
        out = format_result(self._pass())
        assert "Закрытые пункты:" in out
        assert "c1" in out
        assert "c2" in out

    def test_missing_shown(self):
        out = format_result(self._partial())
        assert "Не закрытые пункты:" in out
        assert "m1" in out

    def test_blockers_shown(self):
        out = format_result(self._blocked())
        assert "Блокеры:" in out
        assert "b1" in out

    def test_no_covered_section_when_empty(self):
        out = format_result(self._blocked())
        assert "Закрытые пункты:" not in out

    def test_no_missing_section_when_empty(self):
        out = format_result(self._pass())
        assert "Не закрытые пункты:" not in out

    def test_no_blockers_section_when_empty(self):
        out = format_result(self._pass())
        assert "Блокеры:" not in out

    # ── Next step messages ─────────────────────────────────────────────
    def test_pass_with_next(self):
        out = format_result(self._pass())
        assert "Следующая фаза:" in out
        assert "smoke.next" in out
        assert "Next Phase" in out

    def test_pass_no_next(self):
        r = self._pass()
        r["next_phase"] = None
        r["next_phase_name"] = None
        out = format_result(r)
        assert "Все фазы пройдены" in out

    def test_partial_stay_message(self):
        out = format_result(self._partial())
        assert "Оставайся на текущей фазе" in out

    def test_blocked_message(self):
        out = format_result(self._blocked())
        assert "Фаза заблокирована" in out

    def test_rollback_with_target(self):
        out = format_result(self._rollback())
        assert "Roll back к фазе:" in out
        assert "smoke.prev" in out

    def test_rollback_without_target(self):
        r = self._rollback()
        r["rollback_target"] = None
        out = format_result(r)
        assert "Roll back" in out
        assert "к фазе" not in out  # target-specific phrasing omitted

    def test_delegate_message(self):
        out = format_result(self._delegate())
        assert "Ожидаю завершения делегированной работы" in out

    # ── Message hint ───────────────────────────────────────────────────
    def test_message_hint_appended(self):
        out = format_result(self._pass())
        assert "💡 Go next" in out

    def test_message_hint_not_appended_when_absent(self):
        r = self._pass()
        r["message"] = ""
        out = format_result(r)
        assert "💡" not in out

    # ── Parallel specific ──────────────────────────────────────────────
    def test_parallel_pass_header(self):
        out = format_result(self._parallel_pass())
        assert "Parallel group" in out
        assert "Переход к: Next" in out  # has next_phase_name

    # ── Edge cases ─────────────────────────────────────────────────────
    def test_empty_result(self):
        out = format_result({})
        assert "❓" in out
        assert "—" in out  # phase_name defaults to "-"

    def test_all_verdicts_have_format(self):
        """Ensure every known verdict label maps to something in format_result."""
        for v, label in VERDICT_LABELS.items():
            out = format_result({
                "verdict": label, "phase_name": "Test",
                "covered": [], "missing": [], "blockers": [],
            })
            # Should not fall through to UNKNOWN / generic line
            assert out.strip() != ""
            assert "❓" not in out or label == "UNKNOWN"

    def test_empty_lists_omitted(self):
        """All three lists empty → no bullet sections rendered."""
        out = format_result({
            "verdict": "PASS", "phase_name": "Done", "covered": [],
            "missing": [], "blockers": [], "next_phase": None,
        })
        assert "Закрытые" not in out
        assert "Не закрытые" not in out
        assert "Блокеры" not in out
        assert "Все фазы пройдены" in out
