"""Tests for interfaces.cli.core."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from project_workflow.domain.validation import TaskKeyValidationError
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import _require_valid_key, cli, out_json
from project_workflow.interfaces.cli.ui import cli as runtime_cli

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_cli_group_sets_json_mode():
    runner = CliRunner()

    @cli.command()
    @click.pass_context
    def probe(ctx):
        click.echo(f"json={ctx.obj.get('json_mode')}")

    result = runner.invoke(cli, ["--json", "probe"])
    assert result.exit_code == 0
    assert "json=True" in result.output


def test_out_json_success(capsys):
    with pytest.raises(SystemExit) as exc:
        out_json({"ok": True})
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert '"ok": true' in captured.out


def test_out_json_failure(capsys):
    with pytest.raises(SystemExit) as exc:
        out_json({"ok": False})
    assert exc.value.code == 1


def test_require_valid_key():
    validator = MagicMock()
    validated = MagicMock()
    validated.is_valid = True
    validated.normalized = "A-1"
    validator.validate.return_value = validated
    with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=validator):
        assert _require_valid_key("a-1") == "A-1"


def test_require_valid_key_invalid():
    validator = MagicMock()
    validated = MagicMock()
    validated.is_valid = False
    validated.error_message = "bad"
    validator.validate.return_value = validated
    with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=validator):
        with pytest.raises(TaskKeyValidationError, match="bad"):
            _require_valid_key("bad")


def test_missing_database_configuration_returns_json_blocked(monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(
        "project_workflow.interfaces.cli.ui.SAUnitOfWork",
        MagicMock(side_effect=ValueError("DATABASE_URL is required")),
    )

    result = runner.invoke(runtime_cli, ["--json", "step", "--task", "TASK-1", "--report", "report"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["verdict"] == "BLOCKED"
    assert payload["retryable"] is True
    assert "DATABASE_URL" in payload["message"]


@pytest.mark.parametrize("catalog_state", ["empty", "unknown-phase"])
def test_catalog_errors_are_fail_closed_without_llm_or_audit(catalog_state):
    uow = SAUnitOfWork()
    if catalog_state == "empty":
        workflow_id = uow.workflows.create({"name": "Empty workflow"})
        project_id = uow.projects.create(
            {"workflow_id": workflow_id, "code": "EMPTY", "name": "Empty", "key_prefixes": ["EMPTY"]}
        )
        task_key = "EMPTY-1"
        task_id = uow.tasks.create(
            {"project_id": project_id, "task_key": task_key, "current_phase": "missing", "status": "active"}
        )
    else:
        project = uow.projects.get_by_code("TASK")
        task_key = "TASK-991"
        task_id = uow.tasks.create(
            {"project_id": project.id, "task_key": task_key, "current_phase": "missing", "status": "active"}
        )
    uow.commit()

    runner = CliRunner()
    with patch(
        "project_workflow.infrastructure.llm.OpenAICompatibleClient.chat",
        side_effect=AssertionError("provider must not be called"),
    ) as provider:
        result = runner.invoke(runtime_cli, ["--json", "step", "--task", task_key, "--report", "report"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["verdict"] == "BLOCKED"
    assert payload["retryable"] is True
    assert payload["phase"] == "missing"
    provider.assert_not_called()
    assert uow.supervisor_runs.list(task_id=task_id) == []
    assert uow.tasks.get_history(task_id) == []
    assert uow.tasks.get_by_id(task_id).current_phase == "missing"
    uow.close()


@pytest.mark.parametrize("args", [["--help"], ["step", "--help"], ["history", "--help"]])
def test_cli_help_is_cp1251_safe(args):
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1251"})

    result = subprocess.run(
        [sys.executable, "-m", "project_workflow.interfaces.cli", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="cp1251",
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
