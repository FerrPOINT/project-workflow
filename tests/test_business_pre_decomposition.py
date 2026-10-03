"""Opt-in business context, not proof of native owner execution readiness."""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from project_workflow import build_provenance, config
from project_workflow.application import base_admission
from project_workflow.application.task import TaskService
from project_workflow.domain.assignment_resources import (
    BUSINESS_PRE_DECOMPOSITION,
    BUSINESS_PRE_DECOMPOSITION_MODES,
    LEGACY_RESOURCE_FIELDS,
    PRE_DECOMPOSITION_ABSENT_FIELDS,
)
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog, load_managed_catalog
from project_workflow.infrastructure.db.models import TaskRuntimeAssignment as AssignmentRow
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.routes import runtime_api
from project_workflow.interfaces.ui.schemas import RuntimeAssignmentRequest
from tests.base_candidate.test_admission import (
    AGENT,
    OWNER,
    REAL_OWNER_EVIDENCE_GUARD,
    RUNTIME,
    snapshot,
    step,
)
from tests.base_candidate.test_admission import (
    base as base_fixture,
)
from tests.test_runtime_api import TEST_RUNTIME_COMPATIBILITY, _assignment, _bind_payload

base = base_fixture


def business_request(role="analyst", *, logical_workspace=False):
    request = _assignment("DEV-1", "assign:business:1", role)
    request.update(assignment_shape=BUSINESS_PRE_DECOMPOSITION,
                   mode_key=BUSINESS_PRE_DECOMPOSITION_MODES[role])
    for field in (*LEGACY_RESOURCE_FIELDS, *PRE_DECOMPOSITION_ABSENT_FIELDS):
        request.pop(field, None)
    if logical_workspace:
        request.update(task_workspace_ref="task-workspace:real-tracker-ref", workspace_revision=3)
    return request


@pytest.mark.parametrize("role", BUSINESS_PRE_DECOMPOSITION_MODES)
@pytest.mark.parametrize("logical_workspace", [False, True])
def test_explicit_business_dto_without_fabricated_resources(role, logical_workspace):
    parsed = RuntimeAssignmentRequest.model_validate(business_request(role, logical_workspace=logical_workspace))
    assert parsed.assignment_shape == BUSINESS_PRE_DECOMPOSITION
    assert all(getattr(parsed, field) is None for field in PRE_DECOMPOSITION_ABSENT_FIELDS)
    assert (parsed.task_workspace_ref is not None) == logical_workspace


@pytest.mark.parametrize("changes", [
    {"assignment_shape": None}, {"assignment_shape": "business"},
    {"role_key": "developer", "workflow_key": "hermes-sdlc:developer", "mode_key": "initial"},
    {"role_key": "developer", "workflow_key": "hermes-sdlc:developer", "mode_key": "rework"},
    {"role_key": "reviewer", "workflow_key": "hermes-sdlc:reviewer", "mode_key": "delivery"},
    {"role_key": "tester", "workflow_key": "hermes-sdlc:tester", "mode_key": "integration"},
    {"role_key": "devops", "workflow_key": "hermes-sdlc:devops", "mode_key": "integration"},
    {"execution_scope": "delivery"}, {"execution_scope": "aggregate"},
    {"mode_key": "assigned"}, {"workflow_key": "hermes-sdlc:architect"},
    {"decomposition_revision_ref": "decomposition:invented"},
    {"tech_execution_workspace_ref": "forge:invented"}, {"tech_execution_attempt_ref": "attempt:invented"},
    {"workspace_generation": 0}, {"lease_generation": 0},
    {"task_workspace_ref": "tracker:real"}, {"workspace_revision": 3},
    {"task_workspace_ref": " ", "workspace_revision": 3},
    {"task_workspace_ref": "tracker:real", "workspace_revision": 0},
    {"task_workspace_ref": "tracker:real", "workspace_revision": True},
    {"attempt_number": 0}, {"queue_item_ref": " "},
])
def test_invalid_business_shape_is_rejected(changes):
    with pytest.raises(ValidationError):
        RuntimeAssignmentRequest.model_validate({**business_request(), **changes})


@pytest.mark.parametrize("field", LEGACY_RESOURCE_FIELDS)
@pytest.mark.parametrize("explicit_null", [False, True])
def test_legacy_resource_requirements_not_weakened(field, explicit_null):
    request = _assignment("DEV-1", "legacy:1", "developer")
    if explicit_null:
        request[field] = None
    else:
        del request[field]
    with pytest.raises(ValidationError):
        RuntimeAssignmentRequest.model_validate(request)


def test_legacy_wire_shape_and_hash_do_not_gain_marker():
    request = _assignment("DEV-1", "legacy:1", "developer")
    parsed = RuntimeAssignmentRequest.model_validate(request)
    assert parsed.model_dump(mode="json", exclude_unset=True) == request
    assert payload_sha256(parsed.model_dump(mode="json", exclude_unset=True)) == payload_sha256(request)
    assert "assignment_shape" not in parsed.model_dump(mode="json")


