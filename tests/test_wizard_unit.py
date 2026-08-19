"""Tests for wizard.py to boost coverage."""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.wizard import WizardEngine


class TestWizard:
    def test_init(self):
        engine = WizardEngine("TASK-1")
        assert engine.task_key == "TASK-1"

    def test_init_does_not_bootstrap_empty_workflow(self, tmp_path):
        from project_workflow.infrastructure.db.uow import SAUnitOfWork

        test_db = tmp_path / "workflow.db"
        uow = SAUnitOfWork(f"sqlite:///{test_db}")
        uow.create_all()
        workflow_id = uow.workflows.create({"name": "Empty", "description": ""})
        uow.projects.create({"workflow_id": workflow_id, "code": "task", "name": "Task", "key_prefixes": ["TASK"]})
        uow.commit()
        with pytest.raises(ValueError, match="catalog is empty"):
            WizardEngine("TASK-1", uow=uow)
        assert uow.phases.list(workflow_id) == []

    def test_get_phase_prompt(self):
        ph = MagicMock()
        ph.code = "0"
        ph.name = "Test"
        ph.description = "D"
        ph.is_blocker = False
        ph.is_delegated = False
        ph.instructions = []
        engine = WizardEngine("TASK-1")
        engine.phase_map = {"0": ph}
        engine.all_phases = [ph]
        prompt = engine.get_phase_prompt("0")
        assert "Test" in prompt

    def test_get_phase_prompt_parallel(self):
        """Parallel phases produce a single merged prompt with per-phase agents and partner."""
        ph_a = MagicMock()
        ph_a.code = "parallel-a"
        ph_a.name = "Parallel A"
        ph_a.description = "Desc A"
        ph_a.execution_type = "parallel"
        ph_a.parallel_with = "parallel-b"
        ph_a.rollback_target = None
        ph_a.instructions = []
        ph_a.checks = []
        ph_a.evidence = []
        ph_a.delegate = None
        ph_a.next_recommendation = "next"

        ph_b = MagicMock()
        ph_b.code = "parallel-b"
        ph_b.name = "Parallel B"
        ph_b.description = "Desc B"
        ph_b.execution_type = "parallel"
        ph_b.parallel_with = "parallel-a"
        ph_b.rollback_target = None
        ph_b.instructions = []
        ph_b.checks = []
        ph_b.evidence = []
        ph_b.delegate = None
        ph_b.next_recommendation = "next"

        engine = WizardEngine("TASK-1")
        engine.phase_map = {"parallel-a": ph_a, "parallel-b": ph_b}
        engine.all_phases = [ph_a, ph_b]
        engine.current_phase = "parallel-a"
        prompt = engine.get_phase_prompt("parallel-a")
        assert "ПАРАЛЛЕЛЬНАЯ ГРУППА ФАЗ" in prompt
        assert "Parallel A, Parallel B" in prompt
        assert "параллельно с" in prompt
        assert "Выполняются одновременно" in prompt
        assert "Отчёт по этой группе присылается ОДНИМ сообщением" in prompt

    def test_get_full_context(self):
        engine = WizardEngine("TASK-1")
        ctx = engine.get_full_context()
        assert "current_phase" in ctx
        assert "all_phases" in ctx
        assert "messages" not in ctx


class TestPromptAndModels:
    def test_build_phase_prompt_missing_phase(self):
        from project_workflow.wizard.prompt import build_phase_prompt

        ctx = {"workflow_name": "W", "cli_actor": {"description": "d", "entrypoint": "e"}}
        result = build_phase_prompt("TASK-1", {}, [], "1", ctx, phase_id="missing")
        assert "не найдена" in result

    def test_build_phase_prompt_non_current_phase(self):
        from project_workflow.wizard.models import Phase
        from project_workflow.wizard.prompt import build_phase_prompt

        phase = Phase(code="2", name="Two", description="Desc", execution_type="sync")
        ctx = {"workflow_name": "W", "current_contract": None, "cli_actor": {"description": "d", "entrypoint": "e"}}
        result = build_phase_prompt("TASK-1", {"2": phase}, [phase], "1", ctx, phase_id="2")
        assert "Two" in result
        assert "Desc" in result

    def test_build_phase_prompt_current_contract_dict(self):
        from project_workflow.wizard.models import Phase
        from project_workflow.wizard.prompt import build_phase_prompt

        phase = Phase(code="1", name="One", description="Desc")
        contract = {
            "description": "CDesc",
            "execution_type": "sync",
            "parallel_with": None,
            "rollback_target": None,
            "next_recommendation": None,
            "instructions": ["I1"],
            "required_checks": ["C1"],
            "required_evidence": ["E1"],
            "delegate_agent": None,
        }
        ctx = {"workflow_name": "W", "current_contract": contract, "cli_actor": {"description": "d", "entrypoint": "e"}}
        result = build_phase_prompt("TASK-1", {"1": phase}, [phase], "1", ctx)
        assert "I1" in result
        assert "C1" in result
        assert "E1" in result

    def test_phase_dataclass_post_init_delegate(self):
        from project_workflow.wizard.models import Phase, PhaseDelegate

        phase = Phase(code="1", name="One", selected_agent="agent-x")
        assert isinstance(phase.delegate, PhaseDelegate)
        assert phase.delegate.agent == "agent-x"

    def test_phase_render_instructions(self):
        from project_workflow.wizard.models import Phase, PhaseInstruction

        phase = Phase(
            code="1",
            instructions=[PhaseInstruction(step="run {env}")],
        )
        rendered = phase.render_instructions({"env": "prod"})
        assert rendered == ["run prod"]
