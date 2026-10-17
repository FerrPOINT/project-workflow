"""PM completion seals reuse the accepted step and typed confirmation ledgers."""

import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from project_workflow.application import single_task_terminal
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.task_step_history import SATaskStepHistoryRepository
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.interfaces.ui.app import create_app
from tests import test_single_task_runtime as runtime_fixture
from tests.test_single_task_runtime import API, PM, PROFILE, RUNNER, SESSION, WRITER, enroll_pm
from tests.test_single_task_runtime import bridge as bridge

READBACK = API + "terminal-receipt/readback"
FIXTURE = Path(__file__).parent / "fixtures" / "single_task_pm_terminal_readback.json"
CHECKPOINT = "11111111-1111-4111-8111-111111111101"
CONFIRMATION = "11111111-1111-4111-8111-111111111102"
CURRENT_RUN = "11111111-1111-4111-8111-111111111103"


def advance(client, monkeypatch, supervisor_llm):
    monkeypatch.setattr(runtime_fixture, "uuid4", lambda: UUID("11111111-1111-4111-8111-111111111104"))
    original_payload = runtime_fixture.assignment_payload

    def fleet_pm_payload():
        payload = original_payload()
        return {**payload, "task": "SDLC-7", "operation_key": f"pm-draft:{payload['assignment_ref']}",
                "exact_input_refs": [{"kind": "pm_draft_input", "ref": "11111111-1111-4111-8111-111111111106",
                                      "hash": "8f09dacd2e9dcd6335b867319edeb40a412b1affb0906fa4f560f4b12ef6cdcf"}]}

    monkeypatch.setattr(runtime_fixture, "assignment_payload", fleet_pm_payload)
    identity, observations, old_headers, step = enroll_pm(client, monkeypatch)
    supervisor_llm("PASS")
    for number in range(2):
        report = {**step, "step_operation_key": f"pm:prepare:{number}", "report": "Verified preparation"}
        response = client.post(API + "step", json=report, headers=old_headers)
        assert response.status_code == 200, response.text
        step["expected_phase_code"] = response.json()["result"]["current_phase_code"]
    checkpoint = {**PROFILE, **identity, "operation_key": "pm:checkpoint", "expected_version": 1,
                  "expected_fence": 1, "binding_ref": step["binding_ref"], "hermes_run_ref": step["hermes_run_ref"],
                  "session_run_id": SESSION, "checkpoint_ref": CHECKPOINT,
                  "requirements_revision": 7, "requirements_sha256": "a" * 64}
    assert client.post(PM + "checkpoint", json=checkpoint, headers=old_headers).status_code == 200
    observations[SESSION].update(status="stopped", checkpoint_ref=CHECKPOINT)
    resumed_input = {"input": {"input_kind": "confirmation", "input_id": CONFIRMATION},
                     "input_receipt": {"reference": "tracker:synthetic-confirmation", "sha256": "b" * 64}}
    resume = {**checkpoint, **resumed_input, "operation_key": "pm:resume", "expected_version": 2,
              "new_session_run_id": CURRENT_RUN}
    reserved = client.post(PM + "resume", json=resume, headers=WRITER)
    assert reserved.status_code == 200, reserved.text
    observations[CURRENT_RUN] = {**identity, "observation_ref": "observed:current", "status": "running",
                                 "binding_ref": "binding:current", "hermes_run_ref": "run:current",
                                 "session_run_id": CURRENT_RUN, "fence": 2,
                                 "dispatch_operation_key": "pm:resume", "checkpoint_ref": CHECKPOINT}
    rebind = {**PROFILE, **identity, "operation_key": "pm:rebind", "expected_version": 3, "expected_fence": 2,
              "binding_ref": step["binding_ref"], "hermes_run_ref": step["hermes_run_ref"], "session_run_id": SESSION,
              "checkpoint_ref": CHECKPOINT, "resume_operation_key": "pm:resume",
              "new_binding_ref": "binding:current", "new_hermes_run_ref": "run:current",
              "new_session_run_id": CURRENT_RUN}
    bound = client.post(PM + "rebind", json=rebind, headers=WRITER)
    assert bound.status_code == 200, bound.text
    final = {**step, "step_operation_key": "pm:final", "report": "Actual confirmed final report",
             "session_run_id": CURRENT_RUN, "binding_ref": "binding:current", "hermes_run_ref": "run:current",
             "single_task_context_sha256": bound.json()["result"]["single_task_context_sha256"]}
    headers = {**RUNNER, "X-Workflow-Execution-Token": bound.json()["execution_token"]}
    lookup = {**PROFILE, "task": final["task"], "step_operation_key": final["step_operation_key"],
              "session_run_id": CURRENT_RUN, "single_task_context_sha256": final["single_task_context_sha256"]}
    return final, lookup, headers, old_headers, resumed_input


def complete(client, monkeypatch, supervisor_llm):
    prepared = advance(client, monkeypatch, supervisor_llm)
    response = client.post(API + "step", json=prepared[0], headers=prepared[2])
    assert response.status_code == 200, response.text
    return (*prepared, response.json())


