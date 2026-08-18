"""Coverage gaps for Wizard LLM evaluation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.wizard.evaluate import evaluate_llm_report
from project_workflow.wizard.models import Phase


def _phase(**overrides) -> Phase:
    defaults = dict(
        id=1,
        code="1",
        name="T",
        description="",
        min_time_min=0,
        is_blocker=False,
        is_delegated=False,
        is_critic=False,
        checks=[],
        evidence=[],
        instructions=[],
        delegate=None,
        next_recommendation="",
        parallel_with=None,
        rollback_target=None,
        execution_type="sync",
    )
    defaults.update(overrides)
    return Phase(**defaults)


class MockLlmResponse:
    def __init__(
        self,
        verdict="PASS",
        next_phase=None,
        next_phase_name=None,
        blockers=None,
        covered=None,
        missing=None,
        message="",
        confidence=0.9,
    ):
        self.verdict = verdict
        self.next_phase = next_phase
        self.next_phase_name = next_phase_name
        self.blockers = blockers or []
        self.covered = covered or []
        self.missing = missing or []
        self.message = message
        self.confidence = confidence


class TestEvaluateGaps:
    def _engine(self):
        engine = MagicMock()
        engine.all_phases = []
        engine.task_key = "TASK-1"
        engine.task = {"id": 1}
        engine.phase_map = {}
        engine._resolve_transition.return_value = (None, None, None)
        return engine

    @patch("project_workflow.wizard.evaluate.OllamaClient")
    @patch("project_workflow.wizard.evaluate.ResponseParser")
    def test_evaluate_blocked_default_blocker(self, mock_parser, mock_client):
        mock_parser.parse.return_value = MockLlmResponse(verdict="BLOCKED")
        mock_client.return_value.chat.return_value = "{}"
        engine = self._engine()
        ph = _phase()
        result = evaluate_llm_report("bad", ph, engine)
        assert result["verdict"] == "BLOCKED"
        assert result["blockers"] == ["Wizard identified a blocker"]

    @patch("project_workflow.wizard.evaluate.OllamaClient")
    @patch("project_workflow.wizard.evaluate.ResponseParser")
    def test_evaluate_rollback(self, mock_parser, mock_client):
        mock_parser.parse.return_value = MockLlmResponse(verdict="ROLLBACK")
        mock_client.return_value.chat.return_value = "{}"
        engine = self._engine()
        engine._resolve_transition.return_value = (None, None, "0")
        ph = _phase(rollback_target="0")
        engine.phase_map = {"0": MagicMock(id=2)}
        result = evaluate_llm_report("rollback", ph, engine)
        assert result["verdict"] == "ROLLBACK"
        assert result["rollback_target"] == "0"

    @patch("project_workflow.wizard.evaluate.OllamaClient")
    @patch("project_workflow.wizard.evaluate.ResponseParser")
    def test_evaluate_pass_next_phase_int(self, mock_parser, mock_client):
        mock_parser.parse.return_value = MockLlmResponse(verdict="PASS", next_phase="invented")
        mock_client.return_value.chat.return_value = "{}"
        engine = self._engine()
        engine._resolve_transition.return_value = ("2", "Next", None)
        ph = _phase()
        next_ph = MagicMock(id=5)
        next_ph.code = "2"
        next_ph.name = "Next"
        next_ph.execution_type = "sync"
        engine.phase_map = {"2": next_ph}
        engine.all_phases = [ph, next_ph]
        result = evaluate_llm_report("ok", ph, engine)
        assert result["next_phase"] == "2"
