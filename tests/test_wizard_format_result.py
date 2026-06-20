"""Tests for format_result() human-readable output."""

from workflow_cli.wizard import format_result


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

    # ── Инструкции, чекапы, доказательства ─────────────────────────────
    def test_pass_shows_next_phase_instructions(self):
        out = format_result(self._pass())
        assert "Инструкции:" in out
        assert "Инструкция 1" in out
        assert "Инструкция 2" in out

    def test_pass_shows_next_phase_checks(self):
        out = format_result(self._pass())
        assert "Чекапы:" in out
        assert "c1" in out
        assert "c2" in out

    def test_pass_shows_next_phase_evidence(self):
        out = format_result(self._pass())
        assert "Доказательства:" in out
        assert "e1" in out

    def test_pass_no_covered_done_section(self):
        """PASS output must NOT contain covered items as a separate 'Сделано' section."""
        out = format_result(self._pass())
        assert "Сделано" not in out

    def test_pass_no_message_hint(self):
        """Message field from JSON must NOT leak into formatted output."""
        out = format_result(self._pass())
        assert "Go next" not in out

    def test_partial_shows_header(self):
        out = format_result(self._partial())
        assert "Ты сделал часть, доделай:" in out

    def test_partial_shows_current_instructions(self):
        out = format_result(self._partial())
        assert "Инструкции:" in out
        assert "Инструкция 1" in out

    def test_partial_shows_only_not_done_checks(self):
        out = format_result(self._partial())
        assert "Чекапы:" in out
        assert "c1" not in out  # covered, not shown
        assert "m1" in out  # missing, shown

    def test_partial_shows_only_not_done_evidence(self):
        out = format_result(self._partial())
        assert "Доказательства:" in out
        assert "e1" in out

    def test_partial_no_checkmarks_for_done(self):
        """PARTIAL output must not show ✓ for done items, only ✗ for remaining."""
        out = format_result(self._partial())
        assert "✓ c1" not in out
        assert "✗ m1" in out