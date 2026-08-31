"""Tests for CLI commands step + history in cli/ui.py.

Uses click.testing.CliRunner with heavy mocking to avoid FS/DB side effects.
"""

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

pytestmark = [pytest.mark.cli]

from project_workflow.domain.validation import TaskKeyValidator
from project_workflow.interfaces.cli.core import NAMESPACE_ENV_VAR, cli

# ── Helpers ──────────────────────────────────────────────────────────


def _validator() -> TaskKeyValidator:
    return TaskKeyValidator.from_projects(
        [
            {
                "code": "RUN",
                "name": "RUN",
                "key_prefixes": ["RUN"],
            }
        ]
    )


class TestStepCommand:
    """Test `project-workflow step --task RUN-1`"""

    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_auto_init_creates_task(self, mock_engine_cls):
        """SupervisorEngine auto-creates task in DB if missing."""
        mock_engine = mock_engine_cls.return_value
        mock_engine.current_phase_code = "0"
        mock_engine.format_current_phase_instructions.return_value = "do stuff"
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "RUN-1"])
        assert result.exit_code == 0
        # step_cmd creates a single engine and asks for the phase instructions.
        assert mock_engine_cls.call_count == 1
        first_call = mock_engine_cls.call_args_list[0]
        assert first_call[0] == ("RUN-1",)
        mock_engine.format_current_phase_instructions.assert_called_once()

    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_shows_phase(self, mock_engine_cls):
        mock_engine = mock_engine_cls.return_value
        mock_engine.current_phase_code = "0.00"
        mock_engine.format_current_phase_instructions.return_value = "phase instructions"
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "RUN-1"])
        assert result.exit_code == 0
        assert "phase instructions" in result.output
        mock_engine.format_current_phase_instructions.assert_called_once_with()

    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_report_pass(self, mock_engine_cls):
        mock_engine = mock_engine_cls.return_value
        mock_engine.evaluate.return_value = {
            "verdict": "PASS",
            "phase_name": "Plan",
            "next_phase_code": "1",
            "next_phase_name": "Build",
            "covered": ["a"],
            "missing": [],
            "blockers": [],
            "message": "Go next",
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
            result = runner.invoke(cli, ["step", "--task", "RUN-1", "--report", "Done"])
        assert result.exit_code == 0
        mock_engine.evaluate.assert_called_once_with("Done")
        assert "Инструкции:" in result.output
        assert "Инструкция 2" in result.output
        assert "Чекапы:" in result.output
        assert "c2" in result.output
        assert "Доказательства:" in result.output
        assert "e2" in result.output

    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_report_fail_exits_one(self, mock_engine_cls):
        mock_engine = mock_engine_cls.return_value
        mock_engine.evaluate.return_value = {
            "verdict": "BLOCKED",
            "phase_name": "Plan",
            "next_phase_code": None,
            "next_phase_name": None,
            "covered": [],
            "missing": ["m1"],
            "blockers": ["b1"],
            "message": "Blocked",
            "required_checks": ["m1"],
            "required_evidence": [],
            "instructions": [],
            "description": "",
        }
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "RUN-1", "--report", "Bad"])
        assert result.exit_code == 1
        assert "Чекапы:" in result.output
        assert "m1" in result.output

    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_report_json_mode(self, mock_engine_cls):
        mock_engine = mock_engine_cls.return_value
        mock_engine.evaluate.return_value = {
            "verdict": "PASS",
            "phase_name": "Plan",
            "next_phase_code": None,
            "covered": [],
            "missing": [],
            "blockers": [],
            "message": "ok",
        }
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["--json", "step", "--task", "RUN-1", "--report", "Done"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["verdict"] == "PASS"

    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_report_json_blocked_exits_one(self, mock_engine_cls):
        mock_engine_cls.return_value.evaluate.return_value = {
            "verdict": "BLOCKED",
            "blockers": ["provider unavailable"],
            "retryable": True,
        }
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["--json", "step", "--task", "RUN-1", "--report", "Done"])
        assert result.exit_code == 1
        assert json.loads(result.output)["verdict"] == "BLOCKED"

    @patch("project_workflow.interfaces.cli.ui.SAUnitOfWork")
    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_json_prompt_closes_unit_of_work(self, mock_engine_cls, mock_uow_cls):
        mock_engine = mock_engine_cls.return_value
        mock_engine.current_phase_code = "1.INTAKE"
        mock_engine.task = {"status": "active"}
        mock_engine._get_current_phase_obj.return_value = object()
        mock_engine.get_phase_prompt.return_value = "prompt"
        mock_engine.get_phase_contract.return_value = {"phase_code": "1.INTAKE"}
        runner = CliRunner()

        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["--json", "step", "--task", "RUN-1"])

        assert result.exit_code == 0
        assert json.loads(result.output)["prompt"] == "prompt"
        mock_uow_cls.return_value.close.assert_called_once_with()

    @patch("project_workflow.interfaces.cli.ui.SAUnitOfWork")
    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_closes_unit_of_work_when_engine_init_fails(self, mock_engine_cls, mock_uow_cls):
        mock_engine_cls.side_effect = ValueError("Сломанный snapshot задачи")
        runner = CliRunner()

        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "RUN-1"])

        assert result.exit_code == 1
        assert "Сломанный snapshot задачи" in result.output
        mock_uow_cls.return_value.close.assert_called_once_with()

    @pytest.mark.parametrize("report", ["", "   "])
    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_rejects_explicit_blank_report_without_creating_task(self, mock_engine_cls, report):
        runner = CliRunner()

        result = runner.invoke(cli, ["--json", "step", "--task", "RUN-404", "--report", report])

        assert result.exit_code == 1
        assert json.loads(result.output)["message"] == "Отчёт не может быть пустым"
        mock_engine_cls.assert_not_called()

    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_prompt_json_mode(self, mock_engine_cls):
        mock_engine = mock_engine_cls.return_value
        mock_engine.current_phase_code = "0.00"
        mock_engine.get_phase_prompt.return_value = "next steps"
        mock_engine.get_phase_contract.return_value = {
            "phase_code": "0.00",
            "phase_name": "Git Identity",
            "skills": ["project-workflow-executor"],
            "hermes_profile": "sdlc-ops",
            "group_phases": None,
            "group_details": [],
        }
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["--json", "step", "--task", "RUN-1"])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        assert parsed["task_key"] == "RUN-1"
        assert parsed["phase_code"] == "0.00"
        assert parsed["prompt"] == "next steps"
        assert parsed["phase_contract"]["hermes_profile"] == "sdlc-ops"
        assert parsed["phase_contract"]["skills"] == ["project-workflow-executor"]

    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_done_json_mode_returns_compact_snapshot(self, mock_engine_cls):
        mock_engine = mock_engine_cls.return_value
        mock_engine.current_phase_code = "19.DELIVERY"
        mock_engine.task = {"status": "done"}
        mock_engine._get_current_phase_obj.return_value = object()
        mock_engine.get_phase_prompt.return_value = "heavy prompt must stay out of done JSON"
        mock_engine.get_phase_contract.return_value = {"phase_code": "19.DELIVERY"}
        mock_engine.format_current_phase_instructions.return_value = "Финальный snapshot"
        runner = CliRunner()

        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["--json", "step", "--task", "RUN-1"])

        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["status"] == "done"
        assert parsed["next_phase_code"] is None
        assert parsed["instructions"] == "Финальный snapshot"
        assert "prompt" not in parsed

    @patch("project_workflow.interfaces.cli.ui.SAUnitOfWork")
    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_passes_context_selector_to_engine(self, mock_engine_cls, mock_uow_cls):
        mock_engine = mock_engine_cls.return_value
        mock_engine.current_phase_code = "1.INTAKE"
        mock_engine.format_current_phase_instructions.return_value = "phase"
        mock_uow_cls.return_value.projects.list.return_value = [
            {"id": 7, "code": "QA", "name": "tester"}
        ]
        runner = CliRunner()

        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "RUN-1", "--context", "tester"])

        assert result.exit_code == 0
        assert mock_engine_cls.call_args.kwargs["project_id"] == 7

    @pytest.mark.parametrize(
        ("verdict", "expected"),
        [
            ("PARTIAL", "Нужно доделать проверку"),
            ("DELEGATE", "Передай выполнение агенту Review"),
        ],
    )
    @patch("project_workflow.supervisor.SupervisorEngine")
    def test_step_report_non_pass_non_blocked_rendering(self, mock_engine_cls, verdict, expected):
        mock_engine_cls.return_value.evaluate.return_value = {
            "verdict": verdict,
            "phase_name": "Review",
            "covered": [],
            "missing": ["Нужно доделать проверку"],
            "blockers": [],
            "message": "Передай выполнение агенту Review",
            "instructions": ["Проверь отчёт"],
            "required_checks": ["Нужно доделать проверку"],
            "required_evidence": [],
        }
        runner = CliRunner()

        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["step", "--task", "RUN-1", "--report", "Готово частично"])

        assert result.exit_code == 0
        assert expected in result.output

    def test_step_skip_is_rejected(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["step", "--task", "RUN-1", "--skip"])
        assert result.exit_code != 0
        assert "Нет такого параметра: --skip." in result.output
        assert "No such option" not in result.output

    def test_step_repo_is_rejected(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["step", "--task", "RUN-1", "--repo", "/repo"])
        assert result.exit_code != 0
        assert "Нет такого параметра: --repo." in result.output
        assert "No such option" not in result.output


