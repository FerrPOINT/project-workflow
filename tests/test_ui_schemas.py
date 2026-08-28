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
    p = PhaseCreate(workflow_id=1, insert_after=3)
    assert p.phase_order == 4
    first = PhaseCreate(workflow_id=1, insert_after=0)
    assert first.phase_order == 1


def test_phase_create_rejects_conflicting_order_fields():
    with pytest.raises(ValueError, match="phase_order противоречит insert_after"):
        PhaseCreate(workflow_id=1, phase_order=3, insert_after=0)


def test_phase_create_phase_order_is_strict():
    with pytest.raises(ValueError):
        PhaseCreate(workflow_id=1, phase_order="5")
    with pytest.raises(ValueError):
        PhaseCreate(workflow_id=1, phase_order=0)


@pytest.mark.parametrize(
    "payload",
    [
        {"phase_order": 1},
        {"workflow_id": None, "phase_order": 1},
        {"workflow_id": "1", "phase_order": 1},
        {"workflow_id": 1, "phase_order": None},
        {"workflow_id": 1, "insert_after": None},
        {"workflow_id": 1, "insert_after": "0"},
    ],
)
def test_phase_create_requires_strict_identifiers_and_order(payload):
    with pytest.raises(ValueError):
        PhaseCreate.model_validate(payload)


def test_phase_update_fields():
    p = PhaseUpdate(name="X")
    assert p.name == "X"
    with pytest.raises(ValueError, match="parallel_with"):
        PhaseUpdate(parallel_with=" ")


def test_request_schemas_reject_unknown_fields():
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        PhaseUpdate.model_validate({"unexpected": "value"})


def test_workflow_create_update():
    w = WorkflowCreate(name="W")
    assert w.name == "W"
    wu = WorkflowUpdate(description="D")
    assert wu.description == "D"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        WorkflowCreate.model_validate({"name": "W", "unexpected": "value"})
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        WorkflowCreate.model_validate({"name": "W", "theme_icon": "bug"})


def test_project_theme_create_update():
    p = ProjectCreate(code="PRJ", workflow_id=1, key_prefixes=["PRJ"])
    assert p.theme_icon == "project"
    assert p.theme_color == "#5E6AD2"
    themed = ProjectCreate(
        code="QA",
        workflow_id=1,
        key_prefixes=["QA"],
        theme_icon=" BUG ",
        theme_color="22c55e",
    )
    assert themed.theme_icon == "bug"
    assert themed.theme_color == "#22C55E"
    pu = ProjectUpdate(theme_icon="Rocket", theme_color="#0ea5e9")
    assert pu.theme_icon == "rocket"
    assert pu.theme_color == "#0EA5E9"
    with pytest.raises(ValueError, match="Иконка проекта"):
        ProjectCreate.model_validate(
            {"code": "PRJ", "workflow_id": 1, "key_prefixes": ["PRJ"], "theme_icon": "unknown"}
        )
    with pytest.raises(ValueError, match="HEX-цветом"):
        ProjectUpdate.model_validate({"theme_color": "not-a-color"})


def test_project_create_defaults():
    with pytest.raises(ValueError, match="Field required"):
        ProjectCreate(code="PRJ")


def test_project_create_rejects_prefixes_from_str():
    with pytest.raises(ValueError, match="массивом строк"):
        ProjectCreate(code="PRJ", key_prefixes="aa\nbb")


def test_project_prefixes_reject_non_string_items():
    with pytest.raises(ValueError, match="массивом строк"):
        ProjectCreate(code="PRJ", key_prefixes=["PRJ", 7])
    with pytest.raises(ValueError, match="не может быть пустым"):
        ProjectCreate(code="PRJ", key_prefixes=["PRJ", " "])


def test_phase_order_update_requires_non_empty_orders():
    for payload in ({}, {"orders": []}):
        with pytest.raises(ValueError):
            PhaseOrderUpdate.model_validate(payload)
    with pytest.raises(ValueError):
        PhaseOrderUpdate.model_validate({"orders": [{"phase_id": "1", "phase_order": 1}]})


def test_project_create_invalid_prefix():
    with pytest.raises(ValueError, match="слишком короткий"):
        ProjectCreate(code="PRJ", key_prefixes=["a"])
    with pytest.raises(ValueError, match="Недопустимый префикс"):
        ProjectCreate(code="PRJ", key_prefixes=["1A"])


