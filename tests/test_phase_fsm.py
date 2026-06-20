"""Tests for PhaseFSM formal state machine."""
from workflow_cli.phase_fsm import PhaseFSM


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
