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
