"""Concrete Fleet identity comes from the protected runtime binding ledger."""

from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from project_workflow.application.task import TaskService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import NIL_FLEET_AGENT_REF, payload_sha256
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_pm_execution import (
    ADAPTER,
    AGENT_REF,
    BASE,
    NEW_RUN,
    OLD_RUN,
    OTHER_AGENT_REF,
    RUNTIME,
    bind_pm,
    prepare_pm,
    waiting_pm,
)
from tests.test_runtime_api import _assignment, _bind_payload, _step_payload


@pytest.fixture
def pm(monkeypatch):
    yield from prepare_pm(monkeypatch)


def test_mapping_is_persisted_separately_from_catalog_and_bind_replay_is_immutable(pm):
    client, identity, _, _, bound = pm
    payload = {**_bind_payload(bound), "concrete_agent_ref": AGENT_REF}
    replay = client.post("/internal/runtime/bind", headers=ADAPTER, json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["result"] == bound
    assert bound["concrete_agent_ref"] == identity["agent_ref"] == AGENT_REF
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskRuntimeAssignment))
        task = uow.session.get(m.Task, row.task_id)
        phase = uow.session.get(m.Phase, task.current_phase_id)
        assert uow.session.get(m.Agent, phase.agent_id).name == "project_manager"
        assert uow.tasks.get_assignment_by_operation_key(row.operation_key).concrete_agent_ref == AGENT_REF
        digest_payload = {key: value for key, value in payload.items() if key != "task"}
        digest_payload.update(project_id=row.project_id, task_key=payload["task"], role_key="project_manager")
        assert row.bind_request_sha256 == payload_sha256(digest_payload)
    for changes in (
        {"concrete_agent_ref": OTHER_AGENT_REF}, {"concrete_agent_ref": None},
        {"bind_operation_key": "bind:replacement", "concrete_agent_ref": OTHER_AGENT_REF},
    ):
        assert client.post("/internal/runtime/bind", headers=ADAPTER,
                           json={**payload, **changes}).status_code == 409
    assert client.post("/internal/runtime/bind", headers=RUNTIME,
                       json={**payload, "concrete_agent_ref": OTHER_AGENT_REF}).status_code == 403
    assert client.post("/internal/runtime/bind", headers=ADAPTER, json=payload).json() == replay.json()


@pytest.mark.parametrize("value", [None, "project_manager", AGENT_REF.upper(), " " + AGENT_REF,
                                       AGENT_REF + " ", "a" * 32, "g" + AGENT_REF[1:], 42, {}, NIL_FLEET_AGENT_REF])
def test_pm_and_runtime_bind_reject_noncanonical_agent_uuid(pm, value):
    client, _, command, _, bound = pm
    assert client.post(BASE + "/bind", headers=ADAPTER,
                       json={**command, "agent_ref": value}).status_code == 422
    status = 409 if value is None else 422
    assert client.post("/internal/runtime/bind", headers=ADAPTER, json={
        **_bind_payload(bound), "concrete_agent_ref": value,
    }).status_code == status
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("PM-1")
        with pytest.raises(ValueError if value is not None else ConflictError):
            TaskService(uow).bind_runtime_assignment(
                project_id=task.project_id, task_key="PM-1", role_key="project_manager",
                **{key: val for key, val in _bind_payload(bound).items() if key != "task"},
                concrete_agent_ref=value,
            )


def test_pm_runtime_bind_requires_mapping_before_any_execution(pm):
    client = pm[0]
    assignment = client.post("/internal/runtime/assign", headers=ADAPTER,
                             json=_assignment("PM-2", "assign:pm:2", "project_manager")).json()["result"]
    payload = _bind_payload(assignment)
    assert client.post("/internal/runtime/bind", headers=ADAPTER, json=payload).status_code == 409
    assert client.post("/internal/runtime/bind", headers=ADAPTER,
                       json={**payload, "concrete_agent_ref": AGENT_REF}).status_code == 200


def test_authorized_legacy_adoption_can_persist_mapping_once(pm):
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskRuntimeAssignment))
        row.bind_operation_key = row.bind_request_sha256 = row.concrete_agent_ref = None
    payload = {**_bind_payload(pm[4]), "concrete_agent_ref": AGENT_REF, "expected_binding_state": "legacy_bound"}
    assert pm[0].post("/internal/runtime/bind", headers=ADAPTER, json=payload).status_code == 200
    assert pm[0].post("/internal/runtime/bind", headers=ADAPTER, json=payload).status_code == 200
    bind_pm(pm)


def test_pm_caller_and_callback_cannot_substitute_the_persisted_mapping(pm):
    client, _, command, observations, _ = pm
    observations[OLD_RUN]["agent_ref"] = OTHER_AGENT_REF
    with patch.object(pm_readback, "observe_run") as observe:
        response = client.post(BASE + "/bind", headers=ADAPTER,
                               json={**command, "agent_ref": OTHER_AGENT_REF})
        assert response.status_code == 409
        observe.assert_not_called()
    assert client.post(BASE + "/bind", headers=ADAPTER, json=command).status_code == 409
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.PMExecution)) == 0


