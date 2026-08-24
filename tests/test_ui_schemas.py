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
    first = PhaseCreate(insert_after=0)
    assert first.phase_order == 1


def test_phase_create_rejects_conflicting_order_fields():
    with pytest.raises(ValueError, match="phase_order conflicts with insert_after"):
        PhaseCreate(phase_order=3, insert_after=0)


def test_phase_create_phase_order_coercion():
    p = PhaseCreate(phase_order="5")
    assert p.phase_order == 5
    with pytest.raises(ValueError):
        PhaseCreate(phase_order="bad")
    with pytest.raises(ValueError):
        PhaseCreate(phase_order="0")


def test_phase_update_fields():
    p = PhaseUpdate(name="X")
    assert p.name == "X"


def test_request_schemas_reject_unknown_legacy_fields():
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        PhaseUpdate.model_validate({"group_id": "legacy"})


def test_workflow_create_update():
    w = WorkflowCreate(name="W")
    assert w.name == "W"
    wu = WorkflowUpdate(description="D")
    assert wu.description == "D"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        WorkflowCreate.model_validate({"name": "W", "code": "legacy"})


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


@pytest.mark.parametrize("value", ["bad", 0, -1])
def test_project_workflow_id_rejects_invalid_explicit_values(value):
    with pytest.raises(ValueError, match="positive integer"):
        ProjectCreate(code="PRJ", key_prefixes=["PRJ"], workflow_id=value)
    with pytest.raises(ValueError, match="positive integer"):
        ProjectUpdate(workflow_id=value)


def test_project_update_optional_prefixes():
    p = ProjectUpdate(code="PRJ")
    assert p.key_prefixes is None
    with pytest.raises(ValueError, match="cannot be null"):
        ProjectUpdate(code="PRJ", key_prefixes=None)
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
    i = InstructionCreate(phase_id=1, description="Step", step_num=1)
    assert i.phase_id == 1
    assert i.step_num == 1
    iu = InstructionUpdate(description="Updated")
    assert iu.description == "Updated"
    iu2 = InstructionUpdate(skills=["s1", "s2"])
    assert iu2.skills == ["s1", "s2"]
    with pytest.raises(ValueError):
        InstructionCreate(phase_id=1, description="Step", step_num=0)
    with pytest.raises(ValueError):
        InstructionCreate(phase_id=1, description="Step", step_num="1")
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        InstructionUpdate.model_validate({"step_num": 1})


def test_phase_update_nested_contract_is_strict_and_normalized():
    update = PhaseUpdate.model_validate(
        {
            "instructions": [{"description": "  Run tests  ", "skills": [" testing "]}],
            "checks": [{"description": " Check result "}],
            "evidence": [{"description": " Evidence URL "}],
        }
    )
    assert update.instructions and update.instructions[0].description == "Run tests"
    assert update.instructions[0].skills == ["testing"]
    assert update.checks and update.checks[0].description == "Check result"

    invalid_payloads = [
        {"instructions": [{"skills": []}]},
        {"instructions": [{"description": "Step", "skills": "testing"}]},
        {"checks": [{"description": "Check", "command": None}]},
        {"evidence": [{"description": "Evidence", "validator": None}]},
        {"checks": [{"description": "same"}, {"description": " SAME "}]},
        {"evidence": None},
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValueError):
            PhaseUpdate.model_validate(payload)


@pytest.mark.parametrize(
    ("schema", "field"),
    [
        (PhaseUpdate, "name"),
        (PhaseUpdate, "execution_type"),
        (WorkflowUpdate, "name"),
        (WorkflowUpdate, "description"),
        (ProjectUpdate, "workflow_id"),
        (AgentUpdate, "description"),
        (InstructionUpdate, "description"),
        (InstructionUpdate, "execution_type"),
    ],
)
def test_nonnullable_update_fields_reject_explicit_null(schema, field):
    with pytest.raises(ValueError, match="cannot be null"):
        schema.model_validate({field: None})


def test_nullable_update_fields_distinguish_omitted_and_null():
    phase = PhaseUpdate.model_validate({"description": None, "agent_id": None})
    assert phase.model_fields_set == {"description", "agent_id"}
    assert phase.description is None
    assert PhaseUpdate().model_fields_set == set()

    instruction = InstructionUpdate.model_validate({"skills": None})
    assert instruction.model_fields_set == {"skills"}
    assert instruction.skills is None