@pytest.mark.parametrize("value", ["bad", 0, -1])
def test_project_workflow_id_rejects_invalid_explicit_values(value):
    with pytest.raises(ValueError):
        ProjectCreate(code="PRJ", key_prefixes=["PRJ"], workflow_id=value)
    with pytest.raises(ValueError):
        ProjectUpdate(workflow_id=value)


def test_project_update_optional_prefixes():
    p = ProjectUpdate(code="PRJ")
    assert p.key_prefixes is None
    with pytest.raises(ValueError, match="не могут быть null"):
        ProjectUpdate(code="PRJ", key_prefixes=None)
    with pytest.raises(ValueError, match="массивом строк"):
        ProjectUpdate(code="PRJ", key_prefixes="")


def test_agent_create_update():
    a = AgentCreate(name="Coder", hermes_profile=" code_profile ")
    assert a.name == "Coder"
    assert a.hermes_profile == "code_profile"
    au = AgentUpdate(name="New", hermes_profile=None)
    assert au.name == "New"
    assert au.hermes_profile is None
    with pytest.raises(ValueError, match="для очистки используйте null"):
        AgentUpdate(name="New", hermes_profile="")
    for invalid in (1, {}, []):
        with pytest.raises(ValueError):
            AgentUpdate.model_validate({"hermes_profile": invalid})


@pytest.mark.parametrize("profile", ["UPPER", "space profile", "-leading", "profile.dot"])
def test_agent_rejects_invalid_hermes_profile(profile):
    with pytest.raises(ValueError, match="Профиль Hermes"):
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
            "instructions": [{"id": None, "description": "  Run tests  ", "skills": [" testing "]}],
            "checks": [{"id": None, "description": " Check result "}],
            "evidence": [{"id": None, "description": " Evidence URL "}],
        }
    )
    assert update.instructions and update.instructions[0].description == "Run tests"
    assert update.instructions[0].skills == ["testing"]
    assert update.checks and update.checks[0].description == "Check result"

    invalid_payloads = [
        {"instructions": [{"id": None, "skills": []}]},
        {"instructions": [{"id": None, "description": "Step", "skills": "testing"}]},
        {"checks": [{"id": None, "description": "Check", "command": None}]},
        {"evidence": [{"id": None, "description": "Evidence", "validator": None}]},
        {"checks": [{"id": None, "description": "same"}, {"id": None, "description": " SAME "}]},
        {"evidence": None},
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValueError):
            PhaseUpdate.model_validate(payload)


@pytest.mark.parametrize("item_id", [True, "1", 0, -1])
def test_phase_update_rejects_noncanonical_nested_ids(item_id):
    with pytest.raises(ValueError):
        PhaseUpdate.model_validate({"checks": [{"id": item_id, "description": "Проверка"}]})


def test_phase_update_requires_nested_id_and_rejects_duplicates():
    with pytest.raises(ValueError):
        PhaseUpdate.model_validate({"checks": [{"description": "Проверка"}]})
    with pytest.raises(ValueError, match="Идентификаторы.*должны быть уникальными"):
        PhaseUpdate.model_validate(
            {
                "evidence": [
                    {"id": 7, "description": "Первое"},
                    {"id": 7, "description": "Второе"},
                ]
            }
        )


@pytest.mark.parametrize(
    ("schema", "field"),
    [
        (PhaseUpdate, "name"),
        (PhaseUpdate, "execution_type"),
        (WorkflowUpdate, "name"),
        (WorkflowUpdate, "description"),
        (ProjectUpdate, "workflow_id"),
        (ProjectUpdate, "theme_icon"),
        (ProjectUpdate, "theme_color"),
        (AgentUpdate, "description"),
        (InstructionUpdate, "description"),
        (InstructionUpdate, "execution_type"),
    ],
)
def test_nonnullable_update_fields_reject_explicit_null(schema, field):
    with pytest.raises(ValueError, match="не могут быть null"):
        schema.model_validate({field: None})


def test_nullable_update_fields_distinguish_omitted_and_null():
    phase = PhaseUpdate.model_validate({"description": None, "agent_id": None})
    assert phase.model_fields_set == {"description", "agent_id"}
    assert phase.description is None
    assert PhaseUpdate().model_fields_set == set()

    instruction = InstructionUpdate.model_validate({"skills": None})
    assert instruction.model_fields_set == {"skills"}
    assert instruction.skills is None
