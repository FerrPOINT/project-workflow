"""Tracker review authority stays distinct from the Workflow sink's real CAS."""

import copy
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from project_workflow import config
from project_workflow.domain.pm_execution import PMDraftAssignment, PMReviewAdmissionContext
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.schemas import SingleTaskPMReviewAssignmentRequest
from tests.test_pm_critical_review import REVIEW_RUN, review_assignment, review_bind
from tests.test_single_task_pm_terminal import CURRENT_RUN, READBACK, complete
from tests.test_single_task_runtime import API, PM, PROFILE, RUNNER, WRITER
from tests.test_single_task_runtime import bridge as bridge


def review_context(revision=8, owner=2):
    return {
        "purpose": "critical_business_review", "tracker_assignment_revision": revision,
        "owner_version": owner, "blocker_id": "22222222-2222-4222-8222-222222222205",
        "blocker_sha256": "c" * 64, "blocker_version": 2,
        "requirements": {"revision": 7, "content_hash": "a" * 64},
    }


def request(revision=8, owner=2):
    result = review_assignment()
    return {**result, "task_revision": 89, "operation_key": f"pm-draft:{result['assignment_ref']}",
            "pm_review_context": review_context(revision, owner)}


def predecessor(client, monkeypatch, supervisor_llm):
    final, lookup, headers, _, _, _ = complete(client, monkeypatch, supervisor_llm)
    saved = client.post(READBACK, json=lookup, headers=headers).json()
    observations = {CURRENT_RUN: pm_readback.observe_run(CURRENT_RUN).model_copy(update={"status": "completed"})}
    monkeypatch.setattr(pm_readback, "observe_run", lambda run: observations[run])
    return final, lookup, headers, saved, observations


def assign_and_bind(client, body):
    response = client.post(API + "assign", json=body, headers=WRITER)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["assignment_revision"] == 1
    assert result["pm_review_context"] == body["pm_review_context"]
    assert client.post(API + "assign", json=body, headers=WRITER).json() == response.json()
    binding, command, observation = review_bind(client, body)
    command.update(assignment_revision=body["pm_review_context"]["tracker_assignment_revision"],
                   workflow_assignment_revision=result["assignment_revision"])
    observation = observation.model_copy(update={"assignment_revision": command["assignment_revision"]})
    return result, binding, command, observation


@pytest.mark.parametrize("revision,owner", [(8, 2), (2, 3)])
def test_review_authority_sink_binding_and_restart_remain_independent(
    bridge, monkeypatch, supervisor_llm, revision, owner,
):
    _, old_lookup, old_headers, old_receipt, observations = predecessor(bridge, monkeypatch, supervisor_llm)
    body = request(revision, owner)
    assert len({body["task_revision"], revision, owner, 1}) == 4
    _, binding, command, observed = assign_and_bind(bridge, body)
    observations[REVIEW_RUN] = observed
    ordinary = {k: v for k, v in command.items() if k != "workflow_assignment_revision"}
    assert bridge.post(PM + "bind", json=ordinary, headers=WRITER).status_code == 409
    assert bridge.post(PM + "bind", json={**command, "workflow_assignment_revision": 2},
                       headers=WRITER).status_code == 409
    assert bridge.post(PM + "bind", json=command, headers=RUNNER).status_code == 403
    bound = bridge.post(PM + "bind", json=command, headers=WRITER)
    assert bound.status_code == 200, bound.text
    assert bound.json()["result"]["identity"]["assignment_revision"] == revision
    assert bridge.post(PM + "bind", json=command, headers=WRITER).json() == bound.json()
    for field in ("assignment_ref", "execution_ref", "root_ref", "agent_ref"):
        changed = {**command, field: str(uuid4())}
        assert bridge.post(PM + "bind", json=changed, headers=WRITER).status_code == 409
    headers = {**RUNNER, "X-Workflow-Execution-Token": bound.json()["execution_token"]}
    step = {**PROFILE, "task": body["task"], "step_operation_key": "review:read",
            "assignment_revision": 1, "assignment_ref": body["assignment_ref"],
            "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
            "mode_key": "draft", "cycle_number": 0, "attempt_number": 1,
            "expected_phase_code": "PM-DRAFT-01", "expected_status": "active", "session_run_id": REVIEW_RUN,
            "single_task_context_sha256": bound.json()["result"]["single_task_context_sha256"]}
    assert bridge.post(API + "step", json=step, headers=headers).status_code == 200
    assert bridge.post(API + "step", json={**step, "assignment_revision": revision}, headers=headers).status_code == 409
    identity = bound.json()["result"]["identity"]
    with TestClient(create_app()) as restarted:
        assert restarted.post(READBACK, json=old_lookup, headers=old_headers).json() == old_receipt
        current = restarted.post(PM + "readback", json={**PROFILE, **identity}, headers=headers)
        assert current.status_code == 200, current.text
        assert current.json()["result"]["identity"]["assignment_revision"] == revision
        replay = restarted.post(API + "assign", json=body, headers=WRITER)
        assert replay.status_code == 200, replay.text
        assert replay.json()["result"]["assignment_revision"] == 1
        assert replay.json()["result"]["pm_review_context"] == body["pm_review_context"]
    with SAUnitOfWork() as uow:
        record = uow.tasks.get_assignment_by_operation_key(body["operation_key"])
        assert record.assignment_revision == 1 and record.payload["pm_review_context"]["owner_version"] == owner
        assert record.payload["single_task_context"]["task_revision"] == 89
        assert record.single_task_binding["context"]["task_revision"] == 89
        assert record.payload["pm_review_context"]["tracker_assignment_revision"] == revision
        assert len(list(uow.session.scalars(select(m.PMExecution)))) == 2


