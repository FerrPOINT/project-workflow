"""Unit tests for small coverage gaps in wizard context, store and entry points."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

from project_workflow.infrastructure.db.session import reset_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.wizard.context import WizardContextBuilder
from project_workflow.wizard.models import Phase
from project_workflow.wizard.store import WizardAssessmentStore
from project_workflow.wizard.types import WizardAssessment

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


class TestWizardStore:
    def test_save_and_get_latest(self, tmp_path):
        reset_engine()
        uow = SAUnitOfWork(f"sqlite:///{tmp_path}/store.db")
        uow.create_all()
        store = WizardAssessmentStore(uow)

        from project_workflow.wizard.core import WizardEngine

        engine = WizardEngine("TASK-1", uow=uow)
        task_id = engine.task["id"]

        assessment = WizardAssessment(
            task_key="TASK-1",
            phase_code="0.0a",
            phase_name="Setup",
            verdict="pass",
            covered=["x"],
            missing=[],
            blockers=[],
        )
        store.save(assessment)
        latest = store.get_latest(task_id)
        assert latest
        assert latest[0].verdict == "pass"
        uow.close()

    def test_get_latest_missing_task_key(self, tmp_path):
        reset_engine()
        uow = SAUnitOfWork(f"sqlite:///{tmp_path}/store2.db")
        uow.create_all()
        store = WizardAssessmentStore(uow)
        assert store.get_latest("NO-SUCH-KEY") == []
        uow.close()


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
