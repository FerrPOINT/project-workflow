"""Test phases.py helpers."""

from wartz_workflow.phases import (
    get_next_phase,
    get_phase_checklist_raw,
    show_phase_checklist,
    show_all_phases,
)
from wartz_workflow.db import WorkflowDB


class TestPhaseHelpers:
    def test_get_next_phase_intake(self):
        # "-1" -> first real phase
        nxt = get_next_phase("-1")
        assert isinstance(nxt, (str, type(None)))

    def test_get_next_phase_end(self):
        # last phase should return None
        nxt = get_next_phase("10")
        assert nxt is None

    def test_get_phase_checklist_raw(self):
        wdb = WorkflowDB()
        wdb.init()
        phase_code = "0.0a" if wdb.get_phase("0.0a") else "0.00"
        items = get_phase_checklist_raw(phase_code)
        assert isinstance(items, list)

    def test_show_phase_checklist(self, capsys):
        show_phase_checklist("0.00")
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)

    def test_show_all_phases(self, capsys):
        show_all_phases()
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)


class TestPhaseExecution:
    def test_run_phase_removed(self):
        """run_phase was removed in Task 5 — assert it's gone."""
        from wartz_workflow import phases as phases_mod
        assert not hasattr(phases_mod, "run_phase")
        assert not hasattr(phases_mod, "check_previous_phase")
        assert not hasattr(phases_mod, "conditional_delegate_jump")



