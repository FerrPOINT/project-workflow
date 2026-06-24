"""Coverage gaps for wizard/evaluate.py and ui/seed.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from project_workflow.wizard.evaluate import evaluate_llm_report
from project_workflow.wizard.models import Phase
from project_workflow import config


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
    def __init__(self, verdict="PASS", next_phase=None, next_phase_name=None, blockers=None, covered=None, missing=None, message="", confidence=0.9):
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
        assert result["blockers"] == ["LLM identified blocker"]

    @patch("project_workflow.wizard.evaluate.OllamaClient")
    @patch("project_workflow.wizard.evaluate.ResponseParser")
    def test_evaluate_rollback(self, mock_parser, mock_client):
        mock_parser.parse.return_value = MockLlmResponse(verdict="ROLLBACK")
        mock_client.return_value.chat.return_value = "{}"
        engine = self._engine()
        ph = _phase(rollback_target="0")
        engine.phase_map = {"0": MagicMock(id=2)}
        result = evaluate_llm_report("rollback", ph, engine)
        assert result["verdict"] == "ROLLBACK"
        assert result["rollback_target"] == "0"

    @patch("project_workflow.wizard.evaluate.OllamaClient")
    @patch("project_workflow.wizard.evaluate.ResponseParser")
    def test_evaluate_pass_next_phase_int(self, mock_parser, mock_client):
        mock_parser.parse.return_value = MockLlmResponse(verdict="PASS", next_phase="2")
        mock_client.return_value.chat.return_value = "{}"
        engine = self._engine()
        ph = _phase()
        next_ph = MagicMock(id=5)
        next_ph.code = "2"
        engine.phase_map = {"2": next_ph}
        result = evaluate_llm_report("ok", ph, engine)
        assert result["next_phase"] == "2"


class TestSeedGaps:
    def test_update_config_phase_order_no_rows(self, monkeypatch):
        from project_workflow.interfaces.ui import seed as seed_mod
        before = list(config.PHASE_ORDER)
        uow = MagicMock()
        uow.workflows.get_default.return_value = MagicMock(id=1)
        PhaseServiceApp = MagicMock()
        PhaseServiceApp.return_value.list_phases.return_value = []
        monkeypatch.setattr(seed_mod, "PhaseServiceApp", PhaseServiceApp)
        with patch.object(seed_mod, "_get_app_state") as mock_state:
            mock_state.return_value.get_uow.return_value = uow
            seed_mod._update_config_phase_order(uow)
        assert config.PHASE_ORDER == before