def test_conditional_schema_keeps_legacy_required_and_exact_business_policy():
    schema = RuntimeAssignmentRequest.model_json_schema()
    legacy, business = schema["oneOf"]
    assert legacy["required"] == list(LEGACY_RESOURCE_FIELDS)
    assert business["required"] == ["assignment_shape"]
    assert business["properties"]["execution_scope"] == {"const": "business"}
    for field in PRE_DECOMPOSITION_ABSENT_FIELDS:
        assert business["properties"][field] == {"type": "null"}
    assert [(item["properties"]["role_key"]["const"], item["properties"]["mode_key"]["const"])
            for item in business["oneOf"]] == list(BUSINESS_PRE_DECOMPOSITION_MODES.items())


@pytest.fixture
def business_api(monkeypatch):
    def descriptor(**_kwargs):
        return dict(TEST_RUNTIME_COMPATIBILITY)
    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor", descriptor)
    monkeypatch.setattr(runtime_api, "runtime_compatibility_descriptor", descriptor)
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps(
        {role: "owner-" + role + "x" * 32 for role in BUSINESS_PRE_DECOMPOSITION_MODES}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps(
        {role: "runtime-" + role + "x" * 32 for role in BUSINESS_PRE_DECOMPOSITION_MODES}))
    config.get_settings.cache_clear()
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow)
        uow.commit()
    with TestClient(create_app()) as client:
        yield client


def owner(role="analyst"):
    return {"Authorization": "Bearer owner-" + role + "x" * 32}


def service_request(uow, request):
    parsed = RuntimeAssignmentRequest.model_validate(request)
    values = parsed.model_dump(mode="json")
    values["exact_input_refs"] = [item.model_dump(exclude_unset=True) for item in parsed.exact_input_refs]
    namespace = uow.projects.get_by_cli_command("workflow-" + values["role_key"])
    values["project_id"] = namespace.id
    values["task_key"] = values.pop("task")
    return values


@pytest.mark.parametrize("role", BUSINESS_PRE_DECOMPOSITION_MODES)
@pytest.mark.parametrize("logical_workspace", [False, True])
def test_authorized_business_assign_bind_restart_replay(business_api, role, logical_workspace):
    request = business_request(role, logical_workspace=logical_workspace)
    response = business_api.post("/internal/runtime/assign", headers=owner(role), json=request)
    assert response.status_code == 200, response.text
    assigned = response.json()["result"]
    assert assigned["assignment_shape"] == BUSINESS_PRE_DECOMPOSITION
    assert all(assigned[field] is None for field in PRE_DECOMPOSITION_ABSENT_FIELDS)
    bind = {**_bind_payload(assigned), "concrete_agent_ref": AGENT}
    response = business_api.post("/internal/runtime/bind", headers=owner(role), json=bind)
    assert response.status_code == 200, response.text
    bound = response.json()["result"]
    with SAUnitOfWork() as uow:
        ledger = uow.tasks.get_assignment_by_operation_key(request["operation_key"])
        assert ledger.assignment_shape == BUSINESS_PRE_DECOMPOSITION
        assert ledger.payload_sha256 == payload_sha256(ledger.payload)
        assert ledger.to_dict()["assignment_shape"] == ledger.payload["assignment_shape"]
        assert all(getattr(ledger, field) is None for field in PRE_DECOMPOSITION_ABSENT_FIELDS)
        replay = TaskService(uow).assign_runtime_task(**service_request(uow, request))
        assert replay["binding_ref"] == bound["binding_ref"]
        with pytest.raises(ConflictError):
            TaskService(uow).assign_runtime_task(**service_request(uow, {
                **request, "task_workspace_ref": "tracker:changed", "workspace_revision": 4,
            }))
        with pytest.raises(ConflictError, match="trusted owner checkpoint"):
            TaskService(uow).rebind_runtime_assignment(project_id=ledger.project_id, role_key=role, request={
                "task": assigned["task_key"], "operation_key": "continue:business:1",
            })
        assert len(uow.tasks.list_assignments(ledger.task_id)) == 1
    assert business_api.post("/internal/runtime/bind", headers=owner(role), json=bind).json()["result"] == bound


@pytest.mark.parametrize("headers,status", [
    ({}, 401), ({"Authorization": "Bearer runtime-analyst" + "x" * 32}, 403),
    (owner("architect"), 403),
])
def test_business_shape_does_not_change_assignment_authorization(business_api, headers, status):
    response = business_api.post("/internal/runtime/assign", headers=headers, json=business_request())
    assert response.status_code == status, response.text
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_assignment_by_operation_key("assign:business:1") is None


