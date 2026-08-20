"""Tests for wizard.models."""

from __future__ import annotations

from project_workflow.wizard.models import (
    Phase,
    PhaseCheck,
    PhaseDelegate,
    PhaseEvidence,
)


def test_phase_defaults():
    p = Phase()
    assert p.code == ""
    assert p.instructions == []
    assert p.delegate is None


def test_phase_check_evidence_defaults():
    assert PhaseCheck().description == ""
    assert PhaseEvidence().item == ""


def test_phase_delegate_defaults():
    d = PhaseDelegate()
    assert d.timeout_min == 10
    assert d.max_cycles == 3
