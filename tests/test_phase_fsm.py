"""Tests for PhaseFSM formal state machine."""
from project_workflow.domain.fsm import PhaseFSM


class TestPhaseFSM:
    def test_default_state_is_in_progress(self):
        fsm = PhaseFSM()
        assert fsm.state == "in_progress"

    def test_pass_becomes_done(self):
        fsm = PhaseFSM()
        assert fsm.apply_verdict("pass") == "done"
        assert fsm.is_terminal()

    def test_partial_stays_in_progress(self):
        fsm = PhaseFSM()
        assert fsm.apply_verdict("partial") == "in_progress"
        assert not fsm.is_terminal()

    def test_block_goes_to_blocked(self):
        fsm = PhaseFSM()
        assert fsm.apply_verdict("blocked") == "blocked"
        assert fsm.is_terminal()

    def test_rollback_goes_to_rollback(self):
        fsm = PhaseFSM()
        assert fsm.apply_verdict("rollback") == "rollback"
        assert not fsm.is_terminal()

    def test_delegate_goes_to_delegated(self):
        fsm = PhaseFSM()
        assert fsm.apply_verdict("delegate") == "delegated"
        assert not fsm.is_terminal()

    def test_unknown_verdict_ignored(self):
        fsm = PhaseFSM()
        assert fsm.apply_verdict("unknown") == "in_progress"

    def test_apply_verdict_exception_returns_state(self):
        fsm = PhaseFSM()
        # Force an invalid transition that triggers AttributeError or MachineError
        assert fsm.apply_verdict("pass")  # first pass works
        # second pass after terminal should be caught by exception handler
        assert fsm.apply_verdict("pass") == "done"

    def test_show_phase_checklist_with_items(self, capsys):
        from project_workflow.domain.fsm import show_phase_checklist
        show_phase_checklist("0.00")
        captured = capsys.readouterr()
        assert "Чеклист фазы 0.00" in captured.out
        assert "[ ]" in captured.out

    def test_show_phase_checklist_empty(self, capsys):
        from project_workflow.domain.fsm import show_phase_checklist
        show_phase_checklist("-1")
        captured = capsys.readouterr()
        assert "Чеклист фазы -1" in captured.out

    def test_show_all_phases(self, capsys):
        from project_workflow.domain.fsm import show_all_phases
        from project_workflow import config
        show_all_phases()
        captured = capsys.readouterr()
        assert config.PHASE_ORDER[0] in captured.out
        assert "BLOCKER" in captured.out

    def test_get_phase_checklist_raw_empty_on_missing(self):
        from project_workflow.domain.fsm import get_phase_checklist_raw
        assert get_phase_checklist_raw("nonexistent") == []
