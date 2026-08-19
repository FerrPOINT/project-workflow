"""Tests for interfaces.cli.core."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from project_workflow.interfaces.cli.core import _require_valid_key, cli, out_json

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
        with pytest.raises(click.Abort):
            _require_valid_key("bad")


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
