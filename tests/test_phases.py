"""Test phases.py helpers."""

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._db_helpers import phase_by_code, prepare_sqlite_uow
from tests._phase_helpers import (
    get_next_phase,
    get_phase_checklist_raw,
    show_all_phases,
    show_phase_checklist,
)


class TestPhaseHelpers:
    def test_get_next_phase_intake(self):
        assert get_next_phase("1.INTAKE") == "2.REQUIREMENTS"

    def test_get_next_phase_end(self):
        # last phase should return None
        nxt = get_next_phase("15.RETRO")
        assert nxt is None

    def test_get_phase_checklist_raw(self):
        uow = SAUnitOfWork()
        prepare_sqlite_uow(uow)
        assert phase_by_code(uow, "1.INTAKE") is not None
        items = get_phase_checklist_raw("1.INTAKE")
        assert isinstance(items, list)

    def test_show_phase_checklist(self, capsys):
        show_phase_checklist("1.INTAKE")
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)

    def test_show_all_phases(self, capsys):
        show_all_phases()
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)


class TestPhaseExecution:
    def test_run_phase_removed(self):
        """run_phase was removed in Task 5 — assert it's gone."""
        import importlib.util

        assert importlib.util.find_spec("project_workflow.domain.fsm") is None
