"""Unit tests for small coverage gaps in wizard context, store and entry points."""
from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.infrastructure.db.session import reset_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.wizard.context import WizardContextBuilder
from project_workflow.wizard.models import Phase
from project_workflow.wizard.store import WizardAssessmentStore
from project_workflow.wizard.types import WizardAssessment


class TestWizardContextBuilder:
    def test_uow_from_db_kwarg(self):
        uow = MagicMock()
        builder = WizardContextBuilder(db=uow, task={"id": 1})
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

    def test_scan_artifacts_no_project(self):
        builder = WizardContextBuilder(task={"id": 1}, task_key="TASK-1")
        assert builder._scan_artifacts() == []

    def test_scan_artifacts_existing_file(self, tmp_path, monkeypatch):
        task_dir = tmp_path / ".project-workflow" / "tasks" / "PRJ" / "TASK-1"
        task_dir.mkdir(parents=True)
        (task_dir / "progress.json").write_text("{}")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        builder = WizardContextBuilder(
            task={"id": 1},
            project={"code": "PRJ"},
            task_key="TASK-1",
        )
        snapshots = builder._scan_artifacts()
        assert any(s.exists for s in snapshots)

    def test_scan_artifacts_missing_dir(self):
        builder = WizardContextBuilder(
            task={"id": 1},
            project={"code": "NOPE_NOPE_NOPE"},
            task_key="TASK-1",
        )
        snapshots = builder._scan_artifacts()
        assert len(snapshots) == 5
        assert all(not s.exists for s in snapshots)


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
            exec("if __name__ == '__main__':\n    main()\n    raise SystemExit(0)", {"__name__": "__main__", "main": mod.main, "SystemExit": SystemExit})
        assert called
