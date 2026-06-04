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


# ── Helpers ──────────────────────────────────────────────────────────

def _mock_state():
    return {
        "repo": "/repo",
        "task_key": "TASK-1",
        "current_phase": "0",
        "phases_completed": [],
    }


class TestStepCommand:
    """Test `wartz-workflow step --task TASK-1`"""

    @patch("wartz_workflow.state.find_repo", return_value="/repo")
    @patch("wartz_workflow.state.load_state", return_value=None)
    @patch("wartz_workflow.state.create_task_dir", return_value=(True, Path("/repo/sprint/TASK-1")))
    @patch("wartz_workflow.wizard.main")
    def test_step_auto_init_creates_task(self, mock_main, mock_create, mock_load, mock_find):
        runner = CliRunner()
        result = runner.invoke(cli, ["step", "--task", "TASK-1"])
        assert result.exit_code == 0
        mock_create.assert_called_once()

    @patch("wartz_workflow.state.find_repo", return_value="/repo")
    @patch("wartz_workflow.state.load_state", return_value=_mock_state())
    @patch("wartz_workflow.wizard.main")
    def test_step_shows_phase(self, mock_main, mock_load, mock_find):
        runner = CliRunner()
        result = runner.invoke(cli, ["step", "--task", "TASK-1"])
        assert result.exit_code == 0
        mock_main.assert_called_once()

    @patch("wartz_workflow.state.find_repo", return_value="/repo")
    @patch("wartz_workflow.state.load_state", return_value=_mock_state())
    @patch("wartz_workflow.wizard.evaluate_report", return_value={"verdict": "PASS", "next_phase": "1"})
    def test_step_report_pass(self, mock_eval, mock_load, mock_find):
        runner = CliRunner()
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
        result = runner.invoke(cli, ["step", "--task", "TASK-1", "--report", "Bad"])
        assert result.exit_code == 1
        parsed = json.loads(result.output)
        assert parsed["verdict"] == "FAIL"

    @patch("wartz_workflow.state.find_repo", return_value="/repo")
    @patch("wartz_workflow.state.load_state", return_value=_mock_state())
    @patch("wartz_workflow.wizard.WizardEngine")
    def test_step_skip_advances(self, mock_wiz_cls, mock_load, mock_find):
        engine = MagicMock()
        engine.current_phase = "0"
        engine.phase_map = {"0": SimpleNamespace(id="0", name="Setup", instructions=[])}
        engine._resolve_phase.return_value = engine.phase_map["0"]
        engine._get_next_phase.return_value = ("1", "Next")
        engine._record_transition = MagicMock()
        engine.get_phase_prompt.return_value = "Next phase prompt"
        mock_wiz_cls.return_value = engine

        runner = CliRunner()
        result = runner.invoke(cli, ["step", "--task", "TASK-1", "--skip"])
        assert result.exit_code == 0
        engine._record_transition.assert_called_once()


class TestHistoryCommand:
    """Test `wartz-workflow history --task TASK-1`"""

    @patch("wartz_workflow.cli.ui.convo.get_messages", return_value=[
        SimpleNamespace(role="user", phase_id="0", tags="transition", content="Done", created_at="2024-01-01"),
        SimpleNamespace(role="agent", phase_id="0", tags="", content="OK", created_at="2024-01-02"),
    ])
    def test_history_shows_records(self, mock_get):
        runner = CliRunner()
        result = runner.invoke(cli, ["history", "--task", "TASK-1"])
        assert result.exit_code == 0
        assert "TASK-1" in result.output
        assert "Done" in result.output
        mock_get.assert_called_once()

    @patch("wartz_workflow.cli.ui.convo.get_messages", return_value=[])
    def test_history_empty(self, mock_get):
        runner = CliRunner()
        result = runner.invoke(cli, ["history", "--task", "TASK-1"])
        assert result.exit_code == 0
        assert "пуста" in result.output

    @patch("wartz_workflow.cli.ui.convo.get_messages", return_value=[])
    def test_history_json_mode(self, mock_get):
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "history", "--task", "TASK-1", "--n", "10"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        assert parsed["task_key"] == "TASK-1"
        assert parsed["count"] == 0


class TestCliGuard:
    """Ensure only 2 main commands exist."""

    def test_step_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["step", "--help"])
        assert result.exit_code == 0
        assert "--task" in result.output

    def test_history_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["history", "--help"])
        assert result.exit_code == 0
        assert "--task" in result.output

    def test_ui_command_exists(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["ui", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output
