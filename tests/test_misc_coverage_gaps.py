"""Coverage gap tests for small leftover branches."""

from __future__ import annotations

import runpy
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit]


def test_cli_module_main(tmp_path, monkeypatch):
    from project_workflow import cli as cli_mod

    fake_main = MagicMock()
    monkeypatch.setattr(cli_mod, "main", fake_main)
    monkeypatch.setattr(cli_mod, "__name__", "__main__")
    try:
        runpy.run_module("project_workflow.cli", run_name="__main__", alter_sys=True)
    except SystemExit:
        pass


def test_repositories_compat_module_imports():
    from project_workflow import infrastructure

    assert hasattr(infrastructure, "db")


def test_wizard_store_row_phase_code_from_response_dict():
    from project_workflow.wizard.store import WizardAssessmentStore

    class Row:
        response = '{"phase": "PH-1"}'

    assert WizardAssessmentStore._row_phase_code(Row()) == "PH-1"


def test_wizard_store_row_phase_code_bad_json():
    from project_workflow.wizard.store import WizardAssessmentStore

    class Row:
        response = "not-json"

    assert WizardAssessmentStore._row_phase_code(Row()) == ""


def test_wizard_store_get_latest_no_task():
    from project_workflow.wizard.store import WizardAssessmentStore

    uow = MagicMock()
    uow.tasks.get_by_key.return_value = None
    store = WizardAssessmentStore(uow)
    assert store.get_latest("MISSING", limit=1) == []


def test_wizard_store_phase_id_with_phases_attr():
    from project_workflow.wizard.store import WizardAssessmentStore

    class Ph:
        id = 7

    class Uow:
        def __init__(self):
            self.phases = MagicMock()

    uow = Uow()
    uow.phases.get_by_code.return_value = Ph()
    store = WizardAssessmentStore(uow)
    assert store._phase_id("x") == 7


def test_wizard_store_save_with_uow_attrs():
    from project_workflow.wizard.store import WizardAssessmentStore

    class Task:
        id = 1

    class Uow:
        def __init__(self):
            self.tasks = MagicMock()
            self.phases = MagicMock()
            self.supervisor_runs = MagicMock()
            self.commit = MagicMock()

    class Ph:
        id = 5

    uow = Uow()
    uow.tasks.get_by_key.return_value = Task()
    uow.phases.get_by_code.return_value = Ph()
    store = WizardAssessmentStore(uow)
    store.save({"task_key": "T-1", "phase_code": "1", "verdict": "pass"})
    uow.supervisor_runs.create.assert_called_once()
    uow.commit.assert_called_once()


def test_wizard_core_evaluate_report_no_task_blocked(monkeypatch):
    from project_workflow.wizard.core import evaluate_report

    class Engine:
        def __init__(self, *a, **kw):
            pass

        def evaluate(self, report):
            return {"verdict": "BLOCKED"}

    monkeypatch.setattr("project_workflow.wizard.WizardEngine", Engine)
    result = evaluate_report("TASK-1", "report")
    assert result["verdict"] == "BLOCKED"


def test_wizard_core_persist_supervisor_run_no_task():
    from project_workflow.wizard.core import WizardEngine

    engine = WizardEngine("TASK-1", repo="/tmp")
    engine.task = None
    engine._persist_supervisor_run(MagicMock(), None, None)
