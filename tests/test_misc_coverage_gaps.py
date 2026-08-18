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


def test_wizard_core_has_no_rule_based_persistence_path():
    from project_workflow.wizard.core import WizardEngine

    assert not hasattr(WizardEngine, "_persist_supervisor_run")
