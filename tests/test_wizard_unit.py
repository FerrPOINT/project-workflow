"""Tests for wizard.py to boost coverage."""

from unittest.mock import patch, MagicMock
from wartz_workflow.wizard import WizardEngine


class TestWizard:
    def test_init(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            assert engine.task_key == "AAT-1"

    def test_init_bootstraps_phases_when_workflow_db_is_empty(self, tmp_path, monkeypatch):
        test_db = tmp_path / "workflow.db"
        monkeypatch.setattr("wartz_workflow.db.DB_PATH", test_db)

        with patch("wartz_workflow.wizard.convo") as mock_convo:
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
        with patch("wartz_workflow.wizard.convo") as mock_convo:
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

        with patch("wartz_workflow.wizard.convo") as mock_convo:
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
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            ctx = engine.get_full_context()
            assert "current_phase" in ctx
            assert "all_phases" in ctx
