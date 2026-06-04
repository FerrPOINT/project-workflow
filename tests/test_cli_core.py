"""Tests for CLI core — cli/core.py.

Uses click.testing.CliRunner (no subprocess).
"""

import json
from unittest.mock import patch

import click
from click.testing import CliRunner
import pytest

from wartz_workflow.cli.core import cli, out_json, _require_valid_key


class TestCliGroup:
    """Test the root click.Group."""

    def test_version_flag(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "wartz-workflow" in result.output
        assert "1.0.0" in result.output

    def test_help_shows_two_commands(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "step" in result.output
        assert "history" in result.output
        # ui is a third command but not counted as one of the 2 main ones
        assert "ui" in result.output

    def test_json_mode_in_context(self):
        """--json should set json_mode=True in ctx.obj."""
        @cli.command()
        @click.pass_context
        def probe(ctx):
            click.echo(f"json_mode={ctx.obj['json_mode']}")

        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "probe"])
        assert result.exit_code == 0
        assert "json_mode=True" in result.output

        result = runner.invoke(cli, ["probe"])
        assert result.exit_code == 0
        assert "json_mode=False" in result.output


class TestRequireValidKey:
    """Test _require_valid_key with valid / invalid patterns."""

    def test_valid_returns_normalized(self):
        key = _require_valid_key("TASK-42")
        assert key == "TASK-42"

    def test_valid_with_prefix(self):
        key = _require_valid_key("TASKNEIROKLYUCH-123")
        assert key == "TASKNEIROKLYUCH-123"

    def test_invalid_raises_abort(self):
        with pytest.raises(click.Abort):
            _require_valid_key("lowercase")

    def test_invalid_with_spaces(self):
        with pytest.raises(click.Abort):
            _require_valid_key("TASK 42")

    def test_invalid_digits_only(self):
        with pytest.raises(click.Abort):
            _require_valid_key("12345")


class TestOutJson:
    """Test out_json helper."""

    def test_ok_exits_zero(self):
        with pytest.raises(SystemExit) as exc:
            out_json({"ok": True, "data": "x"})
        assert exc.value.code == 0

    def test_fail_exits_one(self):
        with pytest.raises(SystemExit) as exc:
            out_json({"ok": False, "error": "bad"})
        assert exc.value.code == 1

    def test_outputs_valid_json(self, capsys):
        with pytest.raises(SystemExit):
            out_json({"status": "done"})
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["status"] == "done"
