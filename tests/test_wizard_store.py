"""Tests for wizard_store.py — WizardAssessmentStore persistence."""
import json
from unittest.mock import MagicMock

from workflow_cli.wizard_store import WizardAssessmentStore, _row_to_assessment
from workflow_cli.wizard_types import WizardAssessment


class TestWizardAssessmentStore:
    def _make_db(self):
        db = MagicMock()
        db.get_phase_by_code.side_effect = lambda code: {
            "1": {"id": 101},
            "2": {"id": 102},
            "rollback-1": {"id": 201},
        }.get(code)
        db.get_task_by_key.return_value = {"id": 42}
        db.create_supervisor_run = MagicMock()
        db.get_supervisor_runs.return_value = []
        return db

    def test_save_pass_with_next_phase(self):
        db = self._make_db()
        store = WizardAssessmentStore(db)
        assessment = WizardAssessment(
            task_key="TASK-1",
            phase_code="1",
            phase_name="Phase One",
            verdict="pass",
            covered=["Done A"],
            missing=[],
            blockers=[],
            next_phase="2",
            next_phase_name="Phase Two",
        )
        store.save(assessment)
        db.create_supervisor_run.assert_called_once()
        payload = db.create_supervisor_run.call_args[0][0]
        assert payload["task_id"] == 42
        assert payload["phase_id"] == 101
        assert payload["verdict"] == "pass"
        assert payload["covered"] == ["Done A"]
        assert payload["next_phase_id"] == 102
        assert payload["rollback_phase_id"] is None

    def test_save_blocked_with_rollback(self):
        db = self._make_db()
        store = WizardAssessmentStore(db)
        assessment = WizardAssessment(
            task_key="TASK-1",
            phase_code="1",
            phase_name="Phase One",
            verdict="blocked",
            covered=[],
            missing=["Need X"],
            blockers=["No access"],
            rollback_target="rollback-1",
        )
        store.save(assessment)
        payload = db.create_supervisor_run.call_args[0][0]
        assert payload["verdict"] == "blocked"
        assert payload["rollback_phase_id"] == 201
        assert payload["next_phase_id"] is None

    def test_save_unknown_phase_code(self):
        db = self._make_db()
        store = WizardAssessmentStore(db)
        assessment = WizardAssessment(
            task_key="TASK-1",
            phase_code="unknown",
            phase_name="Unknown",
            verdict="partial",
        )
        store.save(assessment)
        payload = db.create_supervisor_run.call_args[0][0]
        assert payload["phase_id"] == "unknown"

    def test_get_latest_empty(self):
        db = self._make_db()
        store = WizardAssessmentStore(db)
        assert store.get_latest(42) == []

    def test_get_latest_parses_response(self):
        db = self._make_db()
        db.get_supervisor_runs.return_value = [
            {
                "response": json.dumps({
                    "task_key": "T-1",
                    "phase": "1",
                    "phase_name": "P1",
                    "next_phase": "2",
                    "next_phase_name": "P2",
                    "rollback_target": None,
                    "message": "ok",
                    "instructions": ["Inst"],
                    "required_checks": ["Ch"],
                    "required_evidence": ["Ev"],
                }),
                "verdict": "pass",
                "covered": ["A"],
                "missing": [],
                "blockers": [],
            }
        ]
        store = WizardAssessmentStore(db)
        results = store.get_latest(42, limit=1)
        assert len(results) == 1
        r = results[0]
        assert r.task_key == "T-1"
        assert r.verdict == "pass"
        assert r.covered == ["A"]
        assert r.next_phase == "2"

    def test_get_latest_parses_string_response(self):
        db = self._make_db()
        db.get_supervisor_runs.return_value = [
            {"response": "not json", "verdict": "partial", "covered": [], "missing": [], "blockers": []}
        ]
        store = WizardAssessmentStore(db)
        results = store.get_latest(42)
        assert len(results) == 1
        assert results[0].task_key == ""  # defaults on parse failure


class TestRowToAssessment:
    def test_basic(self):
        row = {
            "response": json.dumps({
                "task_key": "TK",
                "phase": "1",
                "phase_name": "One",
                "next_phase": "2",
                "next_phase_name": "Two",
                "rollback_target": None,
                "message": "m",
                "instructions": ["i"],
                "required_checks": ["c"],
                "required_evidence": ["e"],
            }),
            "verdict": "pass",
            "covered": ["A"],
            "missing": ["B"],
            "blockers": [],
        }
        a = _row_to_assessment(row)
        assert a.task_key == "TK"
        assert a.phase_code == "1"
        assert a.verdict == "pass"
        assert a.covered == ["A"]
        assert a.missing == ["B"]
        assert a.next_phase == "2"

    def test_empty_response_defaults(self):
        row = {
            "response": None,
            "verdict": "blocked",
            "phase_code": "3",
            "covered": [],
            "missing": [],
            "blockers": ["No"],
        }
        a = _row_to_assessment(row)
        assert a.task_key == ""
        assert a.phase_code == "3"
        assert a.verdict == "blocked"
        assert a.blockers == ["No"]
