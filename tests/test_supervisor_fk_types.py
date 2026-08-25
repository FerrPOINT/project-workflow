"""Tests that supervisor.py passes int phase_id to DB FK columns."""

"""Tests that supervisor.py passes int phase_id to DB FK columns."""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.models import Phase


class TestRecordTransitionTypes:
    def test_record_transition_uses_int_phase_id(self):
        """add_task_history must receive int phase_id, not str code."""
        engine = SupervisorEngine("RUN-1")
        ph = Phase(id=42, code="1", name="T")
        engine.phase_map = {"1": ph}
        engine.all_phases = [ph]
        engine.current_phase = "1"

        engine.task = {"id": 7, "current_phase": engine.current_phase, "status": "active", "project_id": 1}
        engine.db = MagicMock()
        with patch.object(engine.db.tasks, "add_history") as mock_history:
            engine._record_transition(ph, "pass", "2", None)

        # First call: mark current phase done
        call1 = mock_history.call_args_list[0]
        assert isinstance(call1[0][1], int), f"phase_id must be int, got {type(call1[0][1])}"
        assert call1[0][1] == 42
        assert call1[0][2] == "done"

    def test_record_transition_next_phase_resolved_to_int(self):
        """Next phase code must be resolved to int id."""
        engine = SupervisorEngine("RUN-1")
        ph_current = Phase(id=42, code="1", name="T")
        ph_next = Phase(id=99, code="2", name="N")
        engine.phase_map = {"1": ph_current, "2": ph_next}
        engine.all_phases = [ph_current, ph_next]
        engine.current_phase = "1"

        engine.task = {"id": 7, "current_phase": engine.current_phase, "status": "active", "project_id": 1}
        engine.db = MagicMock()
        with patch.object(engine.db.tasks, "add_history") as mock_history:
            engine._record_transition(ph_current, "pass", "2", None)

        # Second call: next phase pending
        call2 = mock_history.call_args_list[1]
        assert isinstance(call2[0][1], int), f"next_phase_id must be int, got {type(call2[0][1])}"
        assert call2[0][1] == 99
        assert call2[0][2] == "pending"

    def test_record_transition_rollback_target_resolved_to_int(self):
        """Rollback target code must be resolved to int id."""
        engine = SupervisorEngine("RUN-1")
        ph = Phase(id=42, code="1", name="T", rollback_target="0")
        ph_prev = Phase(id=7, code="0", name="Prev")
        engine.phase_map = {"1": ph, "0": ph_prev}
        engine.all_phases = [ph, ph_prev]
        engine.current_phase = "1"

        engine.task = {"id": 7, "current_phase": engine.current_phase, "status": "active", "project_id": 1}
        engine.db = MagicMock()
        with patch.object(engine.db.tasks, "add_history") as mock_history:
            engine._record_transition(ph, "rollback", None, "0")

        # Second call: rollback target pending
        call2 = mock_history.call_args_list[1]
        assert isinstance(call2[0][1], int), f"rollback_phase_id must be int, got {type(call2[0][1])}"
        assert call2[0][1] == 7
        assert call2[0][2] == "pending"

    def test_evaluate_llm_uses_int_phase_id(self):
        """create_supervisor_run must receive int phase_id."""
        engine = SupervisorEngine("RUN-1")
        ph = Phase(id=42, code="1", name="T")
        engine.phase_map = {"1": ph}
        engine.all_phases = [ph]
        engine.current_phase = "1"

        engine.task = {"id": 7, "current_phase": engine.current_phase, "status": "active", "project_id": 1}
        engine.db = MagicMock()
        engine.workflow_id = 1
        engine.db.supervisor_runs.list.return_value = []
        engine.db.supervisor_runs.get_by_fingerprint.return_value = None
        with (
            patch.object(engine, "_get_previously_covered", return_value=set()),
            patch.object(engine, "_reload_evaluation_state"),
            patch.object(engine, "_reload_task_state"),
            patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient") as mock_client,
            patch.object(engine.db, "create_supervisor_run") as mock_run,
            patch.object(engine.db, "get_task", return_value=engine.task),
            patch.object(engine, "_record_transition"),
        ):
            mock_client.return_value.chat.return_value = {
                "verdict": "PASS",
                "covered": [],
                "missing": [],
                "blockers": [],
                "message": "ok",
                "confidence": 1.0,
            }
            engine.evaluate_llm("report ok", ph)

        call = mock_run.call_args
        args, kwargs = call
        payload = args[0]
        assert isinstance(payload["phase_id"], int), f"phase_id must be int, got {type(payload['phase_id'])}"
        assert payload["phase_id"] == 42
