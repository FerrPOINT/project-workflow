"""Tests for supervisor.py to boost coverage."""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.models import Phase


class TestSupervisor:
    def test_init(self):
        engine = SupervisorEngine("RUN-1")
        assert engine.task_key == "RUN-1"

    def test_init_does_not_bootstrap_empty_workflow(self, tmp_path):
        from project_workflow.infrastructure.db.uow import SAUnitOfWork

        test_db = tmp_path / "workflow.db"
        uow = SAUnitOfWork(f"sqlite:///{test_db}")
        ensure_schema(uow.session.get_bind())
        workflow_id = uow.workflows.create({"name": "Empty", "description": ""})
        uow.projects.create({"workflow_id": workflow_id, "code": "run", "name": "Run", "key_prefixes": ["RUN"]})
        uow.commit()
        with pytest.raises(ValueError, match="Каталог фаз воркфлоу пуст"):
            SupervisorEngine("RUN-1", uow=uow)
        assert uow.phases.list(workflow_id) == []

    def test_get_phase_prompt(self):
        ph = Phase(id=100, code="0", name="Test", description="D")
        engine = SupervisorEngine("RUN-1")
        engine.phase_map = {"0": ph}
        engine.all_phases = [ph]
        engine.current_phase_code = "0"
        engine.get_full_context = MagicMock(
            return_value={
                "workflow_name": "W",
                "current_contract": {},
                "cli_actor": {"description": "d", "entrypoint": "e"},
                "report_template": {
                    "summary": "s",
                    "completed": "c",
                    "evidence": "e",
                    "blockers": "b",
                    "next_step": "n",
                },
            }
        )
        prompt = engine.get_phase_prompt("0")
        assert "Test" in prompt

    def test_get_phase_prompt_parallel(self):
        """Parallel phases produce a single merged prompt with per-phase agents and partner."""
        ph_a = Phase(
            id=100,
            code="parallel-a",
            name="Parallel A",
            description="Desc A",
            execution_type="parallel",
            parallel_with_phase_code="parallel-b",
        )
        ph_b = Phase(
            id=101,
            code="parallel-b",
            name="Parallel B",
            description="Desc B",
            execution_type="parallel",
            parallel_with_phase_code="parallel-a",
        )

        engine = SupervisorEngine("RUN-1")
        engine.phase_map = {"parallel-a": ph_a, "parallel-b": ph_b}
        engine.all_phases = [ph_a, ph_b]
        engine.current_phase_code = "parallel-a"
        engine.get_full_context = MagicMock(
            return_value={
                "workflow_name": "W",
                "current_contract": {},
                "cli_actor": {"description": "d", "entrypoint": "e"},
                "report_template": {
                    "summary": "s",
                    "completed": "c",
                    "evidence": "e",
                    "blockers": "b",
                    "next_step": "n",
                },
            }
        )
        prompt = engine.get_phase_prompt("parallel-a")
        assert "ПАРАЛЛЕЛЬНАЯ ГРУППА ФАЗ" in prompt
        assert "Parallel A, Parallel B" in prompt
        assert "параллельно с" in prompt
        assert "Выполняются одновременно" in prompt
        assert "Отчёт по этой группе присылается ОДНИМ сообщением" in prompt

    def test_get_full_context(self):
        engine = SupervisorEngine("RUN-1")
        ctx = engine.get_full_context()
        assert "current_phase_code" in ctx
        assert "all_phases" in ctx
        assert "messages" not in ctx


class TestPromptAndModels:
    def test_build_phase_prompt_missing_phase(self):
        from project_workflow.supervisor.prompt import build_phase_prompt

        ctx = {"workflow_name": "W", "cli_actor": {"description": "d", "entrypoint": "e"}}
        result = build_phase_prompt("RUN-1", {}, [], "1", ctx, phase_code="missing")
        assert "не найдена" in result

    def test_build_phase_prompt_non_current_phase(self):
        from project_workflow.supervisor.models import Phase
        from project_workflow.supervisor.prompt import build_phase_prompt

        phase = Phase(code="2", name="Two", description="Desc", execution_type="sync")
        ctx = {
            "workflow_name": "W",
            "current_contract": None,
            "cli_actor": {"description": "d", "entrypoint": "e"},
            "report_template": {"summary": "s", "completed": "c", "evidence": "e", "blockers": "b", "next_step": "n"},
        }
        result = build_phase_prompt("RUN-1", {"2": phase}, [phase], "1", ctx, phase_code="2")
        assert "Two" in result
        assert "Desc" in result

    def test_build_phase_prompt_current_contract_dict(self):
        from project_workflow.supervisor.models import Phase
        from project_workflow.supervisor.prompt import build_phase_prompt

        phase = Phase(code="1", name="One", description="Desc")
        contract = {
            "description": "CDesc",
            "execution_type": "sync",
            "parallel_with_phase_code": None,
            "rollback_target_phase_code": None,
            "instructions": ["I1"],
            "required_checks": ["C1"],
            "required_evidence": ["E1"],
            "delegate_agent": None,
        }
        ctx = {
            "workflow_name": "W",
            "current_contract": contract,
            "cli_actor": {"description": "d", "entrypoint": "e"},
            "report_template": {"summary": "s", "completed": "c", "evidence": "e", "blockers": "b", "next_step": "n"},
        }
        result = build_phase_prompt("RUN-1", {"1": phase}, [phase], "1", ctx)
        assert "I1" in result
        assert "C1" in result
        assert "E1" in result
