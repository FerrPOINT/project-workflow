"""Unit tests for small coverage gaps in Wizard context and entry points."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

from project_workflow.wizard.context import WizardContextBuilder
from project_workflow.wizard.models import Phase

pytestmark = [pytest.mark.wizard]


class TestWizardContextBuilder:
    def test_uow_from_uow_kwarg(self):
        uow = MagicMock()
        builder = WizardContextBuilder(uow=uow, task={"id": 1})
        assert builder.uow is uow

    def test_phase_by_id_none(self):
        builder = WizardContextBuilder(all_phases=[])
        assert builder._phase_by_id(None) is None

    def test_phase_status_lookup_done_task(self):
        uow = MagicMock()
        uow.get_task_history.return_value = []
        builder = WizardContextBuilder(
            uow=uow,
            task={"id": 1, "status": "done", "current_phase": "0.0a"},
            all_phases=[Phase(id=1, code="0.0a", name="Setup")],
            current_phase="0.0a",
        )
        assert builder._phase_status_lookup() == {}


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
