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


@pytest.mark.parametrize("args", [["--help"], ["step", "--help"], ["history", "--help"]])
def test_cli_help_is_fully_russian(args):
    result = CliRunner().invoke(runtime_cli, args)

    assert result.exit_code == 0
    assert "Использование:" in result.output
    assert "Параметры:" in result.output
    assert "Показать справку и выйти." in result.output
    assert "Usage:" not in result.output
    assert "Options:" not in result.output
    assert "Show this message and exit." not in result.output
    if args == ["--help"]:
        assert "Команды:" in result.output
        assert "Показать версию и выйти." in result.output


def test_cli_version_message_is_russian():
    result = CliRunner().invoke(runtime_cli, ["--version"])

    assert result.exit_code == 0
    assert result.output == "project-workflow, версия 1.0.0\n"


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
        MagicMock(side_effect=ValueError("Переменная DATABASE_URL обязательна")),
    )

    result = runner.invoke(runtime_cli, ["--json", "step", "--task", "RUN-1", "--report", "report"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["verdict"] == "BLOCKED"
    assert payload["retryable"] is True
    assert "DATABASE_URL" in payload["message"]


def test_task_snapshot_cannot_reference_unknown_phase():
    from sqlalchemy.exc import IntegrityError

    uow = SAUnitOfWork()
    project = uow.projects.get_by_code("RUN")
    assert project is not None
    with pytest.raises(IntegrityError):
        uow.tasks.create(
            {
                "project_id": project.id,
                "workflow_id": project.workflow_id,
                "task_key": "RUN-991",
                "current_phase_id": 999999,
                "status": "active",
            }
        )
        uow.commit()
    uow.rollback()
    assert uow.tasks.get_by_key("RUN-991") is None
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
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
