"""Test WizardEngine with mocked DB."""

import pytest
from unittest.mock import patch, MagicMock
from wartz_workflow.wizard import WizardEngine
from wartz_workflow.models import Phase


class TestWizardEvaluate:
    def test_evaluate_pass(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = "-1"
            engine = WizardEngine("AAT-1", repo="/tmp")
            ph = MagicMock()
            ph.code = "0"
            ph.name = "Test"
            ph.is_blocker = False
            ph.is_delegated = False
            ph.is_critic = False
            ph.instructions = []
            engine.phase_map = {"0": ph}
            engine.all_phases = [ph]

            with patch.object(engine, "_build_checklist", return_value=["check"]), \
                 patch.object(engine, "_check_coverage", return_value=(["check"], [])), \
                 patch.object(engine, "_get_next_phase", return_value=("1", "Next")), \
                 patch.object(engine, "_record_transition"):
                result = engine.evaluate("report ok")
                assert result["verdict"] == "PASS"

    def test_evaluate_fail(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = "0"
            engine = WizardEngine("AAT-1", repo="/tmp")
            ph = MagicMock()
            ph.code = "0"
            ph.name = "Test"
            ph.is_blocker = False
            ph.is_delegated = False
            ph.is_critic = False
            ph.instructions = []
            engine.phase_map = {"0": ph}
            engine.all_phases = [ph]

            with patch.object(engine, "_build_checklist", return_value=["check"]), \
                 patch.object(engine, "_check_coverage", return_value=([], ["check"])), \
                 patch.object(engine, "_build_fail_message", return_value="fail msg"):
                result = engine.evaluate("report bad")
                assert result["verdict"] == "FAIL"

    def test_get_phase_prompt(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = "0"
            engine = WizardEngine("AAT-1", repo="/tmp")
            ph = MagicMock()
            ph.code = "0"
            ph.name = "Test"
            ph.description = "D"
            ph.is_blocker = False
            ph.is_delegated = False
            ph.instructions = []
            engine.phase_map = {"0": ph}
            engine.all_phases = [ph]

            with patch.object(engine, "_build_checklist", return_value=[]):
                prompt = engine.get_phase_prompt()
                assert "Test" in prompt
