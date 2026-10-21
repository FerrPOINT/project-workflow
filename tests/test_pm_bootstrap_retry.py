"""Real isolated ledgers; native/Tracker readbacks are synthetic, never live."""

import json
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from project_workflow import config
from project_workflow.application.pm_bootstrap import (
    BootstrapProof,
    BootstrapRetry,
    PMBootstrapService,
    canonical_assignment,
)
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.pm_execution import RuntimeObservation
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.routes import pm_bootstrap_api
from tests import test_single_task_runtime as runtime
from tests.test_single_task_pm_terminal import CHECKPOINT, CONFIRMATION, CURRENT_RUN, READBACK
from tests.test_single_task_runtime import API, PM, PROFILE, SESSION, WRITER
from tests.test_single_task_runtime import bridge as bridge

NEXT = "22222222-2222-4222-8222-222222222211"


@pytest.fixture
def pending(bridge, monkeypatch, request):
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"project_manager": "w" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"project_manager": "r" * 40}))
    config.get_settings.cache_clear()
    assignment = {**runtime.assignment_payload(), "task": "SDLC-7", "role_key": "project_manager",
                  "workflow_key": "single-task-v1:project_manager", "mode_key": "draft", "stage_key": "Draft",
                  "execution_scope": "business", "cycle_number": 0}
    assignment["operation_key"] = f"pm-draft:{assignment['assignment_ref']}"
    assigned = bridge.post(API + "assign", json=assignment, headers=WRITER)
    assert assigned.status_code == 200, assigned.text
    binding = {**PROFILE, "task": assignment["task"], "bind_operation_key": "bind:1",
               "assignment_operation_key": assignment["operation_key"], "assignment_revision": 1,
               "assignment_ref": assignment["assignment_ref"], "binding_ref": "binding:1", "hermes_run_ref": "run:1",
               "mode_key": "draft", "cycle_number": 0, "attempt_number": 1, "expected_binding_state": "unbound",
               "concrete_agent_ref": assignment["concrete_agent_ref"], "session_run_id": SESSION}
    step = {**PROFILE, "task": assignment["task"], "step_operation_key": "step:read",
            "assignment_revision": 1, "assignment_ref": assignment["assignment_ref"],
            "binding_ref": "binding:1", "hermes_run_ref": "run:1", "mode_key": "draft", "cycle_number": 0,
            "attempt_number": 1, "expected_phase_code": assigned.json()["result"]["current_phase_code"],
            "expected_status": "active", "session_run_id": SESSION, "single_task_context_sha256": "0" * 64}
    headers = runtime.RUNNER
    if getattr(request, "param", "bound") == "bound":
        bound = bridge.post(API + "bind", json=binding, headers=WRITER)
        assert bound.status_code == 200, bound.text
        step["single_task_context_sha256"] = bound.json()["result"]["single_task_context_sha256"]
        headers = {**runtime.RUNNER, "X-Workflow-Execution-Token": bound.json()["execution_token"]}
    with SAUnitOfWork() as uow:
        project = uow.projects.get_by_cli_command("workflow-single-task-project-manager")
        uow.projects.create_pm_ownership({
            "contract_version": 1, "ownership_ref": NEXT, "namespace_id": project.id,
            "tracker_instance_ref": assignment["tracker_instance_ref"],
            "tracker_project_ref": assignment["tracker_project_ref"], "authority_issuer": "http://auth.test",
            "provisioner_subject": assignment["concrete_agent_ref"],
        })
        state = PMBootstrapService(uow).predecessor(project.id, assignment["task"], assignment["operation_key"], 1)
        record = uow.tasks.get_assignment_by_operation_key(assignment["operation_key"])
        assert state["bind_request_sha256"] == record.bind_request_sha256
        assert state["initial_phase_id"] == state["current_phase_id"]
        if state["binding"] is not None:
            assert state["bind_request_sha256"] == payload_sha256(state["binding"])
        else:
            assert state["bind_request_sha256"] is None
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


