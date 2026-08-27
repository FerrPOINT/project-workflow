"""Coverage gaps for supervisor/evaluate.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.supervisor.contracts import PhaseContractBuilder
from project_workflow.supervisor.evaluate import evaluate_llm_report
from project_workflow.supervisor.models import Phase


def _phase(**overrides) -> Phase:
    defaults = dict(
        id=1,
        code="1",
        name="T",
        description="",
        checks=[],
        evidence=[],
        instructions=[],
        delegate=None,
        parallel_with_phase_code=None,
        rollback_target_phase_code=None,
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
        self.raw = {}


class TestEvaluateGaps:
    def _engine(self):
        engine = MagicMock()
        engine.task_key = "RUN-1"
        engine.task = {
            "id": 1,
            "project_id": 1,
            "current_phase_id": 1,
            "current_phase_code": "1",
            "status": "active",
        }
        engine.workflow_id = 1
        engine.current_phase_code = "1"
        engine._resolve_transition.return_value = (None, None, None)
        engine.db.step_history.list.return_value = []
        engine.db.step_history.get_by_fingerprint.return_value = None
        return engine

    @staticmethod
    def _set_phases(engine, phase: Phase, *extra: Phase) -> None:
        phases = [phase, *extra]
        engine.all_phases = phases
        engine.phase_map = {item.code: item for item in phases}
        engine.contract_builder = PhaseContractBuilder(phases)

    @patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient")
    @patch("project_workflow.supervisor.evaluate.ResponseParser")
    def test_evaluate_blocked_default_blocker(self, mock_parser, mock_client):
        mock_parser.parse.return_value = MockLlmResponse(verdict="BLOCKED", blockers=["blocked"])
        mock_client.return_value.chat.return_value = {}
        engine = self._engine()
        ph = _phase()
        self._set_phases(engine, ph)
        result = evaluate_llm_report("bad", ph, engine)
        assert result["verdict"] == "BLOCKED"
        assert result["blockers"] == ["blocked"]

    @patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient")
    @patch("project_workflow.supervisor.evaluate.ResponseParser")
    def test_evaluate_rollback(self, mock_parser, mock_client):
        mock_parser.parse.return_value = MockLlmResponse(verdict="ROLLBACK")
        mock_client.return_value.chat.return_value = {}
        engine = self._engine()
        ph = _phase(rollback_target_phase_code="0")
        rollback_phase = _phase(id=2, code="0", name="Previous")
        self._set_phases(engine, ph, rollback_phase)
        engine._resolve_transition.return_value = (None, None, "0")
        result = evaluate_llm_report("rollback", ph, engine)
        assert result["verdict"] == "ROLLBACK"
        assert result["rollback_phase_code"] == "0"

    @patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient")
    @patch("project_workflow.supervisor.evaluate.ResponseParser")
    def test_evaluate_pass_next_phase_int(self, mock_parser, mock_client):
        mock_parser.parse.return_value = MockLlmResponse(verdict="PASS", next_phase="2")
        mock_client.return_value.chat.return_value = {}
        engine = self._engine()
        ph = _phase()
        next_ph = _phase(id=5, code="2", name="Next")
        self._set_phases(engine, ph, next_ph)
        engine._resolve_transition.return_value = ("2", "Next", None)
        result = evaluate_llm_report("ok", ph, engine)
        assert result["next_phase_code"] == "2"
