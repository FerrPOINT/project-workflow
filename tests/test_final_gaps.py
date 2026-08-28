"""Final coverage gap tests to push coverage above 95%."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import click
import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.application.agent import AgentService
from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.project import ProjectService
from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
from project_workflow.infrastructure.db.session import _normalize_url, ensure_schema
from project_workflow.interfaces.ui import schemas
from project_workflow.interfaces.ui.services import (
    _get_task_detail,
    _load_cli_reference,
)
from project_workflow.supervisor import core as core_mod
from project_workflow.supervisor import format_result


def _mock_state(uow=None):
    state = MagicMock()
    state.get_db.return_value = uow or MagicMock()
    return state


class TestSchemasFinalGaps:
    @pytest.mark.parametrize("value", ["abc", "0", "-5", 0, -5, True])
    def test_phase_create_rejects_invalid_optional_integer(self, value):
        with pytest.raises(ValueError):
            schemas.PhaseCreate(workflow_id=1, phase_order=1, agent_id=value)

    def test_project_create_key_prefixes_invalid_type(self):
        with pytest.raises(ValueError, match="массивом строк"):
            schemas.ProjectCreate(code="PRJ", key_prefixes=123)

    def test_project_update_rejects_string_key_prefixes(self):
        with pytest.raises(ValueError, match="массивом строк"):
            schemas.ProjectUpdate(code="PRJ", key_prefixes="aa\nbb")

    def test_project_update_key_prefixes_invalid(self):
        with pytest.raises(ValueError):
            schemas.ProjectUpdate(code="PRJ", key_prefixes=["A"])

    def test_phase_create_insert_after(self):
        p = schemas.PhaseCreate(workflow_id=1, name="X", insert_after=3)
        assert p.phase_order == 4


class TestDomainFinalGaps:
    def test_task_key_str(self):
        from project_workflow.domain import PhaseCode, TaskKey

        assert str(TaskKey("A-1", "A", 1)) == "A-1"
        assert str(PhaseCode("1")) == "1"


class TestSupervisorModelContractFinalGaps:
    def test_parallel_contract_uses_group_delegate(self):
        from project_workflow.supervisor.contracts import PhaseContractBuilder
        from project_workflow.supervisor.models import Phase, PhaseDelegate

        p1 = Phase(code="1", name="A", delegate=PhaseDelegate(agent="researcher"))
        p2 = Phase(code="2", name="B")
        group = [p1, p2]
        contract = PhaseContractBuilder([]).build_parallel(group)
        assert contract.delegate_agent == "researcher"


class TestApplicationServiceFinalGaps:
    def test_agent_service_creation_failed(self):
        uow = MagicMock()
        uow.agents.get_by_name.return_value = None
        uow.agents.get_by_hermes_profile.return_value = None
        uow.agents.create.return_value = 1
        uow.agents.get_by_id.return_value = None
        with pytest.raises(RuntimeError, match="Не удалось создать агента"):
            AgentService(uow).create_agent({"name": "x"})

    def test_phase_service_create_auto_order(self):
        uow = MagicMock()
        uow.phases.get_next_order.return_value = 7
        uow.phases.list.return_value = [
            MagicMock(
                id=order,
                code=f"existing-{order}",
                phase_order=order,
                execution_type="sync",
                parallel_with_phase_id=None,
                rollback_target_phase_id=None,
            )
            for order in range(1, 7)
        ]
        phase = MagicMock()
        phase.to_dict.return_value = {"id": 1}
        uow.phases.create.return_value = 1
        uow.phases.get_by_id.return_value = phase
        result = PhaseServiceApp(uow).create_phase({"workflow_id": 1, "name": "X"})
        assert result["id"] == 1
        assert uow.phases.create.call_args[0][0]["phase_order"] == 7

    def test_phase_service_get_phase_none(self):
        uow = MagicMock()
        uow.phases.get_by_id.return_value = None
        assert PhaseServiceApp(uow).get_phase(1) is None

    def test_project_service_delete(self):
        uow = MagicMock()
        project = MagicMock(workflow_id=1)
        uow.projects.get_by_id.return_value = project
        uow.projects.lock.return_value = project
        uow.tasks.list_by_project.return_value = []
        ProjectService(uow).delete_project(1)
        uow.projects.delete.assert_called_once_with(1)

    def test_task_service_creation_failed(self):
        uow = MagicMock()
        project = MagicMock()
        project.code = "P"
        project.key_prefixes = ["P"]
        project.workflow_id = 1
        project.to_dict.return_value = {
            "code": "P",
            "key_prefixes": ["P"],
        }
        uow.projects.get_by_id.return_value = project
        uow.projects.lock.return_value = project
        uow.workflows.lock.return_value = object()
        uow.phases.list.return_value = [MagicMock(id=1, code="1.INTAKE")]
        uow.phases.get_by_code.return_value = object()
        uow.tasks.get_by_key.return_value = None
        uow.tasks.create.return_value = 1
        uow.tasks.get_by_id.return_value = None
        with pytest.raises(RuntimeError, match="Не удалось создать задачу"):
            TaskService(uow).create_task({"task_key": "P-1", "project_id": 5})

    def test_instruction_service_creation_failed(self):
        uow = MagicMock()
        phase = MagicMock(id=1, workflow_id=7)
        uow.phases.get_by_id.return_value = phase
        uow.phases.list.return_value = [phase]
        uow.phase_instructions.create.return_value = 1
        uow.phase_instructions.get_by_id.return_value = None
        with pytest.raises(RuntimeError, match="Не удалось создать инструкцию"):
            InstructionService(uow).create_instruction(1, {"text": "x"})


class TestCliFinalGap:
    def test_cli_main(self):
        from project_workflow.interfaces.cli import main

        with patch("project_workflow.interfaces.cli.cli") as mock_cli:
            main()
        mock_cli.assert_called_once()


class TestSessionFinalGaps:
    def test_normalize_explicit_url_only(self):
        assert _normalize_url("sqlite:///data.db") == "sqlite:///data.db"
        assert _normalize_url("data.db") == "data.db"

    def test_ensure_schema_postgresql_engine(self):
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        with pytest.raises(RuntimeError, match="изолированных тестах SQLite"):
            ensure_schema(engine)


class TestWorkflowServiceFinalGaps:
    def test_create_workflow_failure(self):
        uow = MagicMock()
        uow.workflows.create.return_value = 1
        uow.workflows.get_by_id.return_value = None
        with pytest.raises(RuntimeError, match="Не удалось создать воркфлоу"):
            WorkflowService(uow).create_workflow({"name": "x"})


class TestSupervisorCoreFinalGaps:
    def test_resolve_current_phase_rejects_blank_code(self):
        engine = core_mod.SupervisorEngine("RUN-1")
        engine.task = {"id": 1, "current_phase_id": 1, "current_phase_code": ""}
        engine.all_phases = []
        with pytest.raises(ValueError, match="current_phase_code"):
            engine._resolve_current_phase_code()

    def test_evaluate_does_not_fall_back_when_llm_raises(self):
        engine = core_mod.SupervisorEngine("RUN-1")
        engine.task = {
            "id": 1,
            "project_id": 1,
            "current_phase_id": 1,
            "current_phase_code": "1",
        }
        uow = MagicMock()
        uow.projects.get.return_value = {"id": 1}
        uow.tasks.get.return_value = engine.task
        engine._uow = uow
        phase = MagicMock()
        phase.code = "1"
        phase.name = "T"
        phase.id = 1
        phase.execution_type = "sync"
        phase.instructions = []
        phase.checks = []
        phase.evidence = []
        engine.all_phases = [phase]
        engine.current_phase_code = "1"
        with patch.object(engine, "evaluate_llm", side_effect=Exception("boom")) as mock_llm:
            with pytest.raises(Exception, match="boom"):
                engine.evaluate(report="ok")
        mock_llm.assert_called_once()

    def test_format_result_pass_parallel(self):
        text = format_result(
            {
                "verdict": "PASS",
                "phase_code": "1",
                "next_phase_contract": {
                    "phase_code": "2",
                    "phase_name": "N",
                    "execution_type": "parallel",
                    "instructions": ["do"],
                    "required_checks": ["check"],
                    "required_evidence": ["evidence"],
                },
            }
        )
        assert "Инструкции:" in text
        assert "  · do" in text
        assert "Параллельная фаза" not in text

    def test_format_result_pass_sync_after_parallel(self):
        text = format_result(
            {
                "verdict": "PASS",
                "phase_code": "parallel.end",
                "phase_name": "Parallel group end",
                "next_phase_contract": {
                    "phase_code": "2",
                    "execution_type": "sync",
                    "instructions": ["do"],
                },
            }
        )
        assert "Инструкции:" in text
        assert "  · do" in text
        assert "параллельного блока" not in text


class TestUiServicesFinalGaps:
    def test_load_cli_reference_argument(self, monkeypatch):
        cmd = click.Command("cmd", params=[click.Argument(["arg"])])
        with patch("project_workflow.interfaces.ui.cli_reference.project_workflow.commands", {"cmd": cmd}, create=True):
            result = _load_cli_reference()
        assert result[0]["options"] == []

    def test_load_cli_reference_default(self):
        opt = click.Option(["--flag"], help="help", default="x")
        cmd = click.Command("cmd", params=[opt])
        with patch("project_workflow.interfaces.ui.cli_reference.project_workflow.commands", {"cmd": cmd}, create=True):
            result = _load_cli_reference()
        assert result[0]["options"][0]["default"] == "x"

    def test_get_task_detail_parallel_history(self, monkeypatch):
        uow = MagicMock()
        uow.get_task_by_key.return_value = {
            "id": 1,
            "task_key": "A-1",
            "status": "done",
            "project_id": 10,
            "current_phase_id": 2,
            "workflow_id": 1,
        }
        uow.projects.get_by_id.return_value.to_dict.return_value = {
            "id": 10,
            "code": "A",
            "name": "Project A",
        }
        uow.get_phases.return_value = [
            {
                "id": 1,
                "code": "1",
                "name": "P1",
                "phase_order": 1,
                "execution_type": "parallel",
                "parallel_with_phase_id": 2,
            },
            {
                "id": 2,
                "code": "2",
                "name": "P2",
                "phase_order": 2,
                "execution_type": "parallel",
                "parallel_with_phase_id": 1,
            },
        ]

        uow.list_phase_events.return_value = [
            {"phase_id": 1, "event_type": "completed", "occurred_at": "2026-01-01"},
            {"phase_id": 2, "event_type": "completed", "occurred_at": "2026-01-01"},
        ]
        uow.list_step_history.return_value = []
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        result = _get_task_detail("A-1")
        assert [phase["phase_code"] for phase in result["phase_history_blocks"][0]["phases"]] == ["1", "2"]

    def test_get_task_detail_next_contract_none(self, monkeypatch):
        uow = MagicMock()
        uow.get_task_by_key.return_value = {
            "id": 1,
            "task_key": "A-1",
            "status": "active",
            "project_id": 10,
            "current_phase_id": 1,
            "workflow_id": 1,
        }
        uow.projects.get_by_id.return_value.to_dict.return_value = {
            "id": 10,
            "code": "A",
            "name": "Project A",
        }
        uow.list_phase_events.return_value = [{"phase_id": 1, "event_type": "entered", "occurred_at": "2026-01-01"}]
        uow.list_step_history.return_value = [
            {
                "verdict": "pass",
                "evaluation_snapshot": {"phase_code": "1", "phase_name": "P1"},
                "supervisor_response": {"message": "ok"},
                "blocker_messages": [],
            }
        ]
        uow.get_phases.return_value = [{"id": 1, "code": "1", "name": "P1", "phase_order": 1}]
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        result = _get_task_detail("A-1")
        assert result["step_history"][0]["next_contract"] is None