def test_review_checkpoint_resume_and_terminal_use_authoritative_revision(bridge, monkeypatch, supervisor_llm):
    _, _, _, _, observations = predecessor(bridge, monkeypatch, supervisor_llm)
    body = request()
    _, binding, command, observed = assign_and_bind(bridge, body)
    observations[REVIEW_RUN] = observed
    bound = bridge.post(PM + "bind", json=command, headers=WRITER)
    assert bound.status_code == 200, bound.text
    headers = {**RUNNER, "X-Workflow-Execution-Token": bound.json()["execution_token"]}
    step = {**PROFILE, "task": body["task"], "step_operation_key": "review:read",
            "assignment_revision": 1, "assignment_ref": body["assignment_ref"],
            "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
            "mode_key": "draft", "cycle_number": 0, "attempt_number": 1,
            "expected_phase_code": "PM-DRAFT-01", "expected_status": "active", "session_run_id": REVIEW_RUN,
            "single_task_context_sha256": bound.json()["result"]["single_task_context_sha256"]}
    revision = body["pm_review_context"]["tracker_assignment_revision"]
    supervisor_llm("PASS")
    for number in range(2):
        report = {**step, "step_operation_key": f"review:phase:{number}", "report": "Verified review work"}
        response = bridge.post(API + "step", json=report, headers=headers)
        assert response.status_code == 200, response.text
        step["expected_phase_code"] = response.json()["result"]["current_phase_code"]
    identity = bound.json()["result"]["identity"]
    checkpoint = {**PROFILE, **identity, "operation_key": "review:checkpoint", "expected_version": 1,
                  "expected_fence": 1, "binding_ref": binding["binding_ref"],
                  "hermes_run_ref": binding["hermes_run_ref"], "session_run_id": REVIEW_RUN,
                  "checkpoint_ref": str(uuid4()), "requirements_revision": 7, "requirements_sha256": "a" * 64}
    waiting = bridge.post(PM + "checkpoint", json=checkpoint, headers=headers)
    assert waiting.status_code == 200, waiting.text
    assert waiting.json()["result"]["identity"]["assignment_revision"] == revision
    new_run = str(uuid4())
    resume = {**checkpoint, "operation_key": "review:resume", "expected_version": 2,
              "new_session_run_id": new_run, "input": {"input_kind": "confirmation", "input_id": str(uuid4())},
              "input_receipt": {"reference": "tracker:saved-review-confirmation", "sha256": "d" * 64}}
    assert bridge.post(PM + "resume", json=resume, headers=WRITER).status_code == 409
    observations[REVIEW_RUN] = observed.model_copy(update={"status": "stopped",
                                                         "checkpoint_ref": checkpoint["checkpoint_ref"]})
    reserved = bridge.post(PM + "resume", json=resume, headers=WRITER)
    assert reserved.status_code == 200, reserved.text
    assert bridge.post(PM + "resume", json=resume, headers=WRITER).json() == reserved.json()
    observations[new_run] = observed.model_copy(update={
        "session_run_id": new_run, "binding_ref": "binding:review:new", "hermes_run_ref": "run:review:new",
        "fence": 2, "dispatch_operation_key": "review:resume", "checkpoint_ref": checkpoint["checkpoint_ref"],
    })
    rebind = {**PROFILE, **identity, "operation_key": "review:rebind", "expected_version": 3, "expected_fence": 2,
              "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
              "session_run_id": REVIEW_RUN, "checkpoint_ref": checkpoint["checkpoint_ref"],
              "resume_operation_key": "review:resume", "new_binding_ref": "binding:review:new",
              "new_hermes_run_ref": "run:review:new", "new_session_run_id": new_run}
    rebound = bridge.post(PM + "rebind", json=rebind, headers=WRITER)
    assert rebound.status_code == 200, rebound.text
    assert rebound.json()["result"]["identity"] == identity
    new_headers = {**RUNNER, "X-Workflow-Execution-Token": rebound.json()["execution_token"]}
    final = {**step, "step_operation_key": "review:final", "report": "Saved review confirmation and result",
             "session_run_id": new_run, "binding_ref": "binding:review:new", "hermes_run_ref": "run:review:new",
             "single_task_context_sha256": rebound.json()["result"]["single_task_context_sha256"]}
    completed = bridge.post(API + "step", json=final, headers=new_headers)
    assert completed.status_code == 200, completed.text
    assert completed.json()["result"]["complete"] is True
    assert bridge.post(API + "step", json=final, headers=new_headers).json() == completed.json()
    with SAUnitOfWork() as uow:
        record = uow.tasks.get_assignment_by_operation_key(body["operation_key"])
        assert record.assignment_revision == 1 and record.payload["pm_review_context"] == body["pm_review_context"]
        assert len(list(uow.session.scalars(select(m.PMExecution)))) == 2
        assert {row.assignment_revision for row in uow.step_history.list(task_id=record.task_id)} == {1}


