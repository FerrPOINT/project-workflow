"""Tests for wizard.py to boost coverage."""

import pytest
from unittest.mock import patch, MagicMock
from wartz_workflow.wizard import WizardEngine


class TestWizard:
    def test_init(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            assert engine.task_key == "AAT-1"

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

    def test_get_full_context(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            ctx = engine.get_full_context()
            assert "current_phase" in ctx
            assert "all_phases" in ctx
