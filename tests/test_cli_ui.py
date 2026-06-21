"""Tests for CLI commands step + history in cli/ui.py.

Uses click.testing.CliRunner with heavy mocking to avoid FS/DB side effects.
"""

import json
from unittest.mock import patch

from click.testing import CliRunner

from project_workflow.cli.core import cli
from project_workflow.task_validator import TaskKeyValidator


# ── Helpers ──────────────────────────────────────────────────────────

def _validator() -> TaskKeyValidator:
    return TaskKeyValidator.from_projects([
        {
            "code": "TASK",
            "name": "TASK",
            "key_patterns": [r"^(?P<prefix>TASK)-(?P<number>[0-9]+)$"],
        }
    ])


class TestStepCommand:
    """Test `project-workflow step --task TASK-1`"""

    @patch("project_workflow.wizard.WizardEngine")
    def test_step_auto_init_creates_task(self, mock_engine_cls):
        """WizardEngine auto-creates task in DB if missing."""
        mock_engine = mock_engine_cls.return_value
        mock_engine.current_phase = "0"
        runner = CliRunner()
        with patch("project_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "TASK-1"])
        assert result.exit_code == 0
        # step_cmd creates engine, then wizard.main creates another via get_phase_instructions
        assert mock_engine_cls.call_count == 2
        first_call = mock_engine_cls.call_args_list[0]
        assert first_call[0] == ("TASK-1",)

    @patch("project_workflow.wizard.main")
    def test_step_shows_phase(self, mock_main):
        runner = CliRunner()
        with patch("project_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "TASK-1"])
        assert result.exit_code == 0
        mock_main.assert_called_once_with("TASK-1")

    @patch("project_workflow.wizard.WizardEngine")
    def test_step_report_pass(self, mock_engine_cls):
        mock_engine = mock_engine_cls.return_value
        mock_engine.evaluate.return_value = {
            "verdict": "PASS", "phase_name": "Plan", "next_phase": "1", "next_phase_name": "Build",
            "covered": ["a"], "missing": [], "blockers": [], "message": "Go next",
            "instructions": ["Инструкция 1"],
            "required_checks": ["a"],
            "required_evidence": ["e1"],
            "next_phase_contract": {
                "instructions": ["Инструкция 2"],
                "required_checks": ["c2"],
                "required_evidence": ["e2"],
            },
        }
        runner = CliRunner()
        with patch("project_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "TASK-1", "--report", "Done"])
        assert result.exit_code == 0
        mock_engine.evaluate.assert_called_once_with("Done")
        assert "Инструкции:" in result.output
        assert "Инструкция 2" in result.output
        assert "Чекапы:" in result.output
        assert "c2" in result.output
        assert "Доказательства:" in result.output
        assert "e2" in result.output

    @patch("project_workflow.wizard.WizardEngine")
    def test_step_report_fail_exits_one(self, mock_engine_cls):
        mock_engine = mock_engine_cls.return_value
        mock_engine.evaluate.return_value = {
            "verdict": "BLOCKED", "phase_name": "Plan", "next_phase": None, "next_phase_name": None,
            "covered": [], "missing": ["m1"], "blockers": ["b1"], "message": "Blocked",
            "required_checks": ["m1"], "required_evidence": [], "instructions": [], "description": "",
        }
        runner = CliRunner()
        with patch("project_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "TASK-1", "--report", "Bad"])
        assert result.exit_code == 1
        assert "Чекапы:" in result.output
        assert "m1" in result.output

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
    """Test `project-workflow history --task TASK-1`"""

    @patch("project_workflow.db.WorkflowDB.get_supervisor_runs", return_value=[
        {
            "phase_code": "0",
            "verdict": "pass",
            "next_phase_code": "1",
            "rollback_phase_code": None,
            "created_at": "2024-01-01",
        },
        {
            "phase_code": "1",
            "verdict": "pass",
            "next_phase_code": None,
            "rollback_phase_code": None,
            "created_at": "2024-01-02",
        },
    ])
    def test_history_shows_records(self, mock_get):
        runner = CliRunner()
        with patch("project_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["history", "--task", "TASK-1"])
        assert result.exit_code == 0
        assert "TASK-1" in result.output
        assert "Phase 0" in result.output
        mock_get.assert_called_once_with(task_key="TASK-1", limit=200)

    @patch("project_workflow.db.WorkflowDB.get_supervisor_runs", return_value=[])
    def test_history_empty(self, mock_get):
        runner = CliRunner()
        with patch("project_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["history", "--task", "TASK-1"])
        assert result.exit_code == 0
        assert "пуста" in result.output
        mock_get.assert_called_once_with(task_key="TASK-1", limit=200)

    @patch("project_workflow.db.WorkflowDB.get_supervisor_runs", return_value=[])
    def test_history_json_mode(self, mock_get):
        runner = CliRunner()
        with patch("project_workflow.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["--json", "history", "--task", "TASK-1", "--n", "10"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        assert parsed["task_key"] == "TASK-1"
        assert parsed["count"] == 0
        mock_get.assert_called_once_with(task_key="TASK-1", limit=10)

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
        assert "Отчёт исполнителя CLI" in result.output
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
