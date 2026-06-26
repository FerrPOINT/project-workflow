"""Tests for wizard.py to boost coverage."""

import pytest
from unittest.mock import patch, MagicMock

pytestmark = [pytest.mark.wizard]

from project_workflow.wizard import WizardEngine


class TestWizard:
    def test_init(self):
        with patch("project_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            assert engine.task_key == "AAT-1"

    def test_init_bootstraps_phases_when_workflow_db_is_empty(self, tmp_path, monkeypatch):
        test_db = tmp_path / "workflow.db"
        monkeypatch.setattr("project_workflow.infrastructure.db.DB_PATH", test_db)

        with patch("project_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")

        assert engine.all_phases
        assert any(phase.code == "-1" for phase in engine.all_phases)

    def test_get_phase_prompt(self):
        ph = MagicMock()
        ph.code = "0"
        ph.name = "Test"
        ph.description = "D"
        ph.is_blocker = False
        ph.is_delegated = False
        ph.instructions = []
        with patch("project_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            engine.phase_map = {"0": ph}
            engine.all_phases = [ph]
            prompt = engine.get_phase_prompt("0")
            assert "Test" in prompt

    def test_get_phase_prompt_parallel(self):
        """Parallel phases produce a single merged prompt."""
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

        with patch("project_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            engine.phase_map = {"parallel-a": ph_a, "parallel-b": ph_b}
            engine.all_phases = [ph_a, ph_b]
            engine.current_phase = "parallel-a"
            prompt = engine.get_phase_prompt("parallel-a")
            assert "⚡ ПАРАЛЛЕЛЬНАЯ ГРУППА ФАЗ" in prompt
            assert "parallel-a" in prompt
            assert "parallel-b" in prompt

    def test_get_full_context(self):
        with patch("project_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            ctx = engine.get_full_context()
            assert "current_phase" in ctx
            assert "all_phases" in ctx


class TestPromptAndModels:
    def test_build_phase_prompt_missing_phase(self):
        from project_workflow.wizard.prompt import build_phase_prompt
        ctx = {"workflow_name": "W", "cli_actor": {"description": "d", "entrypoint": "e"}}
        result = build_phase_prompt("TASK-1", {}, [], "1", ctx, phase_id="missing")
        assert "не найдена" in result

    def test_build_phase_prompt_non_current_phase(self):
        from project_workflow.wizard.prompt import build_phase_prompt
        from project_workflow.wizard.models import Phase
        phase = Phase(code="2", name="Two", description="Desc", execution_type="sync")
        ctx = {"workflow_name": "W", "current_contract": None, "cli_actor": {"description": "d", "entrypoint": "e"}}
        result = build_phase_prompt("TASK-1", {"2": phase}, [phase], "1", ctx, phase_id="2")
        assert "Two" in result
        assert "Desc" in result

    def test_build_phase_prompt_current_contract_dict(self):
        from project_workflow.wizard.prompt import build_phase_prompt
        from project_workflow.wizard.models import Phase
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


class TestDeterministicChecks:
    def test_extract_keywords_empty_input(self):
        from project_workflow.wizard.checks import extract_keywords
        assert extract_keywords("") == []

    def test_extract_keywords_filters_short_words(self):
        from project_workflow.wizard.checks import extract_keywords
        assert extract_keywords("one two three four five six seven") == ["three", "four", "five", "seven"]

    def test_check_coverage_with_previously_covered(self):
        from project_workflow.wizard.checks import check_coverage
        covered, missing = check_coverage("report", ["item one"], previously_covered={"item one"})
        assert "item one" in covered
        assert missing == []

    def test_check_coverage_keyword_threshold(self):
        from project_workflow.wizard.checks import check_coverage
        covered, missing = check_coverage("alpha beta gamma", ["alpha beta", "delta echo"])
        assert "alpha beta" in covered
        assert "delta echo" in missing

    def test_extract_blockers_negative_phrases(self):
        from project_workflow.wizard.checks import extract_blockers
        assert extract_blockers("no blockers, everything fine") == []
        assert extract_blockers("blocked by dependency") == ["blocked by"]

    def test_determine_verdict_rollback(self):
        from project_workflow.wizard.checks import determine_verdict
        assert determine_verdict(covered=[], missing=["m"], blockers=[], report="rollback", rollback_target="0") == "rollback"

    def test_determine_verdict_delegate(self):
        from project_workflow.wizard.checks import determine_verdict
        assert determine_verdict(covered=[], missing=["m"], blockers=[], report="delegated", is_delegated=True) == "delegate"

    def test_build_verdict_message_parallel(self):
        from project_workflow.wizard.checks import build_verdict_message
        assert "Parallel group" in build_verdict_message("pass", "P", "1", [], [], "2", None, is_parallel=True, group_codes=["1", "2"])
        assert "Roll back" in build_verdict_message("rollback", "P", "1", [], [], None, "0", is_parallel=True, group_codes=["1", "2"])
        assert "Delegate work" in build_verdict_message("delegate", "P", "1", [], [], None, None, is_parallel=True, group_codes=["1", "2"])
        assert "BLOCKED" in build_verdict_message("blocked", "P", "1", ["b"], [], None, None, is_parallel=True, group_codes=["1", "2"])