def enroll_retry(pending, monkeypatch, status="failed"):
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
    late_generic = pending["client"].post(API + "bind", json=pending["binding"], headers=WRITER)
    assert late_generic.status_code == 409, late_generic.text
    binding = {**pending["binding"], "assignment_operation_key": request.operation_key,
               "assignment_revision": 2, "attempt_number": 2, "bind_operation_key": "bind:retry",
               "binding_ref": "binding:retry", "hermes_run_ref": "run:retry", "session_run_id": NEXT}
    bound = pending["client"].post(API + "bind", json=binding, headers=WRITER)
    assert bound.status_code == 200, bound.text
    identity = old.model_dump(include={
        "task", "execution_ref", "tracker_instance_ref", "tracker_project_ref", "task_ref", "root_ref",
        "agent_ref", "assignment_operation_key", "assignment_ref", "assignment_revision",
    })
    pm_command = {**PROFILE, **identity, "operation_key": "pm:retry-bind", "expected_version": 0,
                  "binding_ref": "binding:retry", "hermes_run_ref": "run:retry", "session_run_id": NEXT}
    new_native = old.model_copy(update={**identity, "binding_ref": "binding:retry", "hermes_run_ref": "run:retry",
                                        "session_run_id": NEXT, "dispatch_operation_key": "pm:retry-bind"})
    monkeypatch.setattr(pm_readback, "observe_run", lambda _run: new_native)
    assert pending["client"].post(PM + "bind", json=pm_command, headers=WRITER).status_code == 409
    monkeypatch.setattr(pm_readback, "observe_run", lambda _run: new_native.model_copy(update={"status": "running"}))
    for wrong_key in (request.operation_key, "pm-draft:" + NEXT):
        wrong = {**pm_command, "assignment_operation_key": wrong_key}
        assert pending["client"].post(PM + "bind", json=wrong, headers=WRITER).status_code == 409
    enrolled = pending["client"].post(PM + "bind", json=pm_command, headers=WRITER)
    assert enrolled.status_code == 200, enrolled.text
    assert enrolled.json()["result"]["identity"]["assignment_revision"] == 1
    assert enrolled.json()["result"]["identity"]["assignment_operation_key"] == old.assignment_operation_key
    read = pending["client"].post(PM + "readback", json={**PROFILE, **identity}, headers=WRITER)
    assert read.status_code == 200, read.text
    assert read.json()["result"] == {**enrolled.json()["result"], "operation": None}
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
    return identity, new_native, pm_command, next_step, next_headers


@pytest.mark.parametrize("pending", ["bound", "unbound"], indirect=True)
@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "stopped"])
def test_retry_preserves_canonical_identity_and_original_bytes_then_requires_running_bind(pending, monkeypatch, status):
    enroll_retry(pending, monkeypatch, status)


