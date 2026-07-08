"""Tests for wizard.models."""

from __future__ import annotations

from project_workflow.wizard.models import (
    Phase,
    PhaseCheck,
    PhaseDelegate,
    PhaseEvidence,
    PhaseInstruction,
)


def test_phase_delegate_from_selected_agent():
    p = Phase(code="1", name="A", selected_agent="researcher")
    assert p.delegate is not None
    assert p.delegate.agent == "researcher"


def test_phase_render_instructions():
    p = Phase(
        code="1",
        instructions=[PhaseInstruction(step="use {tool} for {repo}")],
    )
    rendered = p.render_instructions({"tool": "git", "repo": "x"})
    assert rendered == ["use git for x"]


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
