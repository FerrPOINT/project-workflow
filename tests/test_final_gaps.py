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
from project_workflow.wizard import core as core_mod
from project_workflow.wizard.formatting import format_result


def _mock_state(uow=None):
    state = MagicMock()
    state.get_db.return_value = uow or MagicMock()
    return state


class TestSchemasFinalGaps:
    def test_coerce_int_invalid(self):
        assert schemas.OptionalIntMixin._coerce_optional_int("abc") is None

    def test_coerce_int_zero_or_negative(self):
        assert schemas.OptionalIntMixin._coerce_optional_int("0") is None
        assert schemas.OptionalIntMixin._coerce_optional_int("-5") is None

    def test_project_create_key_prefixes_invalid_type(self):
        p = schemas.ProjectCreate(code="PRJ", key_prefixes=123)
        assert p.key_prefixes == []

    def test_project_update_key_prefixes_str(self):
        p = schemas.ProjectUpdate(code="PRJ", key_prefixes="aa\nbb")
        assert p.key_prefixes == ["AA", "BB"]

    def test_project_update_key_prefixes_invalid(self):
        with pytest.raises(ValueError):
            schemas.ProjectUpdate(code="PRJ", key_prefixes=["A"])

    def test_phase_create_insert_after(self):
        p = schemas.PhaseCreate(name="X", insert_after=3)
        assert p.phase_order == 4


class TestDomainFinalGaps:
    def test_task_key_str(self):
        from project_workflow.domain import PhaseCode, TaskKey

        assert str(TaskKey("A-1", "A", 1)) == "A-1"
        assert str(PhaseCode("1")) == "1"


class TestUiSeedSkillsFinalGaps:
    def test_scan_hermes_skills_exception(self):
        from project_workflow.interfaces.ui import skills as skills_mod

        with patch("importlib.import_module", side_effect=ImportError("boom")):
            assert skills_mod._scan_hermes_skills() == []


class TestWizardModelContractFinalGaps:
    def test_phase_selected_agent(self):
        from project_workflow.wizard.models import Phase

        phase = Phase(code="1", name="T", selected_agent="ag", description="D")
        assert phase.delegate.agent == "ag"

    def test_parallel_contract_researcher_fallback(self):
        from project_workflow.wizard.contracts import PhaseContractBuilder
        from project_workflow.wizard.models import Phase, PhaseDelegate

        p1 = Phase(code="1", name="A", delegate=PhaseDelegate(agent="researcher", prompt_template="x", toolsets=[]))
        p2 = Phase(code="2", name="B")
        group = [p1, p2]
        contract = PhaseContractBuilder([]).build_parallel(group)
        assert contract.delegate_agent == "researcher"


class TestApplicationServiceFinalGaps:
    def test_agent_service_creation_failed(self):
        uow = MagicMock()
        uow.agents.create.return_value = 1
        uow.agents.get_by_id.return_value = None
        with pytest.raises(RuntimeError, match="Agent creation failed"):
            AgentService(uow).create_agent({"name": "x"})

    def test_phase_service_create_auto_order(self):
        uow = MagicMock()
        uow.phases.get_next_order.return_value = 7
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
        uow.tasks.list.return_value = []
        ProjectService(uow).delete_project(1)
        uow.projects.delete.assert_called_once_with(1)

    def test_task_service_creation_failed(self):
        uow = MagicMock()
        project = MagicMock()
        project.to_dict.return_value = {"id": 5, "code": "PROJ", "key_prefixes": ["PROJ"]}
        uow.projects.list.return_value = [project]
        uow.tasks.create.return_value = 1
        uow.tasks.get_by_id.return_value = None
        with pytest.raises(RuntimeError, match="Task creation failed"):
            TaskService(uow).create_task({"task_key": "PROJ-1"})

    def test_instruction_service_creation_failed(self):
        uow = MagicMock()
        uow.instructions.create.return_value = 1
        uow.instructions.get_by_id.return_value = None
        with pytest.raises(RuntimeError, match="Instruction creation failed"):
            InstructionService(uow).create_instruction(1, {"text": "x"})


class TestCliFinalGap:
    def test_cli_main(self):
        from project_workflow.interfaces.cli import main

        with patch("project_workflow.interfaces.cli.cli") as mock_cli:
            main()
        mock_cli.assert_called_once()