@pytest.mark.parametrize("pending", ["bound", "unbound"], indirect=True)
def test_canonical_root_survives_local_retry_through_confirmed_terminal_readback(pending, monkeypatch, supervisor_llm):
    identity, native, command, step, headers = enroll_retry(pending, monkeypatch)
    child_key = "pm-bootstrap:" + NEXT
    observations = {NEXT: native.model_copy(update={"status": "running"})}
    monkeypatch.setattr(pm_readback, "observe_run", lambda run: observations[run])
    client = pending["client"]
    supervisor_llm("PASS")
    for number in range(2):
        report = {**step, "step_operation_key": f"pm:retry-prepare:{number}", "report": "Verified preparation"}
        response = client.post(API + "step", json=report, headers=headers)
        assert response.status_code == 200, response.text
        step["expected_phase_code"] = response.json()["result"]["current_phase_code"]
    checkpoint = {**command, "operation_key": "pm:retry-checkpoint", "expected_version": 1, "expected_fence": 1,
                  "checkpoint_ref": CHECKPOINT, "requirements_revision": 7, "requirements_sha256": "a" * 64}
    response = client.post(PM + "checkpoint", json=checkpoint, headers=headers)
    assert response.status_code == 200, response.text
    observations[NEXT] = native.model_copy(update={"status": "stopped", "checkpoint_ref": CHECKPOINT})
    confirmation = {"input": {"input_kind": "confirmation", "input_id": CONFIRMATION},
                    "input_receipt": {"reference": "tracker:synthetic-confirmation", "sha256": "b" * 64}}
    resumed = {**checkpoint, **confirmation, "operation_key": "pm:retry-resume", "expected_version": 2,
               "new_session_run_id": CURRENT_RUN}
    response = client.post(PM + "resume", json=resumed, headers=WRITER)
    assert response.status_code == 200, response.text
    observations[CURRENT_RUN] = native.model_copy(update={
        "observation_ref": "observed:confirmed", "status": "running", "binding_ref": "binding:confirmed",
        "hermes_run_ref": "run:confirmed", "session_run_id": CURRENT_RUN, "fence": 2,
        "dispatch_operation_key": "pm:retry-resume", "checkpoint_ref": CHECKPOINT,
    })
    rebind = {**PROFILE, **identity, "operation_key": "pm:retry-rebind", "expected_version": 3, "expected_fence": 2,
              "binding_ref": step["binding_ref"], "hermes_run_ref": step["hermes_run_ref"], "session_run_id": NEXT,
              "checkpoint_ref": CHECKPOINT, "resume_operation_key": "pm:retry-resume",
              "new_binding_ref": "binding:confirmed", "new_hermes_run_ref": "run:confirmed",
              "new_session_run_id": CURRENT_RUN}
    bound = client.post(PM + "rebind", json=rebind, headers=WRITER)
    assert bound.status_code == 200, bound.text
    final = {**step, "step_operation_key": "pm:retry-final", "report": "Actual confirmed final report",
             "session_run_id": CURRENT_RUN, "binding_ref": "binding:confirmed", "hermes_run_ref": "run:confirmed",
             "single_task_context_sha256": bound.json()["result"]["single_task_context_sha256"]}
    current_headers = {**runtime.RUNNER, "X-Workflow-Execution-Token": bound.json()["execution_token"]}
    finished = client.post(API + "step", json=final, headers=current_headers)
    assert finished.status_code == 200, finished.text
    receipt = finished.json()["result"]["single_task_terminal_receipt"]
    assert receipt["binding"]["pm"]["identity"] == identity == observations[CURRENT_RUN].model_dump(
        include=set(identity),
    )
    assert identity["assignment_operation_key"] == pending["assignment"]["operation_key"]
    assert identity["assignment_revision"] == 1
    assert receipt["binding"]["request"]["assignment_operation_key"] == child_key
    assert receipt["binding"]["request"]["assignment_revision"] == receipt["result"]["assignment_revision"] == 2
    assert receipt["result"]["assignment_operation_key"] == child_key
    lookup = {**PROFILE, "task": final["task"], "current_run": True, "session_run_id": CURRENT_RUN,
              "single_task_context_sha256": final["single_task_context_sha256"]}
    read = client.post(READBACK, json=lookup, headers=current_headers)
    assert read.status_code == 200, read.text
    assert read.json()["receipt"] == receipt
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_id(pending["state"]["task_id"])
        assert task.status == "done" and task.assignment_operation_key == child_key
        rows = uow.step_history.list(task_id=task.id)
        assert len(rows) == 3 and all(entry.assignment_operation_key == child_key for entry in rows)


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


@pytest.mark.parametrize("pending", ["unbound"], indirect=True)
@pytest.mark.parametrize("field", [
    "binding_ref", "hermes_run_ref", "bind_operation_key", "bind_request_sha256", "concrete_agent_ref",
])
def test_unbound_retry_never_falls_back_from_partial_custody(pending, field):
    with SAUnitOfWork() as uow:
        record = uow.tasks.get_assignment_by_operation_key(pending["assignment"]["operation_key"]).to_dict()
        # The DB already rejects incomplete binding columns. Also fail closed on
        # any partial reader projection, without disabling that physical guard.
        record[field] = "a" * 64 if field == "bind_request_sha256" else NEXT
        task = uow.session.get(m.Task, pending["state"]["task_id"])
        with pytest.raises(ConflictError, match="Partial or changed"):
            PMBootstrapService(uow)._snapshot(task, record)


