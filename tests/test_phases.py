"""Тесты модуля phases.py."""

import pytest

from wartz_workflow import phases
from wartz_workflow.config import PHASE_ORDER


class TestGetNextPhase:
    def test_next(self):
        assert phases.get_next_phase("-1") == "0.0a"
        assert phases.get_next_phase("0.0a") == "0.01"
        assert phases.get_next_phase("8") == "9"
        assert phases.get_next_phase("9") == "10"

    def test_last(self):
        assert phases.get_next_phase("10") is None

    def test_unknown(self):
        assert phases.get_next_phase("999") is None


class TestGetPhaseChecklistRaw:
    def test_known_phase(self):
        items = phases.get_phase_checklist_raw("0")
        assert len(items) >= 3
        assert "Jira" in items[0]

    def test_unknown_phase(self):
        items = phases.get_phase_checklist_raw("nonexistent")
        assert items == []
