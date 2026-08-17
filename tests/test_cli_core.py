"""Tests for the canonical project-workflow CLI."""

from __future__ import annotations

import subprocess
import sys

from click.testing import CliRunner

from project_workflow.interfaces.cli import cli
from project_workflow.interfaces.cli import v2 as cli_v2


def test_cli_group_sets_json_mode(monkeypatch):
    class Adapter:
        profile = "feature"

        @staticmethod
        def as_dict():
            return {"taskKey": "AAT-1", "jiraRevision": "jira-1"}

    class Engine:
        @staticmethod
        def open_task(task, profile):
            return {"taskKey": task["taskKey"], "profile": profile}

    class Uow:
        @staticmethod
        def close():
            return None

    source = type("Source", (), {"read": lambda _, __: Adapter()})()
    monkeypatch.setattr(cli_v2.CommandTaskAdapter, "from_env", lambda: source)
    monkeypatch.setattr(cli_v2, "_engine", lambda: (Uow(), Engine()))

    result = CliRunner().invoke(cli, ["--json", "current", "--task", "AAT-1"])
    assert result.exit_code == 0
    assert '"ok": true' in result.output


def test_cli_exposes_only_canonical_controller_commands():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for command in ("current", "submit"):
        assert command in result.output
    for command in ("catalog", "start", "history", "evidence-export", "validate"):
        assert command not in result.output
    assert "step" not in result.output
    assert "v2" not in result.output


def test_fresh_process_can_import_uow_bootstrap_without_wizard_cycle():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
