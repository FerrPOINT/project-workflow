"""Real isolated ledgers; native/Tracker readbacks are synthetic, never live."""

import json
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from project_workflow.application.pm_bootstrap import (
    BootstrapProof,
    BootstrapRetry,
    PMBootstrapService,
)
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.pm_execution import RuntimeObservation
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.routes import pm_bootstrap_api
from tests import test_single_task_runtime as runtime
from tests.test_single_task_runtime import API, PM, PROFILE, SESSION, WRITER
from tests.test_single_task_runtime import bridge as bridge

NEXT = "22222222-2222-4222-8222-222222222211"


@pytest.fixture
def pending(bridge, monkeypatch):
    assignment, binding, step, headers = runtime.prepare(bridge, monkeypatch, "project_manager", "draft", "Draft")
    with SAUnitOfWork() as uow:
        project = uow.projects.get_by_cli_command("workflow-single-task-project-manager")
        uow.projects.create_pm_ownership({
            "contract_version": 1, "ownership_ref": NEXT, "namespace_id": project.id,
            "tracker_instance_ref": assignment["tracker_instance_ref"],
            "tracker_project_ref": assignment["tracker_project_ref"], "authority_issuer": "http://auth.test",
            "provisioner_subject": assignment["concrete_agent_ref"],
        })
        state = PMBootstrapService(uow).predecessor(project.id, assignment["task"], assignment["operation_key"], 1)
    native = RuntimeObservation.model_validate({
        "task": assignment["task"], "execution_ref": assignment["execution_ref"],
        "tracker_instance_ref": assignment["tracker_instance_ref"],
        "tracker_project_ref": assignment["tracker_project_ref"], "task_ref": assignment["business_task_ref"],
        "root_ref": assignment["root_task_ref"], "agent_ref": assignment["concrete_agent_ref"],
        "assignment_operation_key": assignment["operation_key"], "assignment_ref": assignment["assignment_ref"],
        "assignment_revision": 1, "observation_ref": "observed:original", "status": "failed",
        "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
        "session_run_id": SESSION, "dispatch_operation_key": "pm:original-bind", "fence": 1,
    })
    proof = BootstrapProof(
        predecessor_sha256=state["sha256"], bootstrap_attempt_ref=NEXT, native=native,
        current_context=state["context"], assignment_ref=assignment["assignment_ref"],
        predecessor_owner_version=1, owner_version=1, original_operations="settled", business_result="absent",
    )
    monkeypatch.setattr(pm_readback, "observe_run", lambda _run: native)
    return {"project": project.id, "assignment": assignment, "binding": binding, "step": step,
            "headers": headers, "state": state, "proof": proof, "client": bridge}


def command(fixture, proof=None, **changes):
    proof = proof or fixture["proof"]
    return BootstrapRetry.model_validate({
        "predecessor_operation_key": fixture["assignment"]["operation_key"],
        "predecessor_sha256": fixture["state"]["sha256"], "operation_key": "pm-bootstrap:" + NEXT,
        "bootstrap_attempt_ref": NEXT, "proof_sha256": payload_sha256(proof.model_dump()), **changes,
    })


