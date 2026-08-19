"""Tests for format_result() human-readable output."""

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.wizard import format_result


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
            "instructions": ["Инструкция 1", "Инструкция 2"],
            "required_checks": ["c1", "c2"],
            "required_evidence": ["e1"],
            "next_phase_contract": {
                "instructions": ["Инструкция 1", "Инструкция 2"],
                "required_checks": ["c1", "c2"],
                "required_evidence": ["e1"],
            },
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
            "instructions": ["Инструкция 1"],
            "required_checks": ["c1", "m1"],
            "required_evidence": ["e1"],
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
            "instructions": ["Инструкция 1"],
            "required_checks": ["m1"],
            "required_evidence": [],
        }

    # ── PASS ──────────────────────────────────────────────────────────
    def test_pass_shows_next_phase_name(self):
        out = format_result(self._pass())
        assert "Перейди к шагу: Next Phase" in out
        # Must be inside the instructions section, not a standalone header.
        lines = out.splitlines()
        instr_idx = next((i for i, line in enumerate(lines) if line == "Инструкции:"), -1)
        next_idx = next((i for i, line in enumerate(lines) if "Перейди к шагу" in line), -1)
        assert instr_idx != -1
        assert next_idx != -1
        assert next_idx > instr_idx

    def test_pass_shows_next_phase_instructions(self):
        out = format_result(self._pass())
        assert "Инструкции:" in out
        assert "  · Инструкция 1" in out
        assert "  · Инструкция 2" in out

    def test_pass_shows_next_phase_checks(self):
        out = format_result(self._pass())
        assert "Чекапы:" in out
        assert "  · c1" in out
        assert "  · c2" in out

    def test_pass_shows_next_phase_evidence(self):
        out = format_result(self._pass())
        assert "Доказательства:" in out
        assert "  · e1" in out

    def test_terminal_pass_reports_workflow_completion(self):
        result = self._pass()
        result["next_phase"] = None
        result["next_phase_name"] = None
        result.pop("next_phase_contract", None)
        assert "Workflow завершён" in format_result(result)

    def test_pass_no_message_hint(self):
        """Message field from JSON must NOT leak into formatted output."""
        out = format_result(self._pass())
        assert "Go next" not in out

    def test_pass_no_emojis(self):
        out = format_result(self._pass())
        assert "✓" not in out
        assert "✗" not in out

    # ── PARTIAL / non-PASS ───────────────────────────────────────────
    def test_partial_no_boilerplate_header(self):
        out = format_result(self._partial())
        assert "Ты сделал часть, доделай:" not in out
        assert "Сделано" not in out
        assert "Блокеры" not in out
        assert "Need more" not in out

    def test_partial_shows_current_instructions(self):
        out = format_result(self._partial())
        assert "Инструкции:" in out
        assert "  · Инструкция 1" in out

    def test_partial_shows_only_not_done_checks(self):
        out = format_result(self._partial())
        assert "Чекапы:" in out
        assert "c1" not in out  # covered, not shown
        assert "  · m1" in out  # missing, shown

    def test_partial_shows_only_not_done_evidence(self):
        out = format_result(self._partial())
        assert "Доказательства:" in out
        assert "  · e1" in out

    def test_partial_uses_pending_marker_only(self):
        """PARTIAL output uses only pending marker and never emoji checkmarks."""
        out = format_result(self._partial())
        assert "✓" not in out
        assert "✗" not in out
        assert "  · m1" in out
        assert "  · e1" in out

    def test_blocked_shows_only_not_done(self):
        out = format_result(self._blocked())
        assert "  · m1" in out
        assert "Причина:" in out
        assert "Blocked msg" in out

    # ── PARALLEL GROUP ─────────────────────────────────────────────────
    def _pass_parallel(self):
        return {
            "verdict": "PASS",
            "phase_name": "Smoke Plan",
            "phase": "smoke.plan",
            "covered": ["c1"],
            "missing": [],
            "blockers": [],
            "next_phase": "smoke.parallel-a",
            "next_phase_name": "Smoke Parallel A",
            "rollback_target": None,
            "message": "Phase accepted.",
            "instructions": [],
            "required_checks": [],
            "required_evidence": [],
            "next_phase_contract": {
                "phase_code": "smoke.parallel-a",
                "phase_name": "Parallel group: smoke.parallel-a, smoke.parallel-b",
                "execution_type": "parallel",
                "group_phases": ["smoke.parallel-a", "smoke.parallel-b"],
                "group_details": [
                    {
                        "phase_code": "smoke.parallel-a",
                        "phase_name": "Smoke Parallel A",
                        "instructions": ["Backend check."],
                        "required_checks": ["backend check prepared"],
                        "required_evidence": ["backend check"],
                        "delegate_agent": "researcher",
                        "delegate_toolsets": [],
                        "parallel_with": "smoke.parallel-b",
                    },
                    {
                        "phase_code": "smoke.parallel-b",
                        "phase_name": "Smoke Parallel B",
                        "instructions": ["UI check."],
                        "required_checks": ["ui check prepared"],
                        "required_evidence": ["ui check"],
                        "delegate_agent": "coder",
                        "delegate_toolsets": [],
                        "parallel_with": "smoke.parallel-a",
                    },
                ],
            },
        }

    def test_pass_parallel_group_lists_phases_and_agents(self):
        out = format_result(self._pass_parallel())
        assert "Параллельная группа фаз: Smoke Parallel A, Smoke Parallel B" in out
        assert "параллельно с Smoke Parallel B" in out
        assert "параллельно с Smoke Parallel A" in out
        assert "агент: researcher" in out
        assert "агент: coder" in out
        assert "Backend check." in out
        assert "UI check." in out
        assert "backend check prepared" in out
        assert "ui check prepared" in out
        assert "Чекапы:" in out
        assert "Доказательства:" in out
