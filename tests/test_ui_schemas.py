"""Tests for interfaces.ui.schemas."""

from __future__ import annotations

import pytest

from project_workflow.interfaces.ui.schemas import (
    AgentCreate,
    AgentUpdate,
    InstructionCreate,
    InstructionUpdate,
    PhaseCreate,
    PhaseOrderUpdate,
    PhaseUpdate,
    ProjectCreate,
    ProjectUpdate,
    WorkflowCreate,
    WorkflowUpdate,
)


def test_phase_create_insert_after():
    p = PhaseCreate(insert_after=3)
    assert p.phase_order == 4


def test_phase_create_phase_order_coercion():
    p = PhaseCreate(phase_order="5")
    assert p.phase_order == 5
    p2 = PhaseCreate(phase_order="bad")
    assert p2.phase_order is None
    p3 = PhaseCreate(phase_order="0")
    assert p3.phase_order is None


def test_phase_update_fields():
    p = PhaseUpdate(name="X")
    assert p.name == "X"


def test_workflow_create_update():
    w = WorkflowCreate(name="W", code="w1")
    assert w.name == "W"
    wu = WorkflowUpdate(description="D")
    assert wu.description == "D"


def test_project_create_defaults():
    with pytest.raises(ValueError, match="At least one task key prefix"):
        ProjectCreate(code="PRJ")


def test_project_create_prefixes_from_str():
    p = ProjectCreate(code="PRJ", key_prefixes="aa\nbb")
    assert p.key_prefixes == ["AA", "BB"]


def test_project_create_invalid_prefix():
    with pytest.raises(ValueError, match="too short"):
        ProjectCreate(code="PRJ", key_prefixes=["a"])
    with pytest.raises(ValueError, match="Invalid prefix"):
        ProjectCreate(code="PRJ", key_prefixes=["1A"])


def test_project_update_optional_prefixes():
    p = ProjectUpdate(code="PRJ", key_prefixes=None)
    assert p.key_prefixes is None
    with pytest.raises(ValueError, match="At least one task key prefix"):
        ProjectUpdate(code="PRJ", key_prefixes="")


def test_agent_create_update():
    a = AgentCreate(name="Coder", hermes_profile=" code_profile ")
    assert a.name == "Coder"
    assert a.hermes_profile == "code_profile"
    au = AgentUpdate(name="New", hermes_profile="")
    assert au.name == "New"
    assert au.hermes_profile is None


@pytest.mark.parametrize("profile", ["UPPER", "space profile", "-leading", "profile.dot"])
def test_agent_rejects_invalid_hermes_profile(profile):
    with pytest.raises(ValueError, match="Hermes profile"):
        AgentCreate(name="Coder", hermes_profile=profile)


def test_phase_order_update():
    po = PhaseOrderUpdate(orders=[{"phase_id": 1, "phase_order": 2}])
    assert len(po.orders) == 1
    assert po.orders[0].phase_id == 1


def test_instruction_create_update():
    i = InstructionCreate(phase_id=1, description="Step")
    assert i.phase_id == 1
    iu = InstructionUpdate(description="Updated")
    assert iu.description == "Updated"
    iu2 = InstructionUpdate(skills=["s1", "s2"])
    assert iu2.skills == ["s1", "s2"]