def retry(fixture, request=None, reader=None):
    with SAUnitOfWork() as uow:
        return PMBootstrapService(uow).retry(
            fixture["project"], fixture["assignment"]["task"], request or command(fixture),
            reader or (lambda _request: fixture["proof"]),
        )


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "stopped"])
def test_retry_preserves_canonical_identity_and_original_bytes_then_requires_running_bind(pending, monkeypatch, status):
    old = pending["proof"].native
    proof = pending["proof"].model_copy(update={"native": old.model_copy(update={"status": status})})
    monkeypatch.setattr(pm_readback, "observe_run", lambda _run: proof.native)
    with SAUnitOfWork() as uow:
        original = uow.tasks.get_assignment_by_operation_key(old.assignment_operation_key).to_dict()
    request = command(pending, proof)
    result = retry(pending, request, lambda _: proof)
    assert result["assignment_revision"] == 2 and result["attempt_number"] == 2
    assert result["binding_state"] == "unbound" and result["status"] == "active"
    assert result["assignment_ref"] == old.assignment_ref and result["task_key"] == old.task
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_assignment_by_operation_key(old.assignment_operation_key).to_dict() == original
        assert list(uow.session.scalars(select(m.PMExecution))) == []
    monkeypatch.setattr(pm_readback, "observe_run", Mock(side_effect=AssertionError("Replay is read-only")))
    replayed = retry(pending, request, Mock(side_effect=AssertionError("No new composite on replay")))
    # SQLite reload drops timezone metadata on the unrelated projection timestamp.
    assert {k: v for k, v in replayed.items() if k != "updated_at"} == {
        k: v for k, v in result.items() if k != "updated_at"
    }
    with pytest.raises(ConflictError, match="key/body conflict"):
        retry(pending, request.model_copy(update={"proof_sha256": "0" * 64}))
    old_command = {**PROFILE, **old.model_dump(include={
        "task", "execution_ref", "tracker_instance_ref", "tracker_project_ref", "task_ref", "root_ref",
        "agent_ref", "assignment_operation_key", "assignment_ref", "assignment_revision",
        "binding_ref", "hermes_run_ref", "session_run_id",
    }), "operation_key": old.dispatch_operation_key, "expected_version": 0}
    monkeypatch.setattr(pm_readback, "observe_run", lambda _: old.model_copy(update={"status": "running"}))
    late_bind = pending["client"].post(PM + "bind", json=old_command, headers=WRITER)
    assert late_bind.status_code == 409, late_bind.text
    binding = {**pending["binding"], "assignment_operation_key": request.operation_key,
               "assignment_revision": 2, "attempt_number": 2, "bind_operation_key": "bind:retry",
               "binding_ref": "binding:retry", "hermes_run_ref": "run:retry", "session_run_id": NEXT}
    bound = pending["client"].post(API + "bind", json=binding, headers=WRITER)
    assert bound.status_code == 200, bound.text
    identity = {**old.model_dump(include={
        "task", "execution_ref", "tracker_instance_ref", "tracker_project_ref", "task_ref", "root_ref",
        "agent_ref", "assignment_operation_key", "assignment_ref", "assignment_revision",
    }), "assignment_operation_key": request.operation_key}
    pm_command = {**PROFILE, **identity, "operation_key": "pm:retry-bind", "expected_version": 0,
                  "binding_ref": "binding:retry", "hermes_run_ref": "run:retry", "session_run_id": NEXT}
    new_native = old.model_copy(update={**identity, "binding_ref": "binding:retry", "hermes_run_ref": "run:retry",
                                        "session_run_id": NEXT, "dispatch_operation_key": "pm:retry-bind"})
    monkeypatch.setattr(pm_readback, "observe_run", lambda _run: new_native)
    assert pending["client"].post(PM + "bind", json=pm_command, headers=WRITER).status_code == 409
    monkeypatch.setattr(pm_readback, "observe_run", lambda _run: new_native.model_copy(update={"status": "running"}))
    enrolled = pending["client"].post(PM + "bind", json=pm_command, headers=WRITER)
    assert enrolled.status_code == 200, enrolled.text
    assert enrolled.json()["result"]["identity"]["assignment_revision"] == 1
    stale = pending["client"].post(API + "step", json=pending["step"], headers=pending["headers"])
    assert stale.status_code in {403, 409}
    next_step = {**pending["step"], "assignment_revision": 2, "attempt_number": 2,
                 "step_operation_key": "step:retry-read", "binding_ref": "binding:retry",
                 "hermes_run_ref": "run:retry", "session_run_id": NEXT,
                 "single_task_context_sha256": enrolled.json()["result"]["single_task_context_sha256"]}
    next_headers = {**runtime.RUNNER, "X-Workflow-Execution-Token": enrolled.json()["execution_token"]}
    first = pending["client"].post(API + "step", json=next_step, headers=next_headers)
    assert first.status_code == 200, first.text
    assert first.json()["result"]["phase_code"] == "PM-DRAFT-01"


@pytest.mark.parametrize("change", [
    {"owner_version": 2}, {"assignment_ref": NEXT},
])
def test_changed_canonical_authority_is_not_a_bootstrap_retry(pending, change):
    proof = pending["proof"].model_copy(update=change)
    with pytest.raises(ConflictError):
        retry(pending, command(pending, proof), lambda _: proof)
    with SAUnitOfWork() as uow:
        assert len(uow.tasks.list_assignments(pending["state"]["task_id"])) == 1


@pytest.mark.parametrize("change", [{"status": "running"}, {"fence": 2}, {"session_run_id": NEXT}])
def test_native_readback_mismatch_or_nonterminal_refuses_retry(pending, monkeypatch, change):
    monkeypatch.setattr(pm_readback, "observe_run", lambda _: pending["proof"].native.model_copy(update=change))
    with pytest.raises(ConflictError, match="terminal"):
        retry(pending)


@pytest.mark.parametrize("durable", ["event", "step", "phase"])
def test_durable_progress_invalidates_predecessor_digest(pending, durable):
    with SAUnitOfWork() as uow:
        task = uow.session.get(m.Task, pending["state"]["task_id"])
        if durable == "event":
            uow.tasks.record_phase_event(task.id, task.current_phase_id, "blocked")
        elif durable == "phase":
            phases = uow.phases.list(workflow_id=task.workflow_id, mode_id=task.mode_id)
            task.current_phase_id = phases[1].id
        else:
            uow.step_history.create({
                "task_id": task.id, "phase_id": task.current_phase_id, "verdict": "blocked",
                "worker_report": "Synthetic retained history", "covered_item_ids": [], "missing_item_ids": [],
                "blocker_messages": [], "evaluation_snapshot": {}, "supervisor_response": {},
            })
        uow.commit()
    with pytest.raises(ConflictError, match="fence differs"):
        retry(pending)


