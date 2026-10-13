"""PM Draft assignment through the public machine boundary, before queue/workspace allocation."""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from project_workflow import build_provenance, config
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.routes import runtime_api
from tests.test_runtime_api import TEST_RUNTIME_COMPATIBILITY, _assignment, _bind_payload, _step_payload

PATH = "/internal/runtime/v1/pm/assign"
ADAPTER = {"Authorization": "Bearer " + "a" * 40}


@pytest.fixture
def draft(monkeypatch):
    yield from prepare_pm_draft(monkeypatch)


def prepare_pm_draft(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"project_manager": "a" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"project_manager": "r" * 40}))
    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor", lambda **_: TEST_RUNTIME_COMPATIBILITY)
    monkeypatch.setattr(runtime_api, "runtime_compatibility_descriptor", lambda **_: TEST_RUNTIME_COMPATIBILITY)
    config.get_settings.cache_clear()
    project_ref, task_ref, assignment_ref = (str(uuid4()) for _ in range(3))
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow)
        project = uow.projects.get_by_cli_command("workflow-project_manager")
        uow.projects.create_pm_ownership(
            {
                "contract_version": 1,
                "ownership_ref": str(uuid4()),
                "namespace_id": project.id,
                "tracker_instance_ref": "tracker:qa",
                "tracker_project_ref": project_ref,
                "authority_issuer": "http://auth.test",
                "provisioner_subject": str(uuid4()),
            }
        )
    request = {
        "task": "SDLC-21",
        "execution_ref": str(uuid4()),
        "tracker_instance_ref": "tracker:qa",
        "tracker_project_ref": project_ref,
        "task_ref": task_ref,
        "root_ref": task_ref,
        "agent_ref": str(uuid4()),
        "assignment_ref": assignment_ref,
        "assignment_operation_key": f"pm-draft:{assignment_ref}",
        "assignment_revision": 1,
        "owner_version": 1,
        "input_snapshot_ref": str(uuid4()),
        "input_sha256": "a" * 64,
        "runtime_compatibility": TEST_RUNTIME_COMPATIBILITY,
    }
    with TestClient(create_app()) as client:
        yield client, request


def test_pm_draft_assign_uses_real_input_without_future_resources(draft):
    client, request = draft
    response = client.post(PATH, headers=ADAPTER, json=request)
    assert response.status_code == 200, response.text[:1000]
    result = response.json()["result"]
    assert result["business_task_ref"] == request["task_ref"]
    assert result["assignment_ref"] == request["assignment_ref"]
    for field in (
        "work_item_ref",
        "work_item_revision",
        "queue_item_ref",
        "task_workspace_ref",
        "workspace_revision",
        "decomposition_revision_ref",
        "workspace_generation",
    ):
        assert result[field] is None
    replay = client.post(PATH, headers=ADAPTER, json=request)
    assert replay.status_code == 200
    assert replay.json() == response.json()
    changed = {**request, "input_sha256": "b" * 64}
    assert client.post(PATH, headers=ADAPTER, json=changed).status_code == 409


def test_pm_draft_assign_does_not_relax_generic_assignments(draft):
    client, _ = draft
    request = _assignment("SDLC-22", "ordinary-pm-assignment", "project_manager")
    request["mode_key"] = "draft"
    del request["queue_item_ref"]
    assert client.post("/internal/runtime/assign", headers=ADAPTER, json=request).status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("mode_key", "analysis"),
        ("runtime_ready", True),
        ("queue_item_ref", "invented"),
        ("assignment_revision", True),
        ("owner_version", 2),
        ("task", "SDLC-021"),
        ("agent_ref", "00000000-0000-0000-0000-000000000000"),
    ],
)
def test_pm_draft_assign_rejects_invented_fields_and_identity(draft, field, value):
    client, request = draft
    assert client.post(PATH, headers=ADAPTER, json={**request, field: value}).status_code == 422


def test_pm_draft_assign_requires_adapter_and_canonical_namespace_owner(draft):
    client, request = draft
    for headers in ({}, {"Authorization": "Bearer " + "r" * 40}):
        assert client.post(PATH, headers=headers, json=request).status_code in (401, 403)
    assert client.post(PATH, headers=ADAPTER, json={**request, "tracker_project_ref": str(uuid4())}).status_code == 409


