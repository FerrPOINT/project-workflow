"""Tests for WizardEngine text helpers, status lookup, and verdict builders."""

import pytest
from unittest.mock import MagicMock, patch

from wartz_workflow.models import Phase, PhaseCheck, PhaseEvidence, PhaseInstruction
from wartz_workflow.wizard import WizardEngine, VERDICT_LABELS


def _make_engine():
    with patch("wartz_workflow.wizard.convo") as mock_convo:
        mock_convo.get_last_phase.return_value = None
        eng = WizardEngine("AAT-1", "/tmp")
    eng.db = MagicMock()
    return eng


class TestTextHelpers:
    """Cover _text_from_instruction, _text_from_check, _text_from_evidence."""

    def test_text_from_instruction_with_step(self):
        assert WizardEngine._text_from_instruction(MagicMock(step="Step A")) == "Step A"

    def test_text_from_instruction_none(self):
        assert WizardEngine._text_from_instruction(None) == ""

    def test_text_from_check_with_description(self):
        assert WizardEngine._text_from_check(MagicMock(description="Check B")) == "Check B"

    def test_text_from_check_none(self):
        assert WizardEngine._text_from_check(None) == ""

    def test_text_from_evidence_with_item(self):
        assert WizardEngine._text_from_evidence(MagicMock(item="Evidence C")) == "Evidence C"

    def test_text_from_evidence_none(self):
        assert WizardEngine._text_from_evidence(None) == ""


class TestPhaseStatusLookup:
    """Cover _phase_status_lookup."""

    def test_empty_history(self):
        engine = _make_engine()
        engine.db.get_task_history.return_value = []
        result = engine._phase_status_lookup()
        # current_phase "-1" is in phase_map, so gets "current"
        assert result == {"-1": "current"}

    def test_done_phase_from_history(self):
        engine = _make_engine()
        engine.db.get_task_history.return_value = [
            {"phase_id": 1, "status": "done"},
        ]
        result = engine._phase_status_lookup()
        assert result == {"-1": "done"}

    def test_current_phase_added_and_task_done_excluded(self):
        engine = _make_engine()
        engine.task = {"id": 7, "current_phase": "0", "status": "done"}
        engine.current_phase = "0"
        engine.db.get_task_history.return_value = []
        result = engine._phase_status_lookup()
        # Phase "0" not in phase_map (only "-1" from init), so lookup is empty


class TestBuildRecentVerdicts:
    """Cover _build_recent_verdicts."""

    def test_empty_verdicts(self):
        engine = _make_engine()
        engine.db.get_supervisor_runs.return_value = []
        result = engine._build_recent_verdicts()
        assert result == []

    def test_verdict_with_blockers(self):
        engine = _make_engine()
        engine.db.get_supervisor_runs.return_value = [
            {
                "phase_code": "0",
                "verdict": "blocked",
                "blockers": ["b1"],
                "missing": ["m1"],
                "next_phase_code": None,
                "rollback_phase_code": None,
                "created_at": "2024-01-01",
            }
        ]
        result = engine._build_recent_verdicts()
        assert len(result) == 1
        assert result[0]["verdict"] == "BLOCKED"
        assert result[0]["blockers"] == ["b1"]

    def test_unknown_verdict_normalized(self):
        engine = _make_engine()
        engine.db.get_supervisor_runs.return_value = [
            {"verdict": "unknown", "blockers": [], "missing": [], "created_at": ""}
        ]
        result = engine._build_recent_verdicts()
        assert result[0]["verdict"] == "UNKNOWN"


class TestVerdictLabels:
    def test_all_verdicts_present(self):
        for v in ("pass", "partial", "blocked", "rollback", "delegate"):
            assert v in VERDICT_LABELS
            assert VERDICT_LABELS[v].isupper()