def test_enrollment_winning_during_composite_read_is_rechecked_under_task_lock(pending, monkeypatch):
    native = pending["proof"].native

    def read(_request):
        command = {**PROFILE, **native.model_dump(include={
            "task", "execution_ref", "tracker_instance_ref", "tracker_project_ref", "task_ref", "root_ref",
            "agent_ref", "assignment_operation_key", "assignment_ref", "assignment_revision",
            "binding_ref", "hermes_run_ref", "session_run_id",
        }), "operation_key": native.dispatch_operation_key, "expected_version": 0}
        monkeypatch.setattr(pm_readback, "observe_run", lambda _: native.model_copy(update={"status": "running"}))
        enrolled = pending["client"].post(PM + "bind", json=command, headers=WRITER)
        assert enrolled.status_code == 200, enrolled.text
        monkeypatch.setattr(pm_readback, "observe_run", lambda _: native)
        return pending["proof"]

    with pytest.raises(ConflictError, match="fence differs"):
        retry(pending, reader=read)
    with SAUnitOfWork() as uow:
        assert len(uow.tasks.list_assignments(pending["state"]["task_id"])) == 1
        assert len(list(uow.session.scalars(select(m.PMExecution)))) == 1


def test_reader_requires_existing_assignment_credential_and_never_returns_empty_on_timeout(pending, monkeypatch):
    args = {"task": pending["assignment"]["task"], "assignment_operation_key": pending["assignment"]["operation_key"],
            "assignment_revision": 1}
    for auth, expected in ((WRITER["Authorization"], 200), (runtime.RUNNER["Authorization"], 403),
                           ("Bearer unknown", 401)):
        response = pm_bootstrap_api.predecessor(**args, authorization=auth)
        assert response.status_code == expected
        assert response.headers["cache-control"] == "no-store"
        if expected == 200:
            assert json.loads(response.body)["result"] == pending["state"]
    unavailable = Mock(side_effect=OperationalError("secret", {}, Exception()))
    monkeypatch.setattr(PMBootstrapService, "predecessor", unavailable)
    response = pm_bootstrap_api.predecessor(**args, authorization=WRITER["Authorization"])
    assert response.status_code == 503 and "result" not in json.loads(response.body)
    assert b"secret" not in response.body


def test_boolean_or_unavailable_composite_is_not_authority(pending):
    with pytest.raises(ConflictError, match="proof required"):
        retry(pending, reader=lambda _: True)
    with pytest.raises(pm_readback.ReadbackUnavailable):
        retry(pending, reader=Mock(side_effect=pm_readback.ReadbackUnavailable("Unknown original effect")))


def test_competing_successor_and_partial_insert_never_publish(pending, monkeypatch):
    with pytest.raises(RuntimeError, match="Synthetic CAS failure"), SAUnitOfWork() as uow:
        monkeypatch.setattr(uow.tasks, "update", Mock(side_effect=RuntimeError("Synthetic CAS failure")))
        PMBootstrapService(uow).retry(pending["project"], pending["assignment"]["task"], command(pending),
                                      lambda _: pending["proof"])
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_assignment_by_operation_key(command(pending).operation_key) is None
    retry(pending)
    request = command(pending, operation_key="pm-bootstrap:competitor")
    with pytest.raises(ConflictError, match="current initial PM"):
        retry(pending, request)
    with SAUnitOfWork() as uow:
        assert len(uow.tasks.list_assignments(pending["state"]["task_id"])) == 2


def test_reader_distinguishes_actual_unbound_assignment_from_unknown(pending):
    assignment = {**pending["assignment"], "task": "RUN-8", "operation_key": "assignment:unbound",
                  "assignment_ref": NEXT, "execution_ref": NEXT}
    assigned = pending["client"].post(API + "assign", json=assignment, headers=WRITER)
    assert assigned.status_code == 200, assigned.text
    with SAUnitOfWork() as uow:
        state = PMBootstrapService(uow).predecessor(pending["project"], "RUN-8", "assignment:unbound", 1)
        assert state["binding"] is None and state["pm_enrolled"] is False and state["step_state"] == "absent"
        with pytest.raises(ConflictError, match="revision differs"):
            PMBootstrapService(uow).predecessor(pending["project"], "RUN-8", "assignment:unbound", 2)