def test_pm_direct_cli_completion_is_discovered_by_current_run_without_fleet_report_key(
    bridge, monkeypatch, supervisor_llm,
):
    final, lookup, headers, old_headers, _ = advance(bridge, monkeypatch, supervisor_llm)
    by_run = {**{key: value for key, value in lookup.items() if key != "step_operation_key"}, "current_run": True}
    assert bridge.post(READBACK, json=by_run, headers=headers).status_code == 404
    response = bridge.post(API + "step", json=final, headers=headers)
    assert response.status_code == 200
    expected = bridge.post(READBACK, json=lookup, headers=headers).json()
    assert bridge.post(READBACK, json=by_run, headers=headers).json() == expected
    assert bridge.post(READBACK, json=by_run, headers=old_headers).status_code == 403
    for body in [{**by_run, "step_operation_key": "pm:final"},
                 {**by_run, "current_run": "true"}, {**by_run, "current_run": False}]:
        assert bridge.post(READBACK, json=body, headers=headers).status_code == 422
    with TestClient(create_app()) as restarted:
        assert restarted.post(READBACK, json=by_run, headers=headers).json() == expected
    with SAUnitOfWork() as uow:
        source = uow.step_history.get_by_step_operation_key(final["step_operation_key"])
        row = uow.session.get(m.TaskStepHistoryEntry, source.id)
        values = {column.name: getattr(row, column.name) for column in m.TaskStepHistoryEntry.__table__.columns
                  if column.name not in {"id", "created_at"}}
        values.update(step_operation_key="pm:ambiguous-final", replay_fingerprint=None)
        uow.session.add(m.TaskStepHistoryEntry(**values))
        uow.commit()
    assert bridge.post(READBACK, json=by_run, headers=headers).status_code == 409


