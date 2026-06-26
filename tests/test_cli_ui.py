"""Tests for CLI commands step + history in cli/ui.py.

Uses click.testing.CliRunner with heavy mocking to avoid FS/DB side effects.
"""

import json
import os
from unittest.mock import patch

from click.testing import CliRunner

from project_workflow.domain.validation import TaskKeyValidator
from project_workflow.interfaces.cli.core import cli


# ── Helpers ──────────────────────────────────────────────────────────

def _validator() -> TaskKeyValidator:
    return TaskKeyValidator.from_projects([
        {
            "code": "TASK",
            "name": "TASK",
            "key_prefixes": ["TASK"],
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
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "TASK-1"])
        assert result.exit_code == 0
        # step_cmd creates engine, then wizard.main creates another via get_phase_instructions
        assert mock_engine_cls.call_count == 2
        first_call = mock_engine_cls.call_args_list[0]
        assert first_call[0] == ("TASK-1",)

    @patch("project_workflow.wizard.main")
    def test_step_shows_phase(self, mock_main):
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
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
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
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
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "TASK-1", "--report", "Bad"])
        assert result.exit_code == 1
        assert "Чекапы:" in result.output
        assert "m1" in result.output

    @patch("project_workflow.wizard.WizardEngine")
    def test_step_report_smart_mode_prefix(self, mock_engine_cls):
        os.environ["SMART_EVALUATE"] = "true"
        try:
            mock_engine = mock_engine_cls.return_value
            mock_engine.evaluate.return_value = {
                "verdict": "PASS", "phase_name": "Plan", "next_phase": "1", "next_phase_name": "Build",
                "covered": [], "missing": [], "blockers": [], "message": "ok",
                "required_checks": [], "required_evidence": [], "instructions": [],
            }
            runner = CliRunner()
            with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
                result = runner.invoke(cli, ["step", "--task", "TASK-1", "--report", "Done"])
            assert result.exit_code == 0
            assert "[🧠 SMART MODE]" in result.output
        finally:
            os.environ.pop("SMART_EVALUATE", None)

    @patch("project_workflow.wizard.WizardEngine")
    def test_step_report_json_mode(self, mock_engine_cls):
        mock_engine = mock_engine_cls.return_value
        mock_engine.evaluate.return_value = {
            "verdict": "PASS", "phase_name": "Plan", "next_phase": None,
            "covered": [], "missing": [], "blockers": [], "message": "ok",
        }
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["--json", "step", "--task", "TASK-1", "--report", "Done"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["verdict"] == "PASS"

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

    @patch("project_workflow.interfaces.cli.ui.SAUnitOfWork")
    def test_history_shows_records(self, mock_uow_cls):
        from project_workflow.domain import SupervisorRun

        run1 = SupervisorRun(
            id=1,
            task_id=1,
            phase_id=0,
            verdict="pass",
            next_phase_id=1,
            rollback_phase_id=None,
            response={"next_phase": "1"},
            created_at="2024-01-01",
        )
        run2 = SupervisorRun(
            id=2,
            task_id=1,
            phase_id=1,
            verdict="pass",
            next_phase_id=None,
            rollback_phase_id=None,
            response={},
            created_at="2024-01-02",
        )
        uow = mock_uow_cls.return_value.__enter__.return_value
        uow.supervisor_runs.list.return_value = [run1, run2]
        def _fake_phase(pid):
            return type('Phase', (), {'code': str(pid), 'name': f'Phase {pid}'})()
        uow.phases.get_by_id.side_effect = _fake_phase
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["history", "--task", "TASK-1"])
        assert result.exit_code == 0, result.output
        assert "TASK-1" in result.output
        assert "Phase 0" in result.output

    @patch("project_workflow.interfaces.cli.ui.SAUnitOfWork")
    def test_history_empty(self, mock_uow_cls):
        uow = mock_uow_cls.return_value.__enter__.return_value
        uow.supervisor_runs.list.return_value = []
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["history", "--task", "TASK-1"])
        assert result.exit_code == 0, result.output
        assert "пуста" in result.output

    @patch("project_workflow.interfaces.cli.ui.SAUnitOfWork")
    def test_history_json_mode(self, mock_uow_cls):
        uow = mock_uow_cls.return_value.__enter__.return_value
        uow.supervisor_runs.list.return_value = []
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["--json", "history", "--task", "TASK-1", "--n", "10"])
        assert result.exit_code == 0, result.output
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