class TestHistoryCommand:
    """Test `project-workflow history --task RUN-1`"""

    @patch("project_workflow.interfaces.cli.ui.SAUnitOfWork")
    def test_history_shows_records(self, mock_uow_cls):
        from project_workflow.domain import TaskStepHistoryEntry

        run1 = TaskStepHistoryEntry(
            id=1,
            task_id=1,
            phase_id=0,
            verdict="pass",
            next_phase_id=1,
            rollback_phase_id=None,
            worker_report="done",
            supervisor_response={"next_phase_code": "1", "message": "Принято"},
            created_at="2024-01-01",
        )
        run2 = TaskStepHistoryEntry(
            id=2,
            task_id=1,
            phase_id=1,
            verdict="pass",
            next_phase_id=None,
            rollback_phase_id=None,
            worker_report="done again",
            supervisor_response={"message": "Принято"},
            created_at="2024-01-02",
        )
        uow = mock_uow_cls.return_value.__enter__.return_value
        uow.tasks.get_by_key.return_value = type("Task", (), {"id": 1})()
        uow.step_history.list.return_value = [run1, run2]

        def _fake_phase(pid):
            return type("Phase", (), {"code": str(pid), "name": f"Phase {pid}"})()

        uow.phases.get_by_id.side_effect = _fake_phase
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["history", "--task", "RUN-1"])
        assert result.exit_code == 0, result.output
        assert "RUN-1" in result.output
        assert "Фаза 0" in result.output

    @patch("project_workflow.interfaces.cli.ui.SAUnitOfWork")
    def test_history_empty(self, mock_uow_cls):
        uow = mock_uow_cls.return_value.__enter__.return_value
        uow.step_history.list.return_value = []
        uow.tasks.get_by_key.return_value = None
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["history", "--task", "RUN-1"])
        assert result.exit_code == 0, result.output
        assert "пуста" in result.output
        uow.step_history.list.assert_called_once_with(
            task_id=None,
            task_key="RUN-1",
            project_id=None,
            limit=None,
        )

    @patch("project_workflow.interfaces.cli.ui.SAUnitOfWork")
    def test_history_json_mode(self, mock_uow_cls):
        uow = mock_uow_cls.return_value.__enter__.return_value
        uow.step_history.list.return_value = []
        uow.tasks.get_by_key.return_value = None
        runner = CliRunner()
        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["--json", "history", "--task", "RUN-1", "--n", "10"])
        assert result.exit_code == 0, result.output
        parsed = json.loads(result.output)
        assert parsed["ok"] is True
        assert parsed["task_key"] == "RUN-1"
        assert parsed["count"] == 0
        uow.step_history.list.assert_called_once_with(
            task_id=None,
            task_key="RUN-1",
            project_id=None,
            limit=10,
        )

    @patch("project_workflow.interfaces.cli.ui.SAUnitOfWork")
    def test_history_passes_context_selector_to_lookup(self, mock_uow_cls):
        uow = mock_uow_cls.return_value.__enter__.return_value
        uow.projects.list.return_value = [{"id": 9, "code": "QA", "name": "tester"}]
        uow.step_history.list.return_value = []
        uow.tasks.get_by_key.return_value = None
        runner = CliRunner()

        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["--json", "history", "--task", "RUN-1", "--context", "tester"])

        assert result.exit_code == 0
        uow.tasks.get_by_key.assert_called_once_with("RUN-1", project_id=9)
        uow.step_history.list.assert_called_once_with(
            task_id=None,
            task_key="RUN-1",
            project_id=9,
            limit=None,
        )

    @patch("project_workflow.interfaces.cli.ui.SAUnitOfWork")
    def test_history_non_json_fails_closed_when_phase_is_missing(self, mock_uow_cls):
        from project_workflow.domain import TaskStepHistoryEntry

        run = TaskStepHistoryEntry(
            id=1,
            task_id=1,
            phase_id=999,
            verdict="pass",
            worker_report="done",
            supervisor_response={"message": "ok"},
            created_at="2024-01-01",
        )
        uow = mock_uow_cls.return_value.__enter__.return_value
        uow.tasks.get_by_key.return_value = type("Task", (), {"id": 1})()
        uow.step_history.list.return_value = [run]
        uow.phases.get_by_id.return_value = None
        runner = CliRunner()

        with patch("project_workflow.interfaces.cli.core._get_task_key_validator", return_value=_validator()):
            result = runner.invoke(cli, ["history", "--task", "RUN-1"])

        assert result.exit_code == 1
        assert "История step ссылается на неизвестную фазу" in result.output

    def test_history_rejects_non_positive_limit(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["history", "--task", "TASK-1", "--n", "0"])
        assert result.exit_code == 2
        assert "Некорректное значение параметра '--n'." in result.output

    def test_history_uses_namespace_env_selector_for_duplicate_task_keys(self):
        from project_workflow.application.project import ProjectService
        from project_workflow.application.task import TaskService
        from project_workflow.application.workflow import WorkflowService
        from project_workflow.infrastructure.db.uow import SAUnitOfWork

        with SAUnitOfWork() as uow:
            default_namespace = uow.projects.get_by_code("RUN")
            assert default_namespace is not None and default_namespace.id is not None
            qa_workflow = WorkflowService(uow).create_workflow({"name": "QA flow"})
            qa_namespace = ProjectService(uow).create_project(
                {
                    "code": "QAENV",
                    "name": "QA Environment",
                    "workflow_id": qa_workflow["id"],
                    "cli_command": "workflow-qa-env",
                    "key_prefixes": ["RUN"],
                }
            )
            TaskService(uow).create_task(
                {"project_id": default_namespace.id, "task_key": "RUN-4242", "title": "Dev duplicate"}
            )
            TaskService(uow).create_task(
                {"project_id": qa_namespace["id"], "task_key": "RUN-4242", "title": "QA duplicate"}
            )
            default_namespace_id = default_namespace.id
            qa_namespace_id = qa_namespace["id"]

        runner = CliRunner()
        ambiguous = runner.invoke(cli, ["--json", "history", "--task", "RUN-4242"])
        assert ambiguous.exit_code == 1
        assert "несколько CLI-команд" in json.loads(ambiguous.output)["message"]

        for namespace_id in (default_namespace_id, qa_namespace_id):
            result = runner.invoke(
                cli,
                ["--json", "history", "--task", "RUN-4242"],
                env={NAMESPACE_ENV_VAR: str(namespace_id)},
            )
            assert result.exit_code == 0, result.output
            assert json.loads(result.output)["task_key"] == "RUN-4242"

    def test_history_rejects_unknown_namespace_env_selector(self):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["--json", "history", "--task", "RUN-1"],
            env={NAMESPACE_ENV_VAR: "999999"},
        )
        assert result.exit_code == 1
        assert "Запись 999999 не найдена" in json.loads(result.output)["message"]
        assert "not in the range" not in result.output


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
        assert "Нет такой команды: 'ui'." in result.output
        assert "No such command" not in result.output
