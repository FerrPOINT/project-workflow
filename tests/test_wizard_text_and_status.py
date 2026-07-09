"""Tests for text_from_* helpers and verdict labels."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.wizard]

from project_workflow.wizard.contracts import (
    text_from_check,
    text_from_evidence,
    text_from_instruction,
)
from project_workflow.wizard.types import VERDICT_LABELS


class TestTextHelpers:
    """Cover text_from_instruction, text_from_check, text_from_evidence."""

    def test_text_from_instruction_with_step(self):
        assert text_from_instruction(MagicMock(step="Step A")) == "Step A"

    def test_text_from_instruction_none(self):
        assert text_from_instruction(None) == ""

    def test_text_from_check_with_description(self):
        assert text_from_check(MagicMock(description="Check B")) == "Check B"

    def test_text_from_check_none(self):
        assert text_from_check(None) == ""

    def test_text_from_evidence_with_item(self):
        assert text_from_evidence(MagicMock(item="Evidence C")) == "Evidence C"

    def test_text_from_evidence_none(self):
        assert text_from_evidence(None) == ""


class TestVerdictLabels:
    def test_all_verdicts_present(self):
        for v in ("pass", "partial", "blocked", "rollback", "delegate"):
            assert v in VERDICT_LABELS
            assert VERDICT_LABELS[v].isupper()
