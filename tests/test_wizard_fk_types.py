"""Tests that wizard.py passes int phase_id to DB FK columns."""

from unittest.mock import patch, MagicMock
from wartz_workflow.models import Phase
from wartz_workflow.wizard import WizardEngine


class TestRecordTransitionTypes:
    def test_record_transition_uses_int_phase_id(self):
        """add_task_history must receive int phase_id, not str code."""
        engine = WizardEngine("AAT-1", repo="/tmp")
        ph = Phase(id=42, code="1", name="T")
        engine.phase_map = {"1": ph}
        engine.all_phases = [ph]
        engine.current_phase = "1"

        with patch.object(engine.db, "add_task_history") as mock_history, \
             patch.object(engine.db, "update_task") as mock_update:
            engine._record_transition(ph, "pass", "2", None)

        # First call: mark current phase done
        call1 = mock_history.call_args_list[0]
        assert isinstance(call1[0][1], int), f"phase_id must be int, got {type(call1[0][1])}"
        assert call1[0][1] == 42
        assert call1[0][2] == "done"

    def test_record_transition_next_phase_resolved_to_int(self):
        """Next phase code must be resolved to int id."""
        engine = WizardEngine("AAT-1", repo="/tmp")
        ph_current = Phase(id=42, code="1", name="T")
        ph_next = Phase(id=99, code="2", name="N")
        engine.phase_map = {"1": ph_current, "2": ph_next}
        engine.all_phases = [ph_current, ph_next]
        engine.current_phase = "1"

        with patch.object(engine.db, "add_task_history") as mock_history, \
             patch.object(engine.db, "update_task") as mock_update:
            engine._record_transition(ph_current, "pass", "2", None)

        # Second call: next phase pending
        call2 = mock_history.call_args_list[1]
        assert isinstance(call2[0][1], int), f"next_phase_id must be int, got {type(call2[0][1])}"
        assert call2[0][1] == 99
        assert call2[0][2] == "pending"

    def test_record_transition_rollback_target_resolved_to_int(self):
        """Rollback target code must be resolved to int id."""
        engine = WizardEngine("AAT-1", repo="/tmp")
        ph = Phase(id=42, code="1", name="T", rollback_target="0")
        ph_prev = Phase(id=7, code="0", name="Prev")
        engine.phase_map = {"1": ph, "0": ph_prev}
        engine.all_phases = [ph, ph_prev]
        engine.current_phase = "1"

        with patch.object(engine.db, "add_task_history") as mock_history, \
             patch.object(engine.db, "update_task") as mock_update:
            engine._record_transition(ph, "rollback", None, "0")

        # Second call: rollback target pending
        call2 = mock_history.call_args_list[1]
        assert isinstance(call2[0][1], int), f"rollback_phase_id must be int, got {type(call2[0][1])}"
        assert call2[0][1] == 7
        assert call2[0][2] == "pending"

    def test_evaluate_llm_uses_int_phase_id(self):
        """create_supervisor_run must receive int phase_id."""
        engine = WizardEngine("AAT-1", repo="/tmp")
        ph = Phase(id=42, code="1", name="T")
        engine.phase_map = {"1": ph}
        engine.all_phases = [ph]
        engine.current_phase = "1"

        with patch.object(engine, "_get_previously_covered", return_value=set()), \
             patch("wartz_workflow.wizard.OllamaClient") as mock_client, \
             patch.object(engine.db, "create_supervisor_run") as mock_run, \
             patch.object(engine.db, "get_task", return_value=engine.task), \
             patch.object(engine, "_record_transition"):
            mock_client.return_value.chat.return_value = {
                "verdict": "PASS",
                "covered": [], "missing": [], "blockers": [],
                "message": "ok", "next_phase": None, "next_phase_name": None,
                "confidence": 1.0,
            }
            engine.evaluate_llm("report ok", ph)

        call = mock_run.call_args
        args, kwargs = call
        payload = args[0]
        assert isinstance(payload["phase_id"], int), f"phase_id must be int, got {type(payload['phase_id'])}"
        assert payload["phase_id"] == 42