@pytest.mark.parametrize("field,value", [
    ("tracker_assignment_revision", 1), ("tracker_assignment_revision", True),
    ("owner_version", 1), ("owner_version", 9007199254740992), ("blocker_version", "2"),
    ("blocker_id", "not-a-uuid"), ("blocker_sha256", "not-a-hash"), ("purpose", "initial"),
    ("requirements", {"revision": 7, "content_hash": "a" * 64, "foreign": True}),
])
def test_review_context_is_closed_and_requires_actual_versions(field, value):
    with pytest.raises(ValidationError):
        PMReviewAdmissionContext.model_validate({**review_context(), field: value})


@pytest.mark.parametrize("changed", [
    {"role_key": "analyst", "workflow_key": "single-task-v1:analyst", "mode_key": "analysis", "stage_key": "Analysis"},
    {"expected_revision": 1}, {"expected_status": "done"}, {"attempt_number": 2}, {"cycle_number": 1},
    {"operation_key": "review:invented"}, {"business_task_ref": "22222222-2222-4222-8222-222222222208"},
])
def test_review_admission_is_only_a_new_single_task_pm_draft(changed):
    with pytest.raises(ValidationError):
        SingleTaskPMReviewAssignmentRequest.model_validate({**request(), **changed})


@pytest.mark.parametrize("failure", ["running", "foreign_fence", "unknown", "unsealed"])
def test_typed_review_still_requires_previous_terminal_and_sealed_history(
    bridge, monkeypatch, supervisor_llm, failure,
):
    final, _, _, _, observations = predecessor(bridge, monkeypatch, supervisor_llm)
    if failure == "unsealed":
        with SAUnitOfWork() as uow:
            entry = uow.step_history.get_by_step_operation_key(final["step_operation_key"])
            row = uow.session.get(m.TaskStepHistoryEntry, entry.id)
            response = json.loads(row.supervisor_response)
            response.pop("workflow_receipt")
            row.supervisor_response = json.dumps(response)
            uow.commit()
    elif failure == "unknown":
        def unavailable(_run):
            raise pm_readback.ReadbackUnavailable("Synthetic unknown")
        monkeypatch.setattr(pm_readback, "observe_run", unavailable)
    else:
        observations[CURRENT_RUN] = observations[CURRENT_RUN].model_copy(update=(
            {"status": "running"} if failure == "running" else {"fence": 99}
        ))
    body = request()
    assert bridge.post(API + "assign", json=body, headers=WRITER).status_code == 409
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_assignment_by_operation_key(body["operation_key"]) is None
        assert len(list(uow.session.scalars(select(m.PMExecution)))) == 1