@pytest.mark.parametrize("mapping", [None, OTHER_AGENT_REF, NIL_FLEET_AGENT_REF])
def test_pm_initial_bind_fails_closed_with_missing_or_mismatched_mapping(pm, mapping):
    with SAUnitOfWork() as uow:
        uow.session.scalar(select(m.TaskRuntimeAssignment)).concrete_agent_ref = mapping
    with patch.object(pm_readback, "observe_run") as observe:
        assert pm[0].post(BASE + "/bind", headers=ADAPTER, json=pm[2]).status_code == 409
        observe.assert_not_called()
    assert pm[0].post("/internal/runtime/step", headers=RUNTIME,
                      json=_step_payload(pm[4])).status_code == 409


def test_changed_mapping_cannot_be_legitimized_by_matching_caller_and_callback(pm):
    with SAUnitOfWork() as uow:
        uow.session.scalar(select(m.TaskRuntimeAssignment)).concrete_agent_ref = OTHER_AGENT_REF
    pm[3][OLD_RUN]["agent_ref"] = OTHER_AGENT_REF
    with patch.object(pm_readback, "observe_run") as observe:
        assert pm[0].post(BASE + "/bind", headers=ADAPTER,
                          json={**pm[2], "agent_ref": OTHER_AGENT_REF}).status_code == 409
        observe.assert_not_called()


@pytest.mark.parametrize("mapping", [None, OTHER_AGENT_REF, NIL_FLEET_AGENT_REF])
def test_changed_mapping_fences_checkpoint_readback_supervisor_and_replays(pm, mapping):
    client, runtime, checkpoint, _, bound = bind_pm(pm)
    with SAUnitOfWork() as uow:
        uow.session.scalar(select(m.TaskRuntimeAssignment)).concrete_agent_ref = mapping
    for route, command in (("bind", pm[2]), ("checkpoint", checkpoint), ("readback", pm[1])):
        headers = runtime if route == "checkpoint" else ADAPTER
        assert client.post(BASE + "/" + route, headers=headers, json=command).status_code == 409
    assert client.post("/internal/runtime/step", headers=runtime,
                       json={**_step_payload(bound), "session_run_id": OLD_RUN}).status_code == 409
    assert client.get("/internal/runtime/history", headers=runtime,
                      params={"task": "PM-1", "session_run_id": OLD_RUN}).status_code == 409
    with SAUnitOfWork() as uow:
        execution = uow.session.scalar(select(m.PMExecution))
        assert (execution.state, execution.version, execution.fence) == ("active", 1, 1)
        assert uow.session.scalar(select(func.count()).select_from(m.PMOperation)) == 1


@pytest.mark.parametrize("mapping", [None, OTHER_AGENT_REF, NIL_FLEET_AGENT_REF])
def test_resume_rechecks_mapping_before_trusted_terminal_probe(pm, mapping):
    client, _, _, resume, _, _ = waiting_pm(pm)
    with SAUnitOfWork() as uow:
        uow.session.scalar(select(m.TaskRuntimeAssignment)).concrete_agent_ref = mapping
    with patch.object(pm_readback, "observe_run") as observe:
        assert client.post(BASE + "/resume", headers=ADAPTER, json=resume).status_code == 409
        observe.assert_not_called()
    with SAUnitOfWork() as uow:
        execution = uow.session.scalar(select(m.PMExecution))
        assert (execution.state, execution.version, execution.fence) == ("waiting", 2, 1)
        assert execution.resume_session_run_id is None


def test_resumed_callback_cannot_move_execution_to_another_concrete_agent(pm):
    client, _, checkpoint, resume, observations, _ = waiting_pm(pm)
    observations[OLD_RUN]["status"] = "stopped"
    assert client.post(BASE + "/resume", headers=ADAPTER, json=resume).status_code == 200
    observations[NEW_RUN] = {
        **observations[OLD_RUN], "status": "running", "session_run_id": NEW_RUN,
        "dispatch_operation_key": resume["operation_key"], "fence": 2,
        "checkpoint_ref": checkpoint["checkpoint_ref"], "binding_ref": "binding:new",
        "hermes_run_ref": "run:new", "agent_ref": OTHER_AGENT_REF,
    }
    rebind = {
        **pm[1], "operation_key": "rebind:agent", "expected_version": 3, "expected_fence": 2,
        "session_run_id": OLD_RUN, "binding_ref": resume["binding_ref"], "hermes_run_ref": resume["hermes_run_ref"],
        "checkpoint_ref": checkpoint["checkpoint_ref"], "resume_operation_key": resume["operation_key"],
        "new_session_run_id": NEW_RUN, "new_binding_ref": "binding:new", "new_hermes_run_ref": "run:new",
    }
    assert client.post(BASE + "/rebind", headers=ADAPTER, json=rebind).status_code == 409
    read = client.post(BASE + "/readback", headers=ADAPTER, json=pm[1]).json()["result"]
    assert read["state"] == "resume_pending"
    assert read["identity"]["agent_ref"] == AGENT_REF
    observations[NEW_RUN]["agent_ref"] = AGENT_REF
    assert client.post(BASE + "/rebind", headers=ADAPTER, json=rebind).status_code == 200
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(m.TaskRuntimeAssignment)).concrete_agent_ref == AGENT_REF
