"""Tests for interfaces.cli.core."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner
import pytest

from project_workflow.interfaces.cli.core import _require_valid_key, cli, out_json


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
