"""WizardEngine unit tests for public supervisor behavior."""

from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.wizard import WizardEngine
from project_workflow.wizard.models import Phase


class TestWizardEvaluate:
    def _phase(self) -> Phase:
        return Phase(
            id=1,
            code="0",
            name="Test",
            description="D",
            min_time_min=0,
            is_blocker=False,
            is_delegated=False,
            is_critic=False,
            checks=[],
            evidence=[],
            instructions=[],
            delegate=None,
            next_recommendation="Move forward",
            parallel_with=None,
            rollback_target=None,
            execution_type="sync",
        )

    def test_evaluate_pass(self):
        engine = WizardEngine("TASK-1")
        ph = self._phase()
        engine.current_phase = "0"
        engine.phase_map = {"0": ph}
        engine.all_phases = [ph]
        engine.task = {"id": 1, "task_key": "AAT-1", "current_phase": "0"}

        with patch.object(engine, "evaluate_llm", return_value={"verdict": "PASS", "next_phase": "1"}) as llm:
            result = engine.evaluate("report ok")

        assert result["verdict"] == "PASS"
        assert result["next_phase"] == "1"
        llm.assert_called_once_with("report ok", ph)

    def test_evaluate_partial_when_items_missing(self):
        engine = WizardEngine("TASK-1")
        ph = self._phase()
        engine.current_phase = "0"
        engine.phase_map = {"0": ph}
        engine.all_phases = [ph]
        engine.task = {"id": 1, "task_key": "AAT-1", "current_phase": "0"}

        with patch.object(
            engine,
            "evaluate_llm",
            return_value={"verdict": "PARTIAL", "missing": ["check"]},
        ):
            result = engine.evaluate("report bad")

        assert result["verdict"] == "PARTIAL"
        assert result["missing"] == ["check"]

    def test_get_phase_prompt(self):
        engine = WizardEngine("TASK-1")
        ph = self._phase()
        engine.current_phase = "0"
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
                    "delegate_toolsets": [],
                    "next_recommendation": "Move forward",
                    "parallel_with": None,
                    "rollback_target": None,
                },
                "report_template": {"summary": "..."},
            },
        ):
            prompt = engine.get_phase_prompt()

        assert "Test" in prompt
        assert "Текущий шаг" in prompt