class TestSessionFinalGaps:
    def test_normalize_db_file(self):
        assert _normalize_url("data.db").startswith("sqlite:///")

    def test_ensure_schema_postgresql_engine(self):
        engine = MagicMock()
        engine.dialect.name = "postgresql"
        with patch("project_workflow.infrastructure.db.session.get_settings") as gs:
            gs.return_value.DB_SCHEMA = "public"
            with patch.object(engine, "begin") as mock_begin:
                conn = MagicMock()
                mock_begin.return_value.__enter__.return_value = conn
                ensure_schema(engine)
        conn.exec_driver_sql.assert_any_call("CREATE SCHEMA IF NOT EXISTS public")


class TestWorkflowServiceFinalGaps:
    def test_get_workflow_by_name_none(self):
        uow = MagicMock()
        uow.workflows.get_by_name.return_value = None
        assert WorkflowService(uow).get_workflow_by_name("x") is None

    def test_create_workflow_failure(self):
        uow = MagicMock()
        uow.workflows.create.return_value = 1
        uow.workflows.get_by_id.return_value = None
        with pytest.raises(RuntimeError, match="creation failed"):
            WorkflowService(uow).create_workflow({"name": "x"})


class TestWizardCoreFinalGaps:
    def test_resolve_current_phase_does_not_invent_fallback(self):
        engine = core_mod.WizardEngine("AAT-1", repo="/tmp")
        engine.task = {"id": 1, "current_phase": ""}
        engine.all_phases = []
        assert engine._resolve_current_phase() == ""

    def test_record_transition_no_task(self):
        engine = core_mod.WizardEngine("AAT-1", repo="/tmp")
        engine.task = None
        phase = MagicMock()
        engine._record_transition(phase, "pass", None, None)

    def test_evaluate_always_calls_llm(self):
        engine = core_mod.WizardEngine("AAT-1", repo="/tmp")
        engine.task = {"id": 1, "project_id": 1, "current_phase": "1"}
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
        engine.current_phase = "1"
        with patch.object(engine, "evaluate_llm", return_value={"verdict": "BLOCKED"}) as mock_llm:
            result = engine.evaluate(report="ok")
        mock_llm.assert_called_once()
        assert result["verdict"] == "BLOCKED"

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
            "status": "active",
            "current_phase": "1",
            "workflow_id": 1,
        }
        uow.get_phases.return_value = [
            {"id": 1, "code": "1", "name": "P1", "phase_order": 1, "execution_type": "parallel"},
            {"id": 2, "code": "2", "name": "P2", "phase_order": 2, "execution_type": "parallel"},
        ]

        def _get_phase(pid):
            return {"id": pid, "code": str(pid), "name": f"P{pid}", "phase_order": pid}

        uow.get_phase.side_effect = _get_phase
        uow.get_task_history.return_value = [
            {"phase_id": 1, "status": "done", "completed_at": "", "execution_type": "parallel"},
            {"phase_id": 2, "status": "done", "completed_at": "", "execution_type": "parallel"},
        ]
        uow.get_supervisor_runs.return_value = [{"verdict": "pass", "response": {}}]
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        result = _get_task_detail("A-1")
        assert result["phase_history_blocks"][0]["phases"][0]["parallel_group"] == "1"

    def test_get_task_detail_next_contract_none(self, monkeypatch):
        uow = MagicMock()
        uow.get_task_by_key.return_value = {
            "id": 1,
            "task_key": "A-1",
            "status": "active",
            "current_phase": "1",
            "workflow_id": 1,
        }
        uow.get_task_history.return_value = [{"phase_id": 1, "status": "done", "completed_at": ""}]
        uow.get_supervisor_runs.return_value = [{"verdict": "pass", "response": {"message": "ok"}}]
        uow.get_projects.return_value = []
        uow.get_phases.return_value = []
        uow.get_phase.return_value = None
        monkeypatch.setattr("project_workflow.interfaces.ui.services._get_app_state", lambda: _mock_state(uow))
        result = _get_task_detail("A-1")
        assert result["supervisor_runs"][0]["next_contract"] is None
