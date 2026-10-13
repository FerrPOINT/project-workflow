"""Generic continuation cannot replace an immutable enrolled PM assignment."""

import json

import pytest
from sqlalchemy import func, select

from project_workflow.application.pm_execution import PMExecutionService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.pm_execution import PMBind
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_pm_execution import ADAPTER, BASE, OLD_RUN, bind_pm, prepare_pm, waiting_pm
from tests.test_runtime_api import _bind_payload
from tests.test_runtime_assignment_contract import _continuation


@pytest.fixture
def pm(monkeypatch):
    yield from prepare_pm(monkeypatch)


def continuation(bound):
    """Synthetic test checkpoint, not a receipt for a live PM draft."""
    return _continuation(
        bound, operation_key="continue:PM-1:1", next_assignment_ref="assignment:PM-1:continued",
        workspace_generation=bound["workspace_generation"],
        lease_generation=bound["lease_generation"] + 1,
        tech_execution_workspace_ref=None, tech_execution_attempt_ref=None,
        exact_input_refs=[*bound["exact_input_refs"], {
            "kind": "business-phase-checkpoint", "ref": "receipt:DEV-1:oldrun",
            "revision": "oldrun", "hash": "a" * 64,
        }],
    )


def persisted_state():
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("PM-1")
        return (
            task.assignment_revision, task.assignment_operation_key, task.current_phase_id, task.status,
            [event.to_dict() for event in uow.tasks.list_phase_events(task.id)],
            tuple(uow.session.scalar(select(func.count()).select_from(model)) for model in (
                m.TaskRuntimeAssignment, m.TaskStepHistoryEntry, m.PMExecution, m.PMRun, m.PMOperation,
            )),
        )


@pytest.mark.parametrize("pm_state", ["active", "waiting", "resume_pending"])
@pytest.mark.parametrize("task_status", ["active", "blocked", "done"])
def test_enrolled_pm_rejects_generic_without_cursor_history_or_ledger_mutation(pm, pm_state, task_status):
    if pm_state == "active":
        bind_pm(pm)
    else:
        client, _, _, resume, observations, _ = waiting_pm(pm)
        if pm_state == "resume_pending":
            observations[OLD_RUN]["status"] = "stopped"
            response = client.post(BASE + "/resume", headers=ADAPTER, json=resume)
            assert response.status_code == 200, response.text
    with SAUnitOfWork() as uow:
        uow.session.scalar(select(m.Task).where(m.Task.task_key == "PM-1")).status = task_status
    before = persisted_state()
    response = pm[0].post("/internal/runtime/rebind", headers=ADAPTER, json=continuation(pm[4]))
    assert response.status_code == 409, response.text
    assert "Enrolled PM assignment requires PM resume/rebind" in response.text
    assert persisted_state() == before


def test_generic_denial_leaves_pm_specific_resume_valid(pm):
    from tests.test_pm_execution import test_wait_resume_new_run_survives_sessions_and_replays as verify_resume

    bind_pm(pm)
    assert pm[0].post("/internal/runtime/rebind", headers=ADAPTER,
                      json=continuation(pm[4])).status_code == 409
    verify_resume(pm)


def test_exact_generic_historical_readback_after_enrollment_is_side_effect_free(pm):
    client, identity, bind, observations, bound = pm
    request = continuation(bound)
    response = client.post("/internal/runtime/rebind", headers=ADAPTER, json=request)
    assert response.status_code == 200, response.text
    prepared = response.json()["result"]
    binding = _bind_payload(prepared)
    binding.update(concrete_agent_ref=identity["agent_ref"], binding_ref=request["next_binding_ref"],
                   hermes_run_ref=request["next_hermes_run_ref"])
    response = client.post("/internal/runtime/bind", headers=ADAPTER, json=binding)
    assert response.status_code == 200, response.text
    continued = response.json()["result"]
    identity.update(assignment_operation_key=continued["assignment_operation_key"],
                    assignment_ref=continued["assignment_ref"], assignment_revision=continued["assignment_revision"])
    bind.update(identity, binding_ref=binding["binding_ref"], hermes_run_ref=binding["hermes_run_ref"])
    observations[OLD_RUN].update(identity, binding_ref=binding["binding_ref"], hermes_run_ref=binding["hermes_run_ref"])
    bind_pm(pm)
    before = persisted_state()
    replay = client.post("/internal/runtime/rebind", headers=ADAPTER, json=request)
    assert replay.status_code == 200, replay.text
    assert replay.json()["result"] == continued
    assert persisted_state() == before
    denied = client.post("/internal/runtime/rebind", headers=ADAPTER, json={
        **continuation(continued), "operation_key": "continue:PM-1:2",
    })
    assert denied.status_code == 409, denied.text
    assert persisted_state() == before


@pytest.mark.parametrize("change", ["missing", "drift", "catalog_v1"])
def test_pm_bind_rejects_incompatible_frozen_assignment_before_runtime_probe(pm, monkeypatch, change):
    probes = []
    monkeypatch.setattr(pm_readback, "observe_run", lambda run: probes.append(run))
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskRuntimeAssignment))
        payload = json.loads(row.payload)
        if change == "catalog_v1":
            row.mode.catalog_version = 1
        elif change == "missing":
            payload.pop("runtime_compatibility")
        else:
            payload["runtime_compatibility"]["catalogSha256"] = "f" * 64
        row.payload = json.dumps(payload)
    before = persisted_state()
    with SAUnitOfWork() as uow:
        project_id = uow.tasks.get_by_key("PM-1").project_id
        with pytest.raises(ConflictError, match="RUNTIME_VERSION_INCOMPATIBLE"):
            PMExecutionService(uow).bind(PMBind.model_validate(pm[2]), project_id)
    response = pm[0].post(BASE + "/bind", headers=ADAPTER, json=pm[2])
    assert response.status_code == 409, response.text
    assert probes == []
    assert persisted_state() == before