def test_pm_actual_seal_readback_replay_restart_and_exact_wire_fixture(bridge, monkeypatch, supervisor_llm):
    final, lookup, headers, old_headers, resumed_input, response = complete(bridge, monkeypatch, supervisor_llm)
    artifact = response["result"]["workflow_receipt"]
    receipt = response["result"]["single_task_terminal_receipt"]
    assert artifact == {"reference": receipt["reference"], "sha256": payload_sha256(receipt)}
    pm = receipt["binding"]["pm"]
    assert pm["resume_input"] == resumed_input
    assert pm["checkpoint"]["requirements_revision"] == 7
    assert pm["checkpoint"]["requirements_sha256"] == "a" * 64
    assert pm["session_run_id"] == CURRENT_RUN and pm["execution_version"] == 4 and pm["execution_fence"] == 2
    assert pm["binding_ref"] == receipt["result"]["binding_ref"] == "binding:current"
    assert pm["hermes_run_ref"] == receipt["result"]["hermes_run_ref"] == "run:current"
    assert receipt["binding"]["request"]["session_run_id"] == SESSION != CURRENT_RUN
    assert receipt["binding"]["task_ref"] == receipt["binding"]["root_ref"]
    monkeypatch.setattr(OpenAICompatibleClient, "chat", lambda *_a, **_kw: pytest.fail("No evaluation on read/replay"))
    assert bridge.post(API + "step", json=final, headers=headers).json() == response
    read = bridge.post(READBACK, json=lookup, headers=headers)
    assert read.status_code == 200, read.text
    assert read.headers["Cache-Control"] == "no-store"
    expected = {"ok": True, "complete": True, "workflow_receipt": artifact, "receipt": receipt}
    assert read.json() == expected
    by_reference = {**{k: v for k, v in lookup.items() if k != "step_operation_key"},
                    "receipt_reference": artifact["reference"], "receipt_sha256": artifact["sha256"]}
    assert bridge.post(READBACK, json=by_reference, headers=headers).json() == expected
    assert bridge.post(READBACK, json=lookup, headers=old_headers).status_code == 403
    assert bridge.post(READBACK, json=lookup, headers=WRITER).status_code == 403
    with TestClient(create_app()) as restarted:
        assert restarted.post(READBACK, json=lookup, headers=headers).json() == expected
    captured = {"authority": ("Actual isolated SQLite/TestClient responses; "
                              "synthetic Tracker confirmation/runtime inputs, not live proof."),
                "headers": ["Authorization: Bearer <PM runtime role credential>",
                            "X-Workflow-Execution-Token: <current PM scoped token>"],
                "final_step_request": final, "readback_request": lookup,
                "reference_readback_request": by_reference, "readback_response": expected}
    if os.environ.get("WORKFLOW_UPDATE_PM_TERMINAL_FIXTURE") == "1":
        FIXTURE.write_text(json.dumps(captured, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert captured == json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("failure", ["build", "seal"])
def test_pm_terminal_receipt_failure_rolls_back_final_step_event_and_cursor(
    bridge, monkeypatch, supervisor_llm, failure,
):
    final, lookup, headers, _, _ = advance(bridge, monkeypatch, supervisor_llm)
    with monkeypatch.context() as patcher:
        if failure == "build":
            def broken(*_a, **_kw):
                raise ConflictError("Injected PM receipt build failure")
            patcher.setattr(single_task_terminal, "build_terminal_receipt", broken)
        else:
            original = SATaskStepHistoryRepository.update_supervisor_response

            def broken_seal(self, history_id, response):
                original(self, history_id, response)
                if "workflow_receipt" in response:
                    raise ConflictError("Injected PM seal failure")
            patcher.setattr(SATaskStepHistoryRepository, "update_supervisor_response", broken_seal)
        assert bridge.post(API + "step", json=final, headers=headers).status_code == 409
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key(final["task"])
        assert task.status == "active" and task.current_phase_code == "PM-DRAFT-03"
        assert len(uow.step_history.list(task_id=task.id)) == 2
        assert uow.step_history.get_by_step_operation_key(final["step_operation_key"]) is None
        assert not [event for event in uow.tasks.list_phase_events(task.id)
                    if event.phase_id == task.current_phase_id and event.event_type == "completed"]
    assert bridge.post(READBACK, json=lookup, headers=headers).status_code == 404
    assert bridge.post(API + "step", json=final, headers=headers).json()["result"]["complete"] is True


@pytest.mark.parametrize("mutation", [
    "owner", "missing_owner", "execution", "version", "fence", "run_fence", "checkpoint", "confirmation",
    "resume_operation",
    "body", "artifact", "report", "evaluation", "response", "event", "cursor", "assignment", "unsealed",
])
def test_pm_readback_and_replay_reject_stale_or_tampered_ledgers(bridge, monkeypatch, supervisor_llm, mutation):
    final, lookup, headers, _, _, _ = complete(bridge, monkeypatch, supervisor_llm)
    with SAUnitOfWork() as uow:
        entry = uow.step_history.get_by_step_operation_key(final["step_operation_key"])
        row = uow.session.get(m.TaskStepHistoryEntry, entry.id)
        execution = uow.session.scalar(select(m.PMExecution))
        if mutation == "owner":
            owner = uow.session.scalar(select(m.PMNamespaceOwnership))
            owner.tracker_project_ref = "11111111-1111-4111-8111-111111111105"
        elif mutation == "missing_owner":
            uow.session.delete(uow.session.scalar(select(m.PMNamespaceOwnership)))
        elif mutation == "execution":
            identity = json.loads(execution.identity_json)
            identity["task_ref"] = "11111111-1111-4111-8111-111111111105"
            execution.identity_json = canonical_json(identity)
        elif mutation in {"version", "fence"}:
            setattr(execution, mutation, getattr(execution, mutation) + 1)
        elif mutation == "run_fence":
            uow.session.get(m.PMRun, CURRENT_RUN).fence += 1
        elif mutation in {"checkpoint", "confirmation"}:
            value = json.loads(execution.checkpoint_json)
            if mutation == "checkpoint":
                value["requirements_sha256"] = "c" * 64
            else:
                value["resume_input"]["input"]["input_id"] = "11111111-1111-4111-8111-111111111105"
            execution.checkpoint_json = canonical_json(value)
        elif mutation == "resume_operation":
            operation = uow.session.get(m.PMOperation, execution.resume_operation_key)
            value = json.loads(operation.result_json)
            value["resume_input"]["input_receipt"]["sha256"] = "c" * 64
            operation.result_json = canonical_json(value)
        elif mutation in {"body", "artifact", "response", "unsealed"}:
            value = dict(entry.supervisor_response)
            if mutation == "body":
                value["single_task_terminal_receipt"]["binding"]["pm"]["execution_fence"] += 1
            elif mutation == "artifact":
                value["workflow_receipt"]["sha256"] = "0" * 64
            elif mutation == "response":
                value["message"] = "Changed PM accepted response"
            else:
                value.pop("workflow_receipt")
                value.pop("single_task_terminal_receipt")
                evaluation = dict(entry.evaluation_snapshot)
                evaluation.pop("contract_fingerprint_state")
                row.evaluation_snapshot = canonical_json(evaluation)
            uow.step_history.update_supervisor_response(entry.id, value)
        elif mutation == "report":
            row.worker_report = "Changed PM report"
        elif mutation == "evaluation":
            value = dict(entry.evaluation_snapshot)
            value["covered_item_ids"] = []
            row.evaluation_snapshot = canonical_json(value)
        elif mutation == "event":
            event = uow.session.scalar(select(m.TaskPhaseEvent).where(
                m.TaskPhaseEvent.step_history_id == entry.id, m.TaskPhaseEvent.event_type == "completed"))
            uow.session.delete(event)
        else:
            task = uow.session.get(m.Task, entry.task_id)
            if mutation == "cursor":
                task.status = "active"
            else:
                task.assignment_revision += 1
    statuses = {409} if mutation == "unsealed" else {403, 409}
    assert bridge.post(READBACK, json=lookup, headers=headers).status_code in statuses
    assert bridge.post(API + "step", json=final, headers=headers).status_code in statuses
    with SAUnitOfWork() as uow:
        assert len(uow.step_history.list(task_id=uow.tasks.get_by_key(final["task"]).id)) == 3
