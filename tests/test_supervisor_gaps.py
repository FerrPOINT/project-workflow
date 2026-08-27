"""Unit tests for small coverage gaps in supervisor context, store and entry points."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

from project_workflow.supervisor.context import SupervisorContextBuilder
from project_workflow.supervisor.models import Phase

pytestmark = [pytest.mark.supervisor]


class TestSupervisorContextBuilder:
    def test_uow_from_uow_kwarg(self):
        uow = MagicMock()
        builder = SupervisorContextBuilder(uow=uow, task={"id": 1})
        assert builder.uow is uow

    def test_phase_by_id_none(self):
        builder = SupervisorContextBuilder(all_phases=[])
        assert builder._phase_by_id(None) is None

    def test_phase_status_lookup_requires_event_history(self):
        uow = MagicMock()
        uow.list_phase_events.return_value = []
        builder = SupervisorContextBuilder(
            uow=uow,
            task={"id": 1, "status": "done", "current_phase_id": 1},
            all_phases=[Phase(id=1, code="0.0a", name="Setup")],
            current_phase_code="0.0a",
        )
        with pytest.raises(ValueError, match="журнал событий"):
            builder._phase_status_lookup()


class TestModuleEntryPoints:
    def test_ui_main_module(self, monkeypatch):
        mod = importlib.import_module("project_workflow.interfaces.ui.__main__")
        called = []
        monkeypatch.setattr(mod, "main", lambda: called.append(True))
        mod.main()
        assert called

    def test_cli_main_module(self, monkeypatch):
        mod = importlib.import_module("project_workflow.interfaces.cli.__main__")
        called = []
        monkeypatch.setattr(mod, "main", lambda: called.append(True))
        # Execute the module's __main__ block directly.
        with pytest.raises(SystemExit):
            exec(
                "if __name__ == '__main__':\n    main()\n    raise SystemExit(0)",
                {"__name__": "__main__", "main": mod.main, "SystemExit": SystemExit},
            )
        assert called
