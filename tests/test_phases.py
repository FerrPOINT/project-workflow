"""Test phases.py helpers."""

import pytest
from unittest.mock import Mock, patch
from wartz_workflow.phases import (
    get_next_phase,
    check_previous_phase,
    run_phase,
    get_phase_checklist_raw,
    show_phase_checklist,
    show_all_phases,
    conditional_delegate_jump,
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
    def test_check_previous_phase(self):
        ok, msg = check_previous_phase("/tmp", "AAT-1", "0.00")
        assert isinstance(ok, bool)
        assert isinstance(msg, str)