@pytest.mark.parametrize("pending", ["unbound"], indirect=True)
def test_original_generic_bind_winning_before_successor_invalidates_absent_snapshot(pending):
    def read(_request):
        response = pending["client"].post(API + "bind", json=pending["binding"], headers=WRITER)
        assert response.status_code == 200, response.text
        return pending["proof"]

    with pytest.raises(ConflictError, match="fence differs"):
        retry(pending, reader=read)
    with SAUnitOfWork() as uow:
        assert len(uow.tasks.list_assignments(pending["state"]["task_id"])) == 1


def test_second_bootstrap_resolves_retained_root_not_previous_local_key(pending, monkeypatch):
    retry(pending)
    first_key = command(pending).operation_key
    with SAUnitOfWork() as uow:
        state = PMBootstrapService(uow).predecessor(pending["project"], pending["assignment"]["task"], first_key, 2)
    native = pending["proof"].native.model_copy(update={
        "binding_ref": "binding:second-original", "hermes_run_ref": "run:second-original", "session_run_id": NEXT,
        "dispatch_operation_key": "pm:second-original",
    })
    proof = pending["proof"].model_copy(update={
        "predecessor_sha256": state["sha256"], "bootstrap_attempt_ref": CURRENT_RUN, "native": native,
    })
    request = command(pending, proof, predecessor_operation_key=first_key, predecessor_sha256=state["sha256"],
                      operation_key="pm-bootstrap:second", bootstrap_attempt_ref=CURRENT_RUN)
    monkeypatch.setattr(pm_readback, "observe_run", lambda _: native)
    result = retry(pending, request, lambda _: proof)
    assert result["assignment_revision"] == result["attempt_number"] == 3
    binding = {**pending["binding"], "assignment_operation_key": request.operation_key, "assignment_revision": 3,
               "attempt_number": 3, "bind_operation_key": "bind:second", "binding_ref": "binding:second",
               "hermes_run_ref": "run:second", "session_run_id": CURRENT_RUN}
    bound = pending["client"].post(API + "bind", json=binding, headers=WRITER)
    assert bound.status_code == 200, bound.text
    identity = native.model_dump(include={
        "task", "execution_ref", "tracker_instance_ref", "tracker_project_ref", "task_ref", "root_ref",
        "agent_ref", "assignment_operation_key", "assignment_ref", "assignment_revision",
    })
    pm_command = {**PROFILE, **identity, "expected_version": 0, "operation_key": "pm:second-bind",
                  "binding_ref": "binding:second", "hermes_run_ref": "run:second", "session_run_id": CURRENT_RUN}
    monkeypatch.setattr(pm_readback, "observe_run", lambda _: native.model_copy(update={
        "status": "running", "binding_ref": "binding:second", "hermes_run_ref": "run:second",
        "session_run_id": CURRENT_RUN, "dispatch_operation_key": "pm:second-bind",
    }))
    for key in (first_key, request.operation_key):
        assert pending["client"].post(
            PM + "bind", json={**pm_command, "assignment_operation_key": key}, headers=WRITER,
        ).status_code == 409
    enrolled = pending["client"].post(PM + "bind", json=pm_command, headers=WRITER)
    assert enrolled.status_code == 200, enrolled.text
    assert enrolled.json()["result"]["identity"] == identity


@pytest.mark.parametrize("field,value", [
    ("canonical_assignment_operation_key", "pm-bootstrap:" + NEXT),
    ("canonical_assignment_revision", 2),
    ("predecessor_payload_sha256", "0" * 64),
])
def test_mapping_cannot_rebind_canonical_authority_even_with_recomputed_child_hash(pending, field, value):
    retry(pending)
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
            m.TaskRuntimeAssignment.operation_key == command(pending).operation_key,
        ))
        payload = json.loads(row.payload)
        payload["pm_bootstrap_context"][field] = value
        row.payload = canonical_json(payload)
        row.payload_sha256 = payload_sha256(payload)
        uow.session.flush()
        record = uow.tasks.get_assignment_by_operation_key(row.operation_key).to_dict()
        with pytest.raises(ConflictError):
            canonical_assignment(uow, record)