@pytest.mark.parametrize("changes", [
    {"assignment_shape": None}, {"assignment_shape": "unknown"},
    {"workspace_generation": 0}, {"decomposition_revision_ref": "fake"},
    {"task_workspace_ref": "tracker:unpaired"}, {"mode_key": "draft"}, {"execution_scope": "aggregate"},
])
def test_direct_service_cannot_bypass_resource_fencing(business_api, changes):
    with SAUnitOfWork() as uow:
        request = {**service_request(uow, business_request()), **changes}
        with pytest.raises((ValueError, ConflictError)):
            TaskService(uow).assign_runtime_task(**request)
        assert uow.tasks.get_assignment_by_operation_key(request["operation_key"]) is None


@pytest.mark.parametrize("role,mode,scope", [
    ("developer", "initial", "delivery"), ("developer", "initial", "aggregate"),
    ("developer", "rework", "delivery"), ("developer", "rework", "aggregate"),
    ("reviewer", "delivery", "delivery"), ("reviewer", "integration", "aggregate"),
    ("tester", "delivery", "delivery"), ("tester", "integration", "aggregate"),
    ("devops", "delivery", "delivery"), ("devops", "integration", "aggregate"),
])
def test_all_resource_bound_modes_still_require_real_resources(business_api, role, mode, scope):
    with SAUnitOfWork() as uow:
        request = _assignment("DEV-1", "assign:resource-bound:1", role)
        request.update(mode_key=mode, execution_scope=scope,
                       tech_execution_workspace_ref="forge:real", tech_execution_attempt_ref="attempt:real")
        values = service_request(uow, request)
        for field in (*LEGACY_RESOURCE_FIELDS, "tech_execution_workspace_ref", "tech_execution_attempt_ref"):
            with pytest.raises((ValueError, ConflictError)):
                TaskService(uow).assign_runtime_task(**{**values, field: None})
        with pytest.raises((ValueError, ConflictError)):
            TaskService(uow).assign_runtime_task(**{**values, "assignment_shape": BUSINESS_PRE_DECOMPOSITION})
        assert uow.tasks.get_assignment_by_operation_key(request["operation_key"]) is None


@pytest.mark.parametrize("field,value", [
    ("assignment_shape", None), ("assignment_shape", "unknown"), ("role_key", "developer"),
    ("workflow_key", "hermes-sdlc:developer"), ("execution_scope", "aggregate"),
    ("queue_item_ref", None), ("role_key", None), ("workspace_generation", 0),
    ("lease_generation", 0), ("decomposition_revision_ref", "fake"),
    ("task_workspace_ref", "tracker:unpaired"), ("workspace_revision", 2),
    ("binding_ref", "partial"),
])
def test_db_constraint_rejects_partial_and_unmarked_business_binding(business_api, field, value):
    with SAUnitOfWork() as uow:
        assigned = TaskService(uow).assign_runtime_task(**service_request(uow, business_request()))
        ledger = uow.tasks.get_assignment_by_operation_key(assigned["assignment_operation_key"])
        row = uow.session.get(AssignmentRow, ledger.id)
        setattr(row, field, value)
        with pytest.raises(IntegrityError):
            uow.session.flush()
        uow.rollback()


@pytest.mark.parametrize("role", BUSINESS_PRE_DECOMPOSITION_MODES)
def test_v3_business_source_context_never_unblocks_owner_execution(base, monkeypatch, role):  # noqa: F811
    client, payload = base
    monkeypatch.setattr(base_admission, "require_owner_execution_evidence", REAL_OWNER_EVIDENCE_GUARD)
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({role: OWNER["Authorization"][7:]}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({role: RUNTIME["Authorization"][7:]}))
    config.get_settings.cache_clear()
    workflow = next(w for w in load_managed_catalog(base_admission.CANDIDATE_PATH).workflows if w.role_key == role)
    admission = {**payload["base_admission"], "namespace": workflow.hermes_namespace,
                 "profile": workflow.hermes_profile, "physical_skills": workflow.skill_allowlist}
    request = {**business_request(role), "runtime_compatibility": None, "base_admission": admission}
    response = client.post("/internal/runtime/assign", headers=OWNER, json=request)
    assert response.status_code == 200, response.text
    assigned = response.json()["result"]
    response = client.post("/internal/runtime/bind", headers=OWNER,
                           json={**_bind_payload(assigned), "concrete_agent_ref": AGENT})
    assert response.status_code == 200, response.text
    bound = response.json()["result"]
    before = snapshot()
    response = client.post("/internal/runtime/step", headers=RUNTIME, json=step(bound, {"base_admission": admission}))
    assert response.status_code == 409, response.text
    assert "trusted owner" in response.text or "PM execution" in response.text
    assert snapshot() == before