@pytest.mark.parametrize("corrupt", [None, {}, {**review_context(), "tracker_assignment_revision": 1}])
def test_malformed_saved_review_context_never_falls_back_to_sink_revision(
    bridge, monkeypatch, supervisor_llm, corrupt,
):
    _, _, _, _, observations = predecessor(bridge, monkeypatch, supervisor_llm)
    body = request()
    _, _, command, observed = assign_and_bind(bridge, body)
    observations[REVIEW_RUN] = observed
    assert bridge.post(PM + "bind", json=command, headers=WRITER).status_code == 200
    with SAUnitOfWork() as uow:
        record = uow.tasks.get_assignment_by_operation_key(body["operation_key"])
        row = uow.session.get(m.TaskRuntimeAssignment, record.id)
        payload = json.loads(row.payload)
        payload["pm_review_context"] = corrupt
        row.payload = json.dumps(payload)
        uow.commit()
    identity = {k: command[k] for k in (
        "task", "execution_ref", "tracker_instance_ref", "tracker_project_ref", "task_ref", "root_ref",
        "agent_ref", "assignment_operation_key", "assignment_ref", "assignment_revision",
    )}
    assert bridge.post(PM + "readback", json={**PROFILE, **identity}, headers=WRITER).status_code == 409
    assert bridge.post(PM + "readback", json={**PROFILE, **identity, "assignment_revision": 1},
                       headers=WRITER).status_code == 409


def test_review_context_replay_and_authorization_do_not_accept_changed_receipt(
    bridge, monkeypatch, supervisor_llm,
):
    predecessor(bridge, monkeypatch, supervisor_llm)
    body = request()
    assert bridge.post(API + "assign", json=body, headers=RUNNER).status_code == 403
    assert bridge.post(API + "assign", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "c" * 40)
    config.get_settings.cache_clear()
    assert bridge.post(API + "assign", json=body,
                       headers={"Authorization": "Bearer " + "c" * 40}).status_code == 403
    for changed in ({"tracker_instance_ref": "tracker:foreign"}, {"tracker_project_ref": str(uuid4())}):
        assert bridge.post(API + "assign", json={**body, **changed}, headers=WRITER).status_code == 409
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_assignment_by_operation_key(body["operation_key"]) is None
    assigned = bridge.post(API + "assign", json=body, headers=WRITER)
    assert assigned.status_code == 200, assigned.text
    for field, value in (("owner_version", 3), ("blocker_sha256", "d" * 64),
                         ("requirements", {"revision": 8, "content_hash": "e" * 64})):
        changed = copy.deepcopy(body)
        changed["pm_review_context"][field] = value
        assert bridge.post(API + "assign", json=changed, headers=WRITER).status_code == 409
    assert bridge.post(PM + "assign", json=body, headers=WRITER).status_code == 422
    assert bridge.post(API + "assign", json={**body, "pm_review_context": None}, headers=WRITER).status_code == 422


def test_initial_draft_model_keeps_exact_one_one_and_original_body():
    original = {
        "task": "SDLC-21", "execution_ref": "11111111-1111-4111-8111-111111111111",
        "tracker_instance_ref": "tracker:qa", "tracker_project_ref": "11111111-1111-4111-8111-111111111112",
        "task_ref": "11111111-1111-4111-8111-111111111113", "root_ref": "11111111-1111-4111-8111-111111111113",
        "agent_ref": "11111111-1111-4111-8111-111111111114",
        "assignment_operation_key": "pm-draft:11111111-1111-4111-8111-111111111115",
        "assignment_ref": "11111111-1111-4111-8111-111111111115", "assignment_revision": 1,
        "input_snapshot_ref": "11111111-1111-4111-8111-111111111116", "input_sha256": "a" * 64,
        "owner_version": 1, "runtime_compatibility": {},
    }
    assert PMDraftAssignment.model_validate(original).model_dump_json() == json.dumps(original, separators=(",", ":"))
    for changed in ({"assignment_revision": 2}, {"owner_version": 2}, {"pm_review_context": review_context()}):
        with pytest.raises(ValidationError):
            PMDraftAssignment.model_validate({**original, **changed})
