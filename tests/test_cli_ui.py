"""Tests for CLI commands step + history in cli/ui.py.

Uses click.testing.CliRunner with heavy mocking to avoid FS/DB side effects.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import click
from click.testing import CliRunner
import pytest

from wartz_workflow.cli.core import cli
from wartz_workflow.task_validator import TaskKeyValidator


# ── Helpers ──────────────────────────────────────────────────────────

def _mock_state():
    return {
        "repo": "/repo",
        "task_key": "TASK-1",
        "current_phase": "0",
        "phases_completed": [],
    }


def _validator() -> TaskKeyValidator:
    return TaskKeyValidator.from_projects([
        {
            "code": "TASK",
            "name": "TASK",
            "key_patterns": [r"^(?P<prefix>TASK)-(?P<number>[0-9]+)$"],
        }
    ])


class TestStepCommand:
    """Test `wartz-workflow step --task TASK-1`"""

    @patch("wartz_workflow.state.find_repo", return_value="/repo")
    @patch("wartz_workflow.state.load_state", return_value=None)
    @patch("wartz_workflow.state.create_task_dir", return_value=(True, Path("/repo/sprint/TASK-1")))
    @patch("wartz_workflow.wizard.main")
    def test_step_auto_init_creates_task(self, mock_main, mock_create, mock_load, mock_find):
        runner = CliRunner()
        with patch("wartz_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "TASK-1"])
        assert result.exit_code == 0
        mock_create.assert_called_once()

    @patch("wartz_workflow.state.find_repo", return_value="/repo")
    @patch("wartz_workflow.state.load_state", return_value=_mock_state())
    @patch("wartz_workflow.wizard.main")
    def test_step_shows_phase(self, mock_main, mock_load, mock_find):
        runner = CliRunner()
        with patch("wartz_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "TASK-1"])
        assert result.exit_code == 0
        mock_main.assert_called_once()

    @patch("wartz_workflow.state.find_repo", return_value="/repo")
    @patch("wartz_workflow.state.load_state", return_value=_mock_state())
    @patch("wartz_workflow.wizard.evaluate_report", return_value={"verdict": "PASS", "next_phase": "1"})
    def test_step_report_pass(self, mock_eval, mock_load, mock_find):
        runner = CliRunner()
        with patch("wartz_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "TASK-1", "--report", "Done"])
        assert result.exit_code == 0
        mock_eval.assert_called_once_with("TASK-1", "Done", "/repo")
        parsed = json.loads(result.output)
        assert parsed["verdict"] == "PASS"

    @patch("wartz_workflow.state.find_repo", return_value="/repo")
    @patch("wartz_workflow.state.load_state", return_value=_mock_state())
    @patch("wartz_workflow.wizard.evaluate_report", return_value={"verdict": "FAIL", "next_phase": None})
    def test_step_report_fail_exits_one(self, mock_eval, mock_load, mock_find):
        runner = CliRunner()
        with patch("wartz_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "TASK-1", "--report", "Bad"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["verdict"] == "FAIL"

    def test_step_skip_is_rejected(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["step", "--task", "TASK-1", "--skip"])
        assert result.exit_code != 0
        assert "No such option '--skip'" in result.output

    def test_step_repo_is_rejected(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["step", "--task", "TASK-1", "--repo", "/repo"])
        assert result.exit_code != 0
        assert "No such option '--repo'" in result.output


class TestHistoryCommand:
    """Test `wartz-workflow history --task TASK-1`"""

    @patch("wartz_workflow.cli.ui.convo.get_messages", return_value=[
        SimpleNamespace(role="user", phase_id="0", tags="transition", content="Done", created_at="2024-01-01"),
        SimpleNamespace(role="agent", phase_id="0", tags="", content="OK", created_at="2024-01-02"),
    ])
    def test_history_shows_records(self, mock_get):
        runner = CliRunner()
        with patch("wartz_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["history", "--task", "TASK-1"])
        assert result.exit_code == 0
        assert "TASK-1" in result.output
        assert "Done" in result.output
        mock_get.assert_called_once_with("1", limit=None)

    @patch("wartz_workflow.cli.ui.convo.get_messages", return_value=[])
    def test_history_empty(self, mock_get):
        runner = CliRunner()
        with patch("wartz_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["history", "--task", "TASK-1"])
        assert result.exit_code == 0
        assert "пуста" in result.output
        mock_get.assert_called_once_with("1", limit=None)

    @patch("wartz_workflow.cli.ui.convo.get_messages", return_value=[])
    def test_history_json_mode(self, mock_get):
        runner = CliRunner()
        with patch("wartz_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["--json", "history", "--task", "TASK-1", "--n", "10"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        assert parsed["task_key"] == "TASK-1"
        assert parsed["count"] == 0
        mock_get.assert_called_once_with("1", limit=10)

    def test_history_repo_is_rejected(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["history", "--task", "TASK-1", "--repo", "/repo"])
        assert result.exit_code != 0
        assert "No such option '--repo'" in result.output


class TestCliGuard:
    """Ensure only 2 main commands exist."""

    def test_step_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["step", "--help"])
        assert result.exit_code == 0
        assert "--task" in result.output
        assert "\n  --repo TEXT" not in result.output
        assert "\n  --skip" not in result.output

    def test_history_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["history", "--help"])
        assert result.exit_code == 0
        assert "--task" in result.output
        assert "Количество записей (по умолчанию: все)" in result.output
        assert "default 20" not in result.output
        assert "\n  --repo TEXT" not in result.output

    def test_ui_command_is_not_exposed(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["ui", "--help"])
        assert result.exit_code != 0
        assert "No such command 'ui'" in result.output
