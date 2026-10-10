"""Persistent PM contract tests through the real namespace runtime API."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from project_workflow import config, supervisor
from project_workflow.application.pm_execution import PMExecutionService
from project_workflow.application.task import TaskService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.pm_execution import PMIdentity, RuntimeObservation
from project_workflow.domain.runtime_assignment import NIL_FLEET_AGENT_REF
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from scripts.export_pm_openapi import OUTPUT, pm_openapi
from tests.test_runtime_api import TEST_RUNTIME_COMPATIBILITY, _assignment, _bind_payload, _namespace, _step_payload

BASE = "/internal/runtime/v1/pm"
ADAPTER = {"Authorization": "Bearer " + "a" * 40}
RUNTIME = {"Authorization": "Bearer " + "r" * 40}
OLD_RUN = "11111111-1111-4111-8111-111111111111"
NEW_RUN = "22222222-2222-4222-8222-222222222222"
AGENT_REF = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PROJECT_REF = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
OTHER_AGENT_REF = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.fixture
def pm(monkeypatch):
    yield from prepare_pm(monkeypatch)


def prepare_pm(monkeypatch, *, ownership=True):
    from project_workflow import build_provenance
    from project_workflow.interfaces.ui.routes import runtime_api

    def descriptor(**_kwargs):
        return dict(TEST_RUNTIME_COMPATIBILITY)

    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor", descriptor)
    monkeypatch.setattr(runtime_api, "runtime_compatibility_descriptor", descriptor)
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"project_manager": "a" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"project_manager": "r" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_SCOPE_SECRET", "s" * 40)
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_TOKEN", "p" * 40)
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_URL", "http://runtime.test/readback")
    config.get_settings.cache_clear()
    _namespace("PM", "workflow-project_manager", "PM")
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_cli_command("workflow-project_manager")
        if ownership:
            uow.projects.create_pm_ownership({
                "contract_version": 1, "ownership_ref": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
                "namespace_id": namespace.id, "tracker_instance_ref": "tracker:one", "tracker_project_ref": PROJECT_REF,
                "authority_issuer": "http://auth.test", "provisioner_subject": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            })
        phase = uow.session.scalar(select(m.Phase).where(m.Phase.code == "assigned"))
        agent_id = uow.agents.create({"name": "project_manager", "description": ""})
        phase.agent_id = agent_id
    client = TestClient(create_app())
    assignment = client.post("/internal/runtime/assign", headers=ADAPTER,
                             json=_assignment("PM-1", "assign:pm:1", "project_manager")).json()["result"]
    binding = _bind_payload(assignment)
    binding["concrete_agent_ref"] = AGENT_REF
    result = client.post("/internal/runtime/bind", headers=ADAPTER, json=binding)
    assert result.status_code == 200
    bound = result.json()["result"]
    identity = {
        "task": "PM-1", "execution_ref": "execution:pm:1", "tracker_instance_ref": "tracker:one",
        "tracker_project_ref": PROJECT_REF, "task_ref": assignment["business_task_ref"],
        "root_ref": assignment["root_task_ref"], "agent_ref": AGENT_REF,
        "assignment_operation_key": assignment["assignment_operation_key"],
        "assignment_ref": assignment["assignment_ref"], "assignment_revision": assignment["assignment_revision"],
    }
    bind = {
        **identity, "operation_key": "pm-bind:1", "expected_version": 0,
        "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
        "session_run_id": OLD_RUN,
    }
    observations = {
        OLD_RUN: {
            **identity, "observation_ref": "observation:1", "status": "running",
            "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
            "dispatch_operation_key": "pm-bind:1", "fence": 1,
            "session_run_id": OLD_RUN,
        },
    }

    def observe(run_ref):
        return RuntimeObservation.model_validate(observations[run_ref])

    monkeypatch.setattr(pm_readback, "observe_run", observe)
    yield client, identity, bind, observations, bound
    client.close()


def bind_pm(pm):
    client, identity, bind, observations, bound = pm
    response = client.post(BASE + "/bind", headers=ADAPTER, json=bind)
    assert response.status_code == 200, response.text
    runtime = {**RUNTIME, "X-Workflow-Execution-Token": response.json()["execution_token"]}
    checkpoint = {
        **identity, "operation_key": "checkpoint:1", "expected_version": 1, "expected_fence": 1,
        "binding_ref": bind["binding_ref"], "hermes_run_ref": bind["hermes_run_ref"],
        "session_run_id": OLD_RUN,
        "checkpoint_ref": "checkpoint:one", "clarification_request_ref": "request:one",
        "clarification_version": 1, "requirements_revision": 1,
    }
    return client, runtime, checkpoint, observations, bound


def waiting_pm(pm):
    client, runtime, checkpoint, observations, bound = bind_pm(pm)
    response = client.post(BASE + "/checkpoint", headers=runtime, json=checkpoint)
    assert response.status_code == 200, response.text
    observations[OLD_RUN]["checkpoint_ref"] = checkpoint["checkpoint_ref"]
    resume = {
        **checkpoint, "operation_key": "resume:1", "expected_version": 2,
        "answer_event_ref": "answer:one", "new_session_run_id": NEW_RUN,
    }
    return client, runtime, checkpoint, resume, observations, bound


def test_wait_resume_new_run_survives_sessions_and_replays(pm):
    client, runtime, checkpoint, resume, observations, bound = waiting_pm(pm)
    with SAUnitOfWork() as uow:
        initial = json.loads(uow.session.get(m.PMRun, OLD_RUN).observation_json)
        assert initial.get("checkpoint_ref") is None
    replay = client.post(BASE + "/checkpoint", headers=runtime, json=checkpoint)
    assert replay.json()["result"]["state"] == "waiting"
    assert replay.json()["result"]["workflow_step_allowed"] is False
    assert replay.json()["result"]["terminal_readback"] is None
    assert client.post(BASE + "/resume", headers=ADAPTER, json=resume).status_code == 409
    observations[OLD_RUN]["status"] = "stopped"
    reserved = client.post(BASE + "/resume", headers=ADAPTER, json=resume)
    assert reserved.status_code == 200, reserved.text
    assert reserved.json()["result"]["state"] == "resume_pending"
    assert reserved.json()["result"]["resume_delivered"] is False
    assert reserved.json()["result"]["fence"] == 2
    assert client.post(BASE + "/resume", headers=ADAPTER, json=resume).json() == reserved.json()
    rebind = {
        **PMExecutionService.identity(PMIdentity.model_validate(pm[1])).model_dump(),
        "operation_key": "rebind:1", "expected_version": 3, "expected_fence": 2,
        "binding_ref": resume["binding_ref"], "hermes_run_ref": resume["hermes_run_ref"],
        "checkpoint_ref": checkpoint["checkpoint_ref"], "resume_operation_key": resume["operation_key"],
        "new_binding_ref": "binding:new", "new_hermes_run_ref": "run:new",
        "session_run_id": OLD_RUN, "new_session_run_id": NEW_RUN,
    }
    observations[NEW_RUN] = {
        **pm[1], "observation_ref": "observation:new", "status": "running",
        "binding_ref": "binding:new", "hermes_run_ref": "run:new", "fence": 2,
        "dispatch_operation_key": "resume:1", "checkpoint_ref": checkpoint["checkpoint_ref"],
        "session_run_id": NEW_RUN,
    }
    response = client.post(BASE + "/rebind", headers=ADAPTER, json=rebind)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["identity"]["execution_ref"] == pm[1]["execution_ref"]
    assert response.json()["result"]["version"] == 4
    assert response.json()["result"]["resume_delivered"] is True
    assert response.json()["execution_token"] != runtime["X-Workflow-Execution-Token"]
    assert client.post(BASE + "/rebind", headers=ADAPTER, json=rebind).json() == response.json()
    read = client.post(BASE + "/readback", headers=ADAPTER, json={**pm[1], "operation_key": "resume:1"})
    assert read.json()["result"]["operation"]["result"] == reserved.json()["result"]
    assert read.json()["result"]["hermes_run_ref"] == "run:new"
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.PMRun)) == 2
        assert uow.session.scalar(select(func.count()).select_from(m.PMOperation)) == 4
        # Assignment ledger remains immutable; Supervisor resolves the effective run.
        assert uow.session.scalar(select(m.TaskRuntimeAssignment)).hermes_run_ref == resume["hermes_run_ref"]
    step = _step_payload(bound)
    step.update(binding_ref="binding:new", hermes_run_ref="run:new", session_run_id=NEW_RUN)
    assert client.post("/internal/runtime/step", headers=runtime, json=step).status_code == 403
    current_runtime = {**RUNTIME, "X-Workflow-Execution-Token": response.json()["execution_token"]}
    next_step = client.post("/internal/runtime/step", headers=current_runtime, json=step)
    assert next_step.status_code == 200, next_step.text
    # Historic command replay cannot recreate a run or invalidate the current version.
    assert client.post(BASE + "/bind", headers=ADAPTER, json=pm[2]).status_code == 200
    assert client.post(BASE + "/checkpoint", headers=runtime, json=checkpoint).status_code == 200


@pytest.mark.parametrize("field,value", [
    ("execution_ref", "foreign"), ("task_ref", "foreign"), ("root_ref", "foreign"),
    ("tracker_instance_ref", "foreign"), ("tracker_project_ref", "foreign"), ("agent_ref", OTHER_AGENT_REF),
    ("assignment_ref", "foreign"), ("assignment_revision", 2), ("assignment_operation_key", "foreign"),
    ("expected_version", 2), ("expected_fence", 2), ("hermes_run_ref", "foreign"), ("binding_ref", "foreign"),
])
def test_checkpoint_rejects_foreign_or_stale_scope(pm, field, value):
    client, runtime, checkpoint, _, _ = bind_pm(pm)
    response = client.post(BASE + "/checkpoint", headers=runtime, json={**checkpoint, field: value})
    assert response.status_code in {403, 404, 409}
    read = client.post(BASE + "/readback", headers=ADAPTER, json=pm[1])
    assert read.json()["result"]["version"] == 1


@pytest.mark.parametrize("headers", [{}, RUNTIME, ADAPTER, {"Authorization": "Bearer human"}])
def test_checkpoint_requires_both_role_and_execution_credential(pm, headers):
    client, _, checkpoint, _, _ = bind_pm(pm)
    assert client.post(BASE + "/checkpoint", headers=headers, json=checkpoint).status_code in {401, 403}


@pytest.mark.parametrize("field,value", [
    ("checkpoint_ref", "old"), ("clarification_request_ref", "old"),
    ("clarification_version", 2), ("requirements_revision", 2),
    ("expected_version", 1), ("expected_fence", 2),
])
def test_late_answer_cannot_reserve_resume(pm, field, value):
    client, _, _, resume, observations, _ = waiting_pm(pm)
    observations[OLD_RUN]["status"] = "completed"
    assert client.post(BASE + "/resume", headers=ADAPTER, json={**resume, field: value}).status_code == 409


def test_wait_blocks_supervisor_and_late_evaluated_report(pm):
    client, runtime, checkpoint, _, bound = bind_pm(pm)
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("PM-1")
        step = _step_payload(bound)
        args = {key: value for key, value in step.items() if key not in {"task", "report"}}
        fence = TaskService(uow).validate_runtime_step(
            project_id=task.project_id, task_key="PM-1", role_key="project_manager", request_sha256="a" * 64, **args,
        )
        engine = supervisor.SupervisorEngine(
            "PM-1", uow=uow, project_id=task.project_id, create_if_missing=False, runtime_fence=fence,
        )
        assert client.post(BASE + "/checkpoint", headers=runtime, json=checkpoint).status_code == 200
        with pytest.raises(ConflictError):
            engine._lock_runtime_fence()
    assert client.post("/internal/runtime/step", headers=runtime,
                       json={**_step_payload(bound), "session_run_id": OLD_RUN}).status_code == 409
    with SAUnitOfWork() as uow:
        with pytest.raises(ConflictError):
            supervisor.SupervisorEngine("PM-1", uow=uow, project_id=task.project_id, create_if_missing=False)


def test_payload_conflict_unknown_proof_and_missing_capability(pm, monkeypatch):
    client, runtime, checkpoint, resume, observations, _ = waiting_pm(pm)
    changed = client.post(BASE + "/checkpoint", headers=runtime,
                          json={**checkpoint, "clarification_version": 2})
    assert changed.status_code == 409
    with patch.object(pm_readback, "observe_run", side_effect=pm_readback.ReadbackUnavailable("unknown")):
        assert client.post(BASE + "/resume", headers=ADAPTER, json=resume).status_code == 503
    observations[OLD_RUN].update(status="stopped", agent_ref=OTHER_AGENT_REF)
    assert client.post(BASE + "/resume", headers=ADAPTER, json=resume).status_code == 409
    read = client.post(BASE + "/readback", headers=ADAPTER, json={**pm[1], "operation_key": resume["operation_key"]})
    assert read.json()["result"]["operation"] is None
    assert read.json()["result"]["state"] == "waiting"
    assert read.json()["result"]["terminal_readback"] is None
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_URL", "")
    config.get_settings.cache_clear()
    assert client.post(BASE + "/resume", headers=ADAPTER, json=resume).status_code == 503
    assert client.post(BASE + "/readback", headers=ADAPTER, json=pm[1]).status_code == 200


@pytest.mark.parametrize("extra", [{"terminal": True}, {"proof": {"status": "stopped"}}, {"expected_version": True}])
def test_human_terminal_assertions_and_coercion_are_rejected(pm, extra):
    client, runtime, checkpoint, _, _ = bind_pm(pm)
    assert client.post(BASE + "/checkpoint", headers=runtime, json={**checkpoint, **extra}).status_code == 422


def test_runtime_readback_network_contract(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_URL", "http://runtime.test/readback")
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_TOKEN", "p" * 40)
    config.get_settings.cache_clear()
    with patch.object(pm_readback.requests, "get") as get:
        get.return_value.status_code = 302
        with pytest.raises(pm_readback.ReadbackUnavailable):
            pm_readback.observe_run(OLD_RUN)
        assert get.call_args.kwargs["allow_redirects"] is False
        assert get.call_args.kwargs["timeout"] == (3, 10)
        assert get.call_args.args[0] == "http://runtime.test/readback/" + OLD_RUN
        assert "params" not in get.call_args.kwargs
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"status": "stopped"}
        with pytest.raises(pm_readback.ReadbackUnavailable):
            pm_readback.observe_run(OLD_RUN)


def test_openapi_exposes_pm_wire_and_callback_schema(pm):
    schema = pm[0].get("/openapi.json").json()
    assert set(schema["components"]["schemas"]["RuntimeObservation"]["required"]) == {
        *PMIdentity.model_fields, "observation_ref", "binding_ref", "hermes_run_ref", "session_run_id",
        "status", "dispatch_operation_key", "fence",
    }
    for route in ("bind", "checkpoint", "resume", "rebind", "readback"):
        assert "post" in schema["paths"][BASE + "/" + route]
    assert "new_session_run_id" in schema["components"]["schemas"]["PMRebind"]["required"]
    callback = schema["components"]["schemas"]["RuntimeObservation"]
    assert set(callback["properties"]) == {
        "task", "execution_ref", "tracker_instance_ref", "tracker_project_ref", "task_ref", "root_ref", "agent_ref",
        "assignment_operation_key", "assignment_ref", "assignment_revision", "observation_ref", "binding_ref",
        "hermes_run_ref", "session_run_id", "status", "dispatch_operation_key", "checkpoint_ref", "fence",
    }
    assert callback["additionalProperties"] is False
    for name in ("PMIdentity", "PMBind", "PMCheckpoint", "PMResume", "PMRebind", "PMReadback", "RuntimeObservation"):
        assert schema["components"]["schemas"][name]["properties"]["agent_ref"]["pattern"] == (
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        assert schema["components"]["schemas"][name]["properties"]["agent_ref"]["not"] == {
            "const": NIL_FLEET_AGENT_REF,
        }
    runtime_bind = schema["components"]["schemas"]["RuntimeBindRequest"]
    assert "concrete_agent_ref" not in runtime_bind["required"]
    assert runtime_bind["properties"]["concrete_agent_ref"]["anyOf"][0]["pattern"] == (
        callback["properties"]["agent_ref"]["pattern"]
    )
    assert runtime_bind["properties"]["concrete_agent_ref"]["anyOf"][0]["not"] == {
        "const": NIL_FLEET_AGENT_REF,
    }
    assert json.loads(Path(OUTPUT).read_text(encoding="utf-8")) == pm_openapi()


@pytest.mark.parametrize("field,value", [
    ("session_run_id", NEW_RUN), ("execution_ref", "foreign"), ("assignment_ref", "foreign"),
    ("tracker_project_ref", "foreign"), ("fence", 2), ("dispatch_operation_key", "foreign"),
])
def test_raw_runtime_id_alone_never_proves_terminal(pm, field, value):
    client, _, _, resume, observations, _ = waiting_pm(pm)
    observations[OLD_RUN].update(status="stopped", **{field: value})
    assert client.post(BASE + "/resume", headers=ADAPTER, json=resume).status_code == 409


def test_fleet_uuid_is_unique_even_if_runtime_local_run_id_collides(pm):
    client, _, checkpoint, resume, observations, _ = waiting_pm(pm)
    observations[OLD_RUN]["status"] = "stopped"
    reserved = client.post(BASE + "/resume", headers=ADAPTER, json=resume)
    assert reserved.status_code == 200
    # A different runtime can legitimately allocate the same raw Hermes ID.
    observations[NEW_RUN] = {
        **observations[OLD_RUN], "status": "running", "session_run_id": NEW_RUN,
        "dispatch_operation_key": "resume:1", "fence": 2,
        "checkpoint_ref": checkpoint["checkpoint_ref"], "binding_ref": "another-runtime-binding",
    }
    rebind = {
        **pm[1], "operation_key": "rebind:collision", "expected_version": 3, "expected_fence": 2,
        "session_run_id": OLD_RUN, "hermes_run_ref": resume["hermes_run_ref"],
        "binding_ref": resume["binding_ref"], "checkpoint_ref": checkpoint["checkpoint_ref"],
        "resume_operation_key": resume["operation_key"], "new_session_run_id": NEW_RUN,
        "new_binding_ref": "another-runtime-binding", "new_hermes_run_ref": resume["hermes_run_ref"],
    }
    assert client.post(BASE + "/rebind", headers=ADAPTER, json=rebind).status_code == 200
    with SAUnitOfWork() as uow:
        assert len(list(uow.session.scalars(select(m.PMRun)))) == 2
