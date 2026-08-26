"""SupervisorEngine unit tests for public supervisor behavior."""

from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.models import Phase


class TestSupervisorEvaluate:
    def _phase(self) -> Phase:
        return Phase(
            id=1,
            code="0",
            name="Test",
            description="D",
            checks=[],
            evidence=[],
            instructions=[],
            delegate=None,
            parallel_with_phase_code=None,
            rollback_target_phase_code=None,
            execution_type="sync",
        )

    def test_evaluate_pass(self):
        engine = SupervisorEngine("RUN-1")
        ph = self._phase()
        engine.current_phase_code = "0"
        engine.phase_map = {"0": ph}
        engine.all_phases = [ph]
        engine.task = {"id": 1, "task_key": "AAT-1", "current_phase_id": 1, "current_phase_code": "0"}

        with patch.object(
            engine,
            "evaluate_llm",
            return_value={"verdict": "PASS", "next_phase_code": "1"},
        ) as llm:
            result = engine.evaluate("report ok")

        assert result["verdict"] == "PASS"
        assert result["next_phase_code"] == "1"
        llm.assert_called_once_with("report ok", ph)

    def test_evaluate_partial_when_items_missing(self):
        engine = SupervisorEngine("RUN-1")
        ph = self._phase()
        engine.current_phase_code = "0"
        engine.phase_map = {"0": ph}
        engine.all_phases = [ph]
        engine.task = {"id": 1, "task_key": "AAT-1", "current_phase_id": 1, "current_phase_code": "0"}

        with patch.object(
            engine,
            "evaluate_llm",
            return_value={"verdict": "PARTIAL", "missing": ["check"]},
        ):
            result = engine.evaluate("report bad")

        assert result["verdict"] == "PARTIAL"
        assert result["missing"] == ["check"]

    def test_evaluate_completed_task_does_not_call_llm(self):
        engine = SupervisorEngine("RUN-1")
        ph = self._phase()
        engine.current_phase_code = "0"
        engine.phase_map = {"0": ph}
        engine.all_phases = [ph]
        engine.task = {
            "id": 1,
            "task_key": "RUN-1",
            "current_phase_id": 1,
            "current_phase_code": "0",
            "status": "done",
        }

        with patch.object(engine, "evaluate_llm") as llm:
            result = engine.evaluate("new report after completion")

        llm.assert_not_called()
        assert result["verdict"] == "PASS"
        assert result["status"] == "done"
        assert result["next_phase_code"] is None
        assert result["replayed"] is False
        assert "уже завершён" in result["message"]

    def test_evaluate_completed_task_survives_missing_catalog_phase(self):
        engine = SupervisorEngine("RUN-1")
        engine.current_phase_code = "retired-phase"
        engine.phase_map = {}
        engine.all_phases = []
        engine.task = {
            "id": 1,
            "task_key": "RUN-1",
            "current_phase_id": 999,
            "current_phase_code": "retired-phase",
            "status": "done",
        }

        with patch.object(engine, "evaluate_llm") as llm:
            result = engine.evaluate("new report after completion")

        llm.assert_not_called()
        assert result["verdict"] == "BLOCKED"
        assert result["phase_code"] == "retired-phase"
        assert result["retryable"] is True

    def test_get_phase_prompt(self):
        engine = SupervisorEngine("RUN-1")
        ph = self._phase()
        engine.current_phase_code = "0"
        engine.phase_map = {"0": ph}
        engine.all_phases = [ph]

        with patch.object(
            engine,
            "get_full_context",
            return_value={
                "workflow_name": "WF",
                "workflow_path": [{"code": "0", "name": "Test", "status": "current"}],
                "current_contract": {
                    "phase_code": "0",
                    "phase_name": "Test",
                    "description": "D",
                    "instructions": [],
                    "required_checks": [],
                    "required_evidence": [],
                    "execution_type": "sync",
                    "delegate_agent": None,
                    "parallel_with_phase_code": None,
                    "rollback_target_phase_code": None,
                },
                "report_template": {"summary": "..."},
            },
        ):
            prompt = engine.get_phase_prompt()

        assert "Test" in prompt
        assert "Текущий шаг" in prompt