def test_pm_draft_binding_keeps_original_agent_and_cannot_step_before_enrollment(draft):
    client, request = draft
    assigned = client.post(PATH, headers=ADAPTER, json=request).json()["result"]
    binding = {**_bind_payload(assigned), "concrete_agent_ref": str(uuid4())}
    assert client.post("/internal/runtime/bind", headers=ADAPTER, json=binding).status_code == 409
    binding["concrete_agent_ref"] = request["agent_ref"]
    response = client.post("/internal/runtime/bind", headers=ADAPTER, json=binding)
    assert response.status_code == 200, response.text[:1000]
    bound = response.json()["result"]
    assert (
        client.post(
            "/internal/runtime/step", headers={"Authorization": "Bearer " + "r" * 40}, json=_step_payload(bound)
        ).status_code
        == 409
    )
    with SAUnitOfWork() as uow:
        project = uow.projects.get_by_cli_command("workflow-project_manager")
        from project_workflow.application.task import TaskService
        from project_workflow.domain.exceptions import ConflictError

        with pytest.raises(ConflictError, match="PM resume/rebind"):
            TaskService(uow).rebind_runtime_assignment(
                project_id=project.id,
                role_key="project_manager",
                request={"task": request["task"], "operation_key": "bypass-resume"},
            )


def test_pm_draft_cannot_be_replaced_by_generic_assignment_after_manual_done(draft):
    client, request = draft
    original = client.post(PATH, headers=ADAPTER, json=request).json()["result"]
    with SAUnitOfWork() as uow:
        project = uow.projects.get_by_cli_command("workflow-project_manager")
        task = uow.tasks.get_by_key(request["task"], project_id=project.id)
        uow.tasks.update(task.id, {"status": "done"})
    generic = _assignment(request["task"], "bypass-draft-reservation", "project_manager")
    generic.update(mode_key="draft", expected_revision=1, expected_status="done", attempt_number=2)
    assert client.post("/internal/runtime/assign", headers=ADAPTER, json=generic).status_code == 409
    replay = client.post(PATH, headers=ADAPTER, json=request).json()["result"]
    assert replay["assignment_ref"] == original["assignment_ref"]


def test_pm_draft_enrollment_requires_original_execution_identity_before_probe(draft, monkeypatch):
    from project_workflow.domain.pm_execution import PMIdentity, RuntimeObservation
    from project_workflow.infrastructure import pm_readback

    client, request = draft
    for key, value in {
        "PROJECT_WORKFLOW_PM_SCOPE_SECRET": "s" * 40,
        "PROJECT_WORKFLOW_PM_READBACK_TOKEN": "p" * 40,
        "PROJECT_WORKFLOW_PM_READBACK_URL": "http://runtime.test/readback",
    }.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()
    result = client.post(PATH, headers=ADAPTER, json=request).json()["result"]
    binding = {**_bind_payload(result, hermes_run_ref="native_run_test"), "concrete_agent_ref": request["agent_ref"]}
    assert client.post("/internal/runtime/bind", headers=ADAPTER, json=binding).status_code == 200
    identity = {key: request[key] for key in PMIdentity.model_fields}
    command = {
        **identity,
        "operation_key": "pm-bind-initial",
        "expected_version": 0,
        "session_run_id": str(uuid4()),
        "binding_ref": binding["binding_ref"],
        "hermes_run_ref": binding["hermes_run_ref"],
    }
    probes = []

    def observe(run_id):
        probes.append(run_id)
        return RuntimeObservation.model_validate(
            {
                **identity,
                "observation_ref": str(uuid4()),
                "status": "running",
                "binding_ref": command["binding_ref"],
                "hermes_run_ref": command["hermes_run_ref"],
                "session_run_id": run_id,
                "dispatch_operation_key": command["operation_key"],
                "checkpoint_ref": None,
                "fence": 1,
            }
        )

    monkeypatch.setattr(pm_readback, "observe_run", observe)
    route = "/internal/runtime/v1/pm/bind"
    assert client.post(route, headers=ADAPTER, json={**command, "execution_ref": str(uuid4())}).status_code == 409
    assert probes == []
    accepted = client.post(route, headers=ADAPTER, json=command)
    assert accepted.status_code == 200, accepted.text[:1000]
    assert accepted.json()["result"]["identity"] == identity
    assert probes == [command["session_run_id"]]
