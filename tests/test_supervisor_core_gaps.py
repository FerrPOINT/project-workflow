"""SupervisorEngine coverage gap tests for supervisor/core.py helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.domain.exceptions import ConcurrentTransitionError, ConflictError
from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.models import Phase


class TestSupervisorCoreGaps:
    @staticmethod
    def _phase(
        code: str = "1",
        name: str = "Test",
        id: int = 1,
        rollback_target: str | None = None,
        parallel_with: str | None = None,
        execution_type: str = "sync",
    ) -> Phase:
        return Phase(
            id=id,
            code=code,
            name=name,
            description="",
            checks=[],
            evidence=[],
            instructions=[],
            parallel_with_phase_code=parallel_with,
            rollback_target_phase_code=rollback_target,
            execution_type=execution_type,
        )

    def test_resolve_current_phase_no_task(self):
        engine = SupervisorEngine("RUN-1")
        engine.task = None
        assert engine._resolve_current_phase_code() == ""

    def test_resolve_current_phase_preserves_unknown_value(self):
        engine = SupervisorEngine("RUN-1")
        ph = self._phase(code="1", id=1)
        engine.all_phases = [ph]
        engine.phase_map = {"1": ph}
        engine.task = {"id": 1, "current_phase_id": 99, "current_phase_code": "99"}
        assert engine._resolve_current_phase_code() == "99"

    def test_resolve_current_phase_empty_current(self):
        engine = SupervisorEngine("RUN-1")
        ph = self._phase(code="1", id=1)
        engine.all_phases = [ph]
        engine.phase_map = {"1": ph}
        engine.task = {"id": 1, "current_phase_id": 1, "current_phase_code": ""}
        with pytest.raises(ValueError, match="current_phase_code"):
            engine._resolve_current_phase_code()

    def test_get_previously_covered_no_task(self):
        engine = SupervisorEngine("RUN-1")
        engine.task = None
        assert engine._get_previously_covered("1") == set()

    def test_phase_contract_includes_feedback_after_rollback(self):
        engine = SupervisorEngine("RUN-1")
        implementation = self._phase(code="8.IMPLEMENT", id=8)
        engine.all_phases = [implementation]
        engine.phase_map = {implementation.code: implementation}
        engine.current_phase_code = implementation.code
        engine.get_full_context = MagicMock(
            return_value={
                "recent_verdicts": [
                    {
                        "phase_code": "10.REVIEW",
                        "verdict": "ROLLBACK",
                        "message": "Fix the JavaScript syntax error",
                        "missing": ["Нет correctness-дефектов"],
                        "blockers": [],
                        "rollback_phase_code": "8.IMPLEMENT",
                    }
                ]
            }
        )

        contract = engine.get_phase_contract()

        assert contract is not None
        assert contract["evaluation_feedback"]["verdict"] == "ROLLBACK"
        assert contract["evaluation_feedback"]["message"] == (
            "Fix the JavaScript syntax error"
        )

    def test_get_previously_covered_no_task_id(self):
        engine = SupervisorEngine("RUN-1")
        engine.task = {"id": 0}
        assert engine._get_previously_covered("1") == set()

    def test_get_previously_covered_run_phase_id_none(self):
        engine = SupervisorEngine("RUN-1")
        engine.task = {"id": 1}
        uow = MagicMock()
        Run = type("R", (), {"to_dict": lambda self: {"phase_id": None, "covered": []}})()
        uow.step_history.list.return_value = [Run]
        engine._uow = uow
        assert engine._get_previously_covered("1") == set()

    def test_get_previously_covered_phase_mismatch(self):
        engine = SupervisorEngine("RUN-1")
        ph = self._phase(code="1", id=1)
        engine.all_phases = [ph]
        engine.phase_map = {"1": ph}
        engine.task = {"id": 1}
        db = MagicMock()
        db.phases.get_by_id.return_value = ph
        Row = type("R", (), {"to_dict": lambda self: {"phase_id": 1, "covered": []}})()
        db.step_history.list.return_value = [Row]
        engine.db = db
        assert engine._get_previously_covered("99") == set()

    def test_record_transition_no_task(self):
        engine = SupervisorEngine("RUN-1")
        engine.task = None
        ph = self._phase(code="1", id=1)
        with pytest.raises(ConcurrentTransitionError, match="Задача отсутствует"):
            engine._record_transition(ph, "pass", None, None, 55)

    def test_record_transition_requires_complete_task_state(self):
        engine = SupervisorEngine("RUN-1")
        engine.task = {"id": 1}
        ph = self._phase(code="1", id=1)
        engine.phase_map = {"1": ph}
        engine.db = MagicMock()

        with pytest.raises(ConcurrentTransitionError, match="Состояние задачи"):
            engine._record_transition(ph, "pass", None, None, 55)

        engine.db.tasks.update_if_state.assert_not_called()
        engine.db.tasks.record_phase_event.assert_not_called()

    def test_record_transition_delegated(self):
        engine = SupervisorEngine("RUN-1")
        engine.task = {"id": 1, "current_phase_id": 1, "current_phase_code": "1", "status": "active"}
        ph = self._phase(code="1", id=1)
        engine.phase_map = {"1": ph}
        db = MagicMock()
        engine.db = db
        engine._record_transition(ph, "delegate", None, None, 55)
        db.tasks.record_phase_event.assert_not_called()
        db.tasks.update_if_state.assert_called_once()

    def test_record_transition_partial(self):
        engine = SupervisorEngine("RUN-1")
        engine.task = {"id": 1, "current_phase_id": 1, "current_phase_code": "1", "status": "active"}
        ph = self._phase(code="1", id=1)
        engine.phase_map = {"1": ph}
        db = MagicMock()
        engine.db = db
        engine._record_transition(ph, "partial", None, None, 55)
        db.tasks.record_phase_event.assert_not_called()
        db.tasks.update_if_state.assert_called_once()

    def test_record_parallel_transition_blocked(self):
        engine = SupervisorEngine("RUN-1")
        engine.task = {"id": 1, "current_phase_id": 1, "current_phase_code": "1", "status": "active"}
        ph = self._phase(code="1", id=1)
        engine.phase_map = {"1": ph}
        db = MagicMock()
        engine.db = db
        engine._record_parallel_transition([ph], "blocked", None, step_history_id=55)
        db.tasks.update_if_state.assert_called_once()

    def test_record_parallel_transition_rollback(self):
        engine = SupervisorEngine("RUN-1")
        engine.task = {"id": 1, "current_phase_id": 1, "current_phase_code": "1", "status": "active"}
        ph = self._phase(code="1", id=1)
        engine.phase_map = {"1": ph, "0": self._phase(id=2, code="0")}
        db = MagicMock()
        engine.db = db
        engine._record_parallel_transition([ph], "rollback", None, "0", step_history_id=55)
        db.tasks.update_if_state.assert_called_once()

    def test_reload_task_state_does_not_keep_deleted_task(self):
        engine = SupervisorEngine("RUN-1")
        engine.task = {"id": 1, "current_phase_id": 1, "current_phase_code": "1", "status": "active"}
        engine.current_phase_code = "1"
        engine.db = MagicMock()
        engine._task_service.get_task = MagicMock(return_value=None)

        engine._reload_task_state()

        assert engine.task is None
        assert engine.current_phase_code == ""

    def test_ensure_task_returns_existing_strict_snapshot(self):
        engine = SupervisorEngine("RUN-1")
        svc = MagicMock()
        svc.get_task_by_key.return_value = {
            "id": 1,
            "project_id": 1,
            "workflow_id": 1,
            "current_phase_id": 2,
            "current_phase_code": "1.INTAKE",
        }
        engine._task_service = svc
        result = engine._ensure_task()
        assert result["current_phase_id"] == 2

    def test_ensure_task_create_if_missing_false(self):
        engine = SupervisorEngine("RUN-1")
        engine.create_if_missing = False
        svc = MagicMock()
        svc.get_task_by_key.return_value = None
        engine._task_service = svc
        with pytest.raises(ValueError, match="не найдена"):
            engine._ensure_task()

    def test_ensure_task_rereads_same_project_after_concurrent_create(self):
        engine = SupervisorEngine("RUN-1")
        service = MagicMock()
        service.get_task_by_key.side_effect = [
            None,
            {"id": 7, "project_id": 3, "task_key": "RUN-1"},
        ]
        service.create_task.side_effect = ConflictError("already exists")
        engine._task_service = service
        engine._resolve_project = MagicMock(return_value={"id": 3, "workflow_id": 1})
        engine._first_phase_id_for_project = MagicMock(return_value=1)

        task = engine._ensure_task()

        assert task["id"] == 7
        assert service.get_task_by_key.call_count == 2

    def test_ensure_task_does_not_hide_cross_project_conflict(self):
        engine = SupervisorEngine("RUN-1")
        service = MagicMock()
        service.get_task_by_key.side_effect = [
            None,
            {"id": 8, "project_id": 4, "task_key": "RUN-1"},
        ]
        service.create_task.side_effect = ConflictError("already exists")
        engine._task_service = service
        engine._resolve_project = MagicMock(return_value={"id": 3, "workflow_id": 1})
        engine._first_phase_id_for_project = MagicMock(return_value=1)

        with pytest.raises(ConflictError, match="already exists"):
            engine._ensure_task()

    def test_format_result_pass_sync_after_parallel(self):
        from project_workflow.supervisor import format_result

        text = format_result(
            {
                "verdict": "PASS",
                "phase_name": "Parallel block",
                "phase": "parallel.foo",
                "next_phase_contract": {
                    "instructions": ["do"],
                    "required_checks": ["check"],
                    "required_evidence": ["ev"],
                    "execution_type": "sync",
                },
            }
        )
        assert "Инструкции:" in text
        assert "  · do" in text
        assert "параллельного блока" not in text

    def test_format_result_pass_parallel(self):
        from project_workflow.supervisor import format_result

        text = format_result(
            {
                "verdict": "PASS",
                "next_phase_contract": {
                    "instructions": ["do"],
                    "required_checks": ["check"],
                    "required_evidence": ["ev"],
                    "execution_type": "parallel",
                    "parallel_with_phase_code": "PH-1",
                },
            }
        )
        assert "Инструкции:" in text
        assert "  · do" in text
        assert "Параллельно" not in text
