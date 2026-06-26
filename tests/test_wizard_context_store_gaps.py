"""Coverage gap tests for wizard context and store."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.wizard.context import WizardContextBuilder
from project_workflow.wizard.models import Phase
from project_workflow.wizard.store import WizardAssessmentStore, _row_to_assessment
from project_workflow.wizard.types import WizardAssessment


class TestWizardContextBuilder:
    def _phase(self, code="1", name="One", id=1, parallel_with=None, rollback_target=None):
        return Phase(
            code=code,
            name=name,
            id=id,
            description="",
            instructions=[],
            checks=[],
            evidence=[],
            execution_type="sync",
            parallel_with=parallel_with,
            rollback_target=rollback_target,
        )

    def test_phase_by_id_none(self):
        builder = WizardContextBuilder(all_phases=[])
        assert builder._phase_by_id(None) is None

    def test_phase_by_id_no_match(self):
        builder = WizardContextBuilder(all_phases=[self._phase(id=1)])
        assert builder._phase_by_id(99) is None

    def test_phase_status_lookup_no_phase(self):
        uow = MagicMock()
        uow.get_task_history.return_value = [{"phase_id": 99, "status": "done"}]
        builder = WizardContextBuilder(uow=uow, task={"id": 1, "status": "active", "current_phase": "1"}, all_phases=[self._phase(id=1)], current_phase="1")
        statuses = builder._phase_status_lookup()
        assert statuses == {"1": "current"}

    def test_phase_history_skips_unknown_phase(self):
        uow = MagicMock()
        uow.get_task_history.return_value = [{"phase_id": 99, "status": "done", "completed_at": "2025-01-01"}]
        builder = WizardContextBuilder(uow=uow, task={"id": 1}, all_phases=[self._phase(id=1)])
        assert builder._build_phase_history() == []

    def test_recent_verdicts_object_row(self):
        uow = MagicMock()
        row = MagicMock()
        row.phase_code = "1"
        row.verdict = "pass"
        row.blockers = []
        row.missing = []
        row.next_phase_code = None
        row.rollback_phase_code = None
        row.created_at = "2025-01-01"
        uow.get_supervisor_runs.return_value = [row]
        builder = WizardContextBuilder(uow=uow, task={"id": 1}, all_phases=[])
        verdicts = builder._build_recent_verdicts()
        assert len(verdicts) == 1
        assert verdicts[0]["verdict"] == "PASS"

    def test_build_catches_conversation_exception(self):
        uow = MagicMock()
        uow.get_task_history.return_value = []
        uow.get_supervisor_runs.return_value = []
        builder = WizardContextBuilder(
            uow=uow,
            task={"id": 1, "status": "active", "current_phase": "1"},
            project={"code": "PRJ", "name": "Project"},
            workflow={"id": 1, "name": "WF"},
            all_phases=[self._phase(id=1)],
            current_phase="1",
            task_key="PRJ-1",
        )
        with pytest.MonkeyPatch().context() as mp:
            import project_workflow.infrastructure.conversation as convo
            mp.setattr(convo, "get_messages", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
            result = builder.build()
        assert result["messages"] == []


class TestWizardAssessmentStore:
    def test_phase_id_with_phases_attr(self):
        class FakePhases:
            def get_by_code(self, code):
                return type("P", (), {"id": 5})()
        uow = type("U", (), {"phases": FakePhases()})()
        store = WizardAssessmentStore(uow)
        assert store._phase_id("1") == 5

    def test_phase_id_fallback_no_phases_attr(self):
        uow = MagicMock()
        uow.get_phase_by_code.return_value = {"id": 7}
        store = WizardAssessmentStore(uow)
        assert store._phase_id("1") == 7

    def test_row_phase_code_from_response_dict(self):
        class Row:
            response = '{"phase": "PH-1"}'
        assert WizardAssessmentStore._row_phase_code(Row()) == "PH-1"

    def test_row_phase_code_from_response_str_bad_json(self):
        class Row:
            response = "not json"
        assert WizardAssessmentStore._row_phase_code(Row()) == ""

    def test_save_without_raw_response(self):
        uow = MagicMock()
        uow.get_task_by_key.return_value = {"id": 1}
        uow.create_supervisor_run = MagicMock()
        store = WizardAssessmentStore(uow)
        assessment = WizardAssessment(
            task_key="AAT-1",
            phase_code="1",
            phase_name="One",
            verdict="pass",
            covered=["c1"],
            missing=[],
            blockers=[],
        )
        store.save(assessment)
        uow.create_supervisor_run.assert_called_once()

    def test_get_latest_by_str_task_with_phase_filter(self):
        class FakeRuns:
            def list(self, **kw):
                return [{
                    "response": '{"phase": "PH-1", "phase_code": "PH-1"}',
                    "verdict": "pass",
                    "covered": [],
                    "missing": [],
                    "blockers": [],
                    "phase_code": "PH-1",
                }]
        class FakeTasks:
            def get_by_key(self, key):
                return type("T", (), {"id": 42})()
        uow = type("U", (), {"tasks": FakeTasks(), "supervisor_runs": FakeRuns()})()
        store = WizardAssessmentStore(uow)
        results = store.get_latest("AAT-1", phase_code="PH-1")
        assert len(results) == 1


class TestRowToAssessment:
    def test_dict_row(self):
        row = {
            "response": '{"phase": "PH-1", "task_key": "AAT-1", "phase_name": "One", "phase_code": "PH-1"}',
            "verdict": "PASS",
            "covered": ["c1"],
            "missing": ["m1"],
            "blockers": ["b1"],
            "phase_code": "PH-1",
        }
        a = _row_to_assessment(row)
        assert a.phase_code == "PH-1"
        assert a.verdict == "pass"

    def test_object_row_response_parsing(self):
        class Row:
            response = '{"phase": "PH-2"}'
            verdict = "PARTIAL"
            covered = []
            missing = []
            blockers = []
        a = _row_to_assessment(Row())
        assert a.phase_code == "PH-2"
        assert a.verdict == "partial"

    def test_bad_response_string(self):
        class Row:
            response = "bad"
            verdict = "BLOCKED"
            covered = []
            missing = []
            blockers = []
        a = _row_to_assessment(Row())
        assert a.verdict == "blocked"
