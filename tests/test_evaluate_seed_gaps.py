"""Coverage gaps for supervisor/evaluate.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from sqlalchemy.exc import IntegrityError

pytestmark = [pytest.mark.supervisor]

from project_workflow.domain.exceptions import ConcurrentTransitionError
from project_workflow.infrastructure.llm import LlmConfigurationError
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

    @pytest.mark.parametrize(
        "error",
        [
            LlmConfigurationError("private-provider-detail"),
            requests.Timeout("private-provider-detail"),
            requests.HTTPError("private-provider-detail"),
            requests.ConnectionError("private-provider-detail"),
            requests.RequestException("private-provider-detail"),
            OSError("private-provider-detail"),
            ValueError("private-provider-detail"),
        ],
    )
    @patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient")
    def test_provider_failure_keeps_phase_blocked_retryable_and_redacts_details(self, mock_client, error):
        mock_client.return_value.chat.side_effect = error
        engine = self._engine()
        phase = _phase()
        self._set_phases(engine, phase)
        result = evaluate_llm_report("report", phase, engine)
        assert result["verdict"] == "BLOCKED"
        assert result["retryable"] is True
        assert result["next_phase_code"] is None
        assert result["rollback_phase_code"] is None
        assert "private-provider-detail" not in str(result)
        assert engine._record_evaluation.call_args.args[1] == "blocked"

    @pytest.mark.parametrize("verdict", ["ROLLBACK", "DELEGATE"])
    @patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient")
    @patch("project_workflow.supervisor.evaluate.ResponseParser")
    def test_provider_cannot_invent_rollback_or_delegate_policy(self, mock_parser, mock_client, verdict):
        mock_parser.parse.return_value = MockLlmResponse(verdict=verdict)
        mock_client.return_value.chat.return_value = {}
        engine = self._engine()
        phase = _phase()
        self._set_phases(engine, phase)
        result = evaluate_llm_report("report", phase, engine)
        assert result["verdict"] == "BLOCKED"
        assert result["retryable"] is True
        assert result["next_phase_code"] is None
        assert result["rollback_phase_code"] is None
        assert mock_client.return_value.chat.call_count == 3

    @pytest.mark.parametrize("point", ["before", "during"])
    @patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient")
    @patch("project_workflow.supervisor.evaluate.ResponseParser")
    def test_deleted_workflow_cannot_commit_an_evaluation(self, mock_parser, mock_client, point):
        mock_parser.parse.return_value = MockLlmResponse()
        engine = self._engine()
        phase = _phase()
        self._set_phases(engine, phase)
        engine.db.workflows.lock.side_effect = [None] if point == "before" else [object(), None]
        if point == "before":
            with pytest.raises(ConcurrentTransitionError):
                evaluate_llm_report("report", phase, engine)
            mock_client.assert_not_called()
        else:
            result = evaluate_llm_report("report", phase, engine)
            assert result["verdict"] == "BLOCKED"
            assert result["retryable"] is True
            engine.db.rollback.assert_called_once()
        engine.db.record_step.assert_not_called()
        engine._record_evaluation.assert_not_called()

    @pytest.mark.parametrize("moved", [False, True])
    @patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient")
    @patch("project_workflow.supervisor.evaluate.ResponseParser")
    def test_phase_deleted_during_provider_call_cannot_write_history(self, mock_parser, mock_client, moved):
        mock_parser.parse.return_value = MockLlmResponse()
        engine = self._engine()
        phase = _phase()
        self._set_phases(engine, phase)
        engine._blocked_result.return_value = {"verdict": "BLOCKED"}

        def delete_phase(**_kwargs):
            engine.phase_map = {}
            if moved:
                engine.current_phase_code = "2"
            return {}

        mock_client.return_value.chat.side_effect = delete_phase
        result = evaluate_llm_report("report", phase, engine)
        assert result["verdict"] == "BLOCKED"
        engine.db.record_step.assert_not_called()
        engine._record_evaluation.assert_not_called()
        engine.db.rollback.assert_called_once()

    @pytest.mark.parametrize("state", ["phase-moved", "phase-missing", "phase-unsaved"])
    @patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient")
    def test_invalid_initial_cursor_never_calls_provider_or_writes_history(self, mock_client, state):
        engine = self._engine()
        phase = _phase(id=None if state == "phase-unsaved" else 1)
        self._set_phases(engine, phase)
        engine._blocked_result.return_value = {"verdict": "BLOCKED"}
        if state == "phase-moved":
            engine.current_phase_code = "2"
        elif state == "phase-missing":
            engine.phase_map = {}
        if state == "phase-unsaved":
            with pytest.raises(ValueError, match="не сохранена"):
                evaluate_llm_report("report", phase, engine)
        else:
            result = evaluate_llm_report("report", phase, engine)
            assert result["verdict"] == "BLOCKED"
            engine.db.rollback.assert_called_once()
        mock_client.assert_not_called()
        engine.db.record_step.assert_not_called()

    @patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient")
    @patch("project_workflow.supervisor.evaluate.ResponseParser")
    def test_history_write_conflict_without_durable_response_rolls_back_and_propagates(self, mock_parser, mock_client):
        mock_parser.parse.return_value = MockLlmResponse()
        mock_client.return_value.chat.return_value = {}
        engine = self._engine()
        phase = _phase()
        self._set_phases(engine, phase)
        engine.db.record_step.side_effect = IntegrityError(
            "injected history uniqueness race", {}, Exception("conflict")
        )
        with pytest.raises(IntegrityError):
            evaluate_llm_report("report", phase, engine)
        engine.db.rollback.assert_called_once()
        engine._record_evaluation.assert_not_called()

    @pytest.mark.parametrize("task_disappears", [False, True])
    @patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient")
    @patch("project_workflow.supervisor.evaluate.ResponseParser")
    def test_identical_report_committed_during_provider_call_replays_without_second_write(
        self, mock_parser, mock_client, task_disappears
    ):
        mock_parser.parse.return_value = MockLlmResponse()
        engine = self._engine()
        phase = _phase()
        self._set_phases(engine, phase)
        response = {"verdict": "PASS", "phase_code": "1", "next_phase_code": None,
                    "rollback_phase_code": None, "message": "durable peer response"}
        run = SimpleNamespace(id=7, supervisor_response=response)

        def peer_completes(**_kwargs):
            engine.db.step_history.get_by_fingerprint.return_value = run
            engine.db.step_history.list.return_value = [run]
            engine.db.tasks.get_by_id.return_value = SimpleNamespace(current_phase_code="1", status="done")
            return {}

        def refresh_task():
            if task_disappears:
                engine.task = {}

        mock_client.return_value.chat.side_effect = peer_completes
        engine._refresh_task_state.side_effect = refresh_task
        result = evaluate_llm_report("same report", phase, engine)
        if task_disappears:
            assert result["verdict"] == "BLOCKED"
            assert result["retryable"] is True
        else:
            assert result == {**response, "replayed": True}
        # Release the initial read transaction before the provider call, then
        # close the peer-response read transaction without writing another step.
        assert engine.db.commit.call_count == 2
        engine.db.record_step.assert_not_called()
        engine._record_evaluation.assert_not_called()

    @patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient")
    @patch("project_workflow.supervisor.evaluate.ResponseParser")
    def test_different_report_committed_during_provider_call_blocks_stale_evaluation(self, mock_parser, mock_client):
        mock_parser.parse.return_value = MockLlmResponse()
        engine = self._engine()
        phase = _phase()
        self._set_phases(engine, phase)

        def peer_completes(**_kwargs):
            engine.db.step_history.list.return_value = [SimpleNamespace(id=7)]
            return {}

        mock_client.return_value.chat.side_effect = peer_completes
        result = evaluate_llm_report("stale report", phase, engine)
        assert result["verdict"] == "BLOCKED"
        assert result["retryable"] is True
        engine.db.rollback.assert_called_once()
        engine._reload_task_state.assert_called_once()
        engine.db.record_step.assert_not_called()
        engine._record_evaluation.assert_not_called()
