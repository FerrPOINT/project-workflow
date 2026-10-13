"""Opt-in bridge execution and typed continuation with real SQLite ledgers."""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from project_workflow import config
from project_workflow.application.pm_execution import PMExecutionService
from project_workflow.domain.pm_execution import RuntimeObservation
from project_workflow.domain.single_task_profile import MANIFEST_SHA256, ROLE_MODES
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests.test_single_task_installation import assignment_payload

API = "/internal/runtime/"
PM = API + "v1/pm/"
WRITER = {"Authorization": "Bearer " + "w" * 40}
RUNNER = {"Authorization": "Bearer " + "r" * 40}
SESSION = "ffffffff-ffff-4fff-8fff-ffffffffffff"
PROFILE = {"instruction_profile": "single-task-v1", "instruction_manifest_sha256": MANIFEST_SHA256}


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr(config, "CATALOG_VARIANT", "single-task-v1")
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_SCOPE_SECRET", "s" * 40)
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_TOKEN", "p" * 40)
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_URL", "http://runtime.test/readback")
    with SAUnitOfWork() as uow:
        ensure_single_task_catalog(uow)
    with TestClient(create_app()) as client:
        yield client


def prepare(client, monkeypatch, role="developer", mode="initial", stage="Development", tech_pair=None):
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({role: "w" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({role: "r" * 40}))
    config.get_settings.cache_clear()
    assignment = {**assignment_payload(), "role_key": role, "workflow_key": "single-task-v1:" + role,
                  "mode_key": mode, "stage_key": stage,
                  "execution_scope": ROLE_MODES[role][mode][0]}
    if tech_pair is not None:
        assignment.update(tech_execution_workspace_ref=tech_pair[0], tech_execution_attempt_ref=tech_pair[1])
    response = client.post(API + "assign", json=assignment, headers=WRITER)
    assert response.status_code == 200, response.text
    assert client.post(API + "assign", json=assignment, headers=WRITER).json() == response.json()
    accepted = response.json()["result"]
    bind = {**PROFILE, "task": assignment["task"], "bind_operation_key": "bind:1",
            "assignment_operation_key": assignment["operation_key"], "assignment_revision": 1,
            "assignment_ref": assignment["assignment_ref"], "binding_ref": "binding:1", "hermes_run_ref": "run:1",
            "mode_key": mode, "cycle_number": 0, "attempt_number": 1, "expected_binding_state": "unbound",
            "concrete_agent_ref": assignment["concrete_agent_ref"], "session_run_id": SESSION}
    response = client.post(API + "bind", json=bind, headers=WRITER)
    assert response.status_code == 200, response.text
    assert client.post(API + "bind", json=bind, headers=WRITER).json() == response.json()
    bound = response.json()
    step = {**PROFILE, "task": assignment["task"], "step_operation_key": "step:read",
            "assignment_revision": 1, "assignment_ref": assignment["assignment_ref"],
            "binding_ref": bind["binding_ref"], "hermes_run_ref": bind["hermes_run_ref"], "mode_key": mode,
            "cycle_number": 0, "attempt_number": 1, "expected_phase_code": accepted["current_phase_code"],
            "expected_status": "active", "session_run_id": SESSION,
            "single_task_context_sha256": bound["result"]["single_task_context_sha256"]}
    headers = {**RUNNER, "X-Workflow-Execution-Token": bound["execution_token"]}
    return assignment, bind, step, headers


@pytest.mark.parametrize("role,mode,stage", [
    ("analyst", "analysis", "Analysis"), ("architect", "decomposition", "Architecture"),
    ("developer", "initial", "Development"), ("developer", "rework", "Rework"),
    ("reviewer", "delivery", "Review"), ("tester", "delivery", "Testing"), ("devops", "delivery", "Deployment"),
])
def test_profile_executes_three_phases_replays_and_reads_history(
    bridge, monkeypatch, supervisor_llm, role, mode, stage,
):
    assignment, bind, step, headers = prepare(bridge, monkeypatch, role, mode, stage)
    read = bridge.post(API + "step", json=step, headers=headers)
    assert read.status_code == 200, read.text
    assert bridge.post(API + "step", json=step, headers=RUNNER).status_code == 403
    assert bridge.post(API + "step", json={**step, "session_run_id": str(uuid4())}, headers=headers).status_code == 409
    assert bridge.post(API + "step", json={**step, "single_task_context_sha256": "0" * 64},
                       headers=headers).status_code == 409
    supervisor_llm("PASS")
    for number in range(3):
        report = {**step, "step_operation_key": f"step:report:{number}", "report": f"Verified phase {number}"}
        result = bridge.post(API + "step", json=report, headers=headers)
        assert result.status_code == 200, result.text
        assert bridge.post(API + "step", json=report, headers=headers).json() == result.json()
        with SAUnitOfWork() as uow:
            task = uow.tasks.get_by_key(assignment["task"])
            step["expected_phase_code"] = task.current_phase_code
        if number == 2:
            assert result.json()["result"]["complete"] is True
    params = {**PROFILE, "task": assignment["task"], "session_run_id": SESSION}
    history = bridge.get(API + "history", params=params, headers=headers)
    assert history.status_code == 200, history.text
    assert history.json()["result"]["count"] == 3
    assert bridge.get(API + "history", params=params, headers=RUNNER).status_code == 403
    with SAUnitOfWork() as uow:
        record = uow.tasks.get_assignment_by_operation_key(assignment["operation_key"])
        assert record.payload["single_task_context"]["lease_version"] == assignment["lease_version"]
        assert record.single_task_binding["request"]["session_run_id"] == SESSION
        assert record.decomposition_revision_ref is record.queue_item_ref is record.task_workspace_ref is None
        for entry in uow.step_history.list(task_id=record.task_id):
            assert entry.evaluation_snapshot["single_task_context_sha256"] == step["single_task_context_sha256"]


def enroll_pm(client, monkeypatch):
    assignment, binding, step, _ = prepare(client, monkeypatch, "project_manager", "draft", "Draft")
    with SAUnitOfWork() as uow:
        project = uow.projects.get_by_cli_command("workflow-single-task-project-manager")
        uow.projects.create_pm_ownership({
            "contract_version": 1, "ownership_ref": str(uuid4()), "namespace_id": project.id,
            "tracker_instance_ref": assignment["tracker_instance_ref"],
            "tracker_project_ref": assignment["tracker_project_ref"], "authority_issuer": "http://auth.test",
            "provisioner_subject": str(uuid4()),
        })
    identity = {"task": assignment["task"], "execution_ref": assignment["execution_ref"],
                "tracker_instance_ref": assignment["tracker_instance_ref"],
                "tracker_project_ref": assignment["tracker_project_ref"], "task_ref": assignment["business_task_ref"],
                "root_ref": assignment["root_task_ref"], "agent_ref": assignment["concrete_agent_ref"],
                "assignment_operation_key": assignment["operation_key"], "assignment_ref": assignment["assignment_ref"],
                "assignment_revision": 1}
    observations = {SESSION: {**identity, "observation_ref": "observed:1", "status": "running",
                             "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
                             "dispatch_operation_key": "pm:bind", "fence": 1, "session_run_id": SESSION}}
    monkeypatch.setattr(pm_readback, "observe_run", lambda run: RuntimeObservation.model_validate(observations[run]))
    result = client.post(PM + "bind", headers=WRITER, json={**PROFILE, **identity, "operation_key": "pm:bind",
                         "expected_version": 0, "binding_ref": binding["binding_ref"],
                         "hermes_run_ref": binding["hermes_run_ref"], "session_run_id": SESSION})
    assert result.status_code == 200, result.text
    headers = {**RUNNER, "X-Workflow-Execution-Token": result.json()["execution_token"]}
    step["single_task_context_sha256"] = result.json()["result"]["single_task_context_sha256"]
    return identity, observations, headers, step


@pytest.mark.parametrize("kind", ["answer", "feedback", "confirmation"])
def test_typed_pm_resume_keeps_execution_and_real_receipt(bridge, monkeypatch, supervisor_llm, kind):
    identity, observations, headers, step = enroll_pm(bridge, monkeypatch)
    supervisor_llm("PASS")
    for number in range(2):
        report = {**step, "step_operation_key": f"pm:phase:{number}", "report": "Verified preparation"}
        result = bridge.post(API + "step", json=report, headers=headers)
        assert result.status_code == 200, result.text
        assert bridge.post(API + "step", json=report, headers=headers).json() == result.json()
        step["expected_phase_code"] = result.json()["result"]["current_phase_code"]
    assert step["expected_phase_code"] == "PM-DRAFT-03"
    assert bridge.post(API + "step", json={**step, "report": "Premature", "step_operation_key": "pm:final"},
                       headers=headers).status_code == 409
    checkpoint = {**PROFILE, **identity, "operation_key": "pm:checkpoint", "expected_version": 1,
                  "expected_fence": 1, "binding_ref": step["binding_ref"], "hermes_run_ref": step["hermes_run_ref"],
                  "session_run_id": SESSION, "checkpoint_ref": str(uuid4()),
                  "requirements_revision": 7, "requirements_sha256": "a" * 64}
    if kind == "answer":
        checkpoint.update(clarification_request_ref="question:real", clarification_version=1)
    waiting = bridge.post(PM + "checkpoint", json=checkpoint, headers=headers)
    assert waiting.status_code == 200, waiting.text
    assert waiting.json()["result"]["workflow_step_allowed"] is False
    assert bridge.post(API + "step", json=step, headers=headers).status_code == 409
    new_run = str(uuid4())
    resume = {**checkpoint, "operation_key": "pm:resume", "expected_version": 2, "new_session_run_id": new_run,
              "input": {"input_kind": kind, "input_id": str(uuid4())},
              "input_receipt": {"reference": "tracker:actual-receipt", "sha256": "b" * 64}}
    assert bridge.post(PM + "resume", json=resume, headers=RUNNER).status_code == 403
    assert bridge.post(PM + "resume", json=resume, headers=WRITER).status_code == 409
    observations[SESSION].update(status="stopped", checkpoint_ref=checkpoint["checkpoint_ref"])
    stale = {**resume, "requirements_sha256": "c" * 64}
    assert bridge.post(PM + "resume", json=stale, headers=WRITER).status_code == 409
    if kind != "answer":
        assert bridge.post(PM + "resume", json={**resume, "answer_event_ref": "fake"},
                           headers=WRITER).status_code == 422
    reserved = bridge.post(PM + "resume", json=resume, headers=WRITER)
    assert reserved.status_code == 200, reserved.text
    assert bridge.post(PM + "resume", json=resume, headers=WRITER).json() == reserved.json()
    changed = {**resume, "input_receipt": {"reference": "tracker:other", "sha256": "b" * 64}}
    assert bridge.post(PM + "resume", json=changed, headers=WRITER).status_code == 409
    readback = bridge.post(PM + "readback", json={**PROFILE, **identity, "operation_key": "pm:resume"}, headers=WRITER)
    assert readback.status_code == 200, readback.text
    assert readback.json()["result"]["resume_input"]["input"] == resume["input"]
    assert readback.json()["result"]["resume_input"]["input_receipt"] == resume["input_receipt"]
    observations[new_run] = {**identity, "observation_ref": "observed:new", "status": "running",
                             "binding_ref": "binding:new", "hermes_run_ref": "run:new", "session_run_id": new_run,
                             "fence": 2, "dispatch_operation_key": "pm:resume",
                             "checkpoint_ref": checkpoint["checkpoint_ref"]}
    rebind = {**PROFILE, **identity, "operation_key": "pm:rebind", "expected_version": 3, "expected_fence": 2,
              "binding_ref": step["binding_ref"], "hermes_run_ref": step["hermes_run_ref"], "session_run_id": SESSION,
              "checkpoint_ref": checkpoint["checkpoint_ref"], "resume_operation_key": "pm:resume",
              "new_binding_ref": "binding:new", "new_hermes_run_ref": "run:new", "new_session_run_id": new_run}
    rebound = bridge.post(PM + "rebind", json=rebind, headers=WRITER)
    assert rebound.status_code == 200, rebound.text
    assert rebound.json()["result"]["identity"] == identity
    assert rebound.json()["result"]["single_task_context_sha256"] != step["single_task_context_sha256"]
    new_step = {**step, "step_operation_key": "pm:final", "report": "Actual confirmed final report",
                "session_run_id": new_run, "binding_ref": "binding:new", "hermes_run_ref": "run:new",
                "single_task_context_sha256": rebound.json()["result"]["single_task_context_sha256"]}
    new_headers = {**RUNNER, "X-Workflow-Execution-Token": rebound.json()["execution_token"]}
    final = bridge.post(API + "step", json=new_step, headers=new_headers)
    assert final.status_code == (200 if kind == "confirmation" else 409), final.text
    if kind == "confirmation":
        assert final.json()["result"]["complete"] is True
        assert bridge.post(API + "step", json=new_step, headers=new_headers).json() == final.json()
    next_checkpoint = {**checkpoint, "operation_key": "pm:checkpoint:new", "expected_version": 4,
                       "expected_fence": 2, "session_run_id": new_run, "binding_ref": "binding:new",
                       "hermes_run_ref": "run:new", "checkpoint_ref": str(uuid4()),
                       "requirements_revision": 8, "requirements_sha256": "d" * 64}
    next_wait = bridge.post(PM + "checkpoint", json=next_checkpoint, headers=new_headers)
    assert next_wait.status_code == (409 if kind == "confirmation" else 200), next_wait.text
    if kind != "confirmation":
        stale_consent = {**resume, **next_checkpoint, "operation_key": "pm:old-consent", "expected_version": 5,
                         "requirements_revision": 7, "requirements_sha256": "a" * 64,
                         "new_session_run_id": str(uuid4())}
        assert bridge.post(PM + "resume", json=stale_consent, headers=WRITER).status_code == 409
    with SAUnitOfWork() as uow:
        assert len(uow.tasks.list_assignments(uow.tasks.get_by_key(identity["task"]).id)) == 1
        execution = uow.session.scalar(select(m.PMExecution))
        assert execution.execution_ref == identity["execution_ref"]
        snapshot = PMExecutionService(uow).snapshot(execution)
        if kind == "confirmation":
            assert snapshot["resume_input"]["input"]["input_kind"] == kind
        else:
            assert "resume_input" not in snapshot
    assert bridge.post(API + "step", json=step, headers=headers).status_code in {403, 409}


def test_public_profile_contract_is_additive_and_has_no_base_or_routing_inputs(bridge):
    schemas = bridge.get("/openapi.json").json()["components"]["schemas"]
    single = schemas["SingleTaskAssignmentRequest"]
    for forbidden in ("base_admission", "decomposition_revision_ref", "queue_item_ref", "work_item_ref",
                      "task_workspace_ref", "workspace_revision", "routing_snapshot", "observed_owner", "lease_expiry"):
        assert forbidden not in single["properties"]
    assert single["additionalProperties"] is False
    assert "input" in schemas["SingleTaskPMResume"]["required"]
    assert "input_receipt" in schemas["SingleTaskPMResume"]["required"]
    assert "answer_event_ref" not in schemas["SingleTaskPMResume"]["properties"]
    assert "answer_event_ref" in schemas["PMResume"]["required"]
    assert schemas["PMTypedInput"]["properties"]["input_kind"]["enum"] == ["answer", "feedback", "confirmation"]
    assert schemas["PMTypedInput"]["additionalProperties"] is False
    assert "single_task_context_sha256" in schemas["SingleTaskStepRequest"]["required"]
    assert "single_task_context_sha256" not in schemas["RuntimeStepRequest"]["properties"]


def test_installed_drift_and_binding_tampering_fail_before_evaluation(bridge, monkeypatch, supervisor_llm):
    assignment, _, step, headers = prepare(bridge, monkeypatch)
    supervisor_llm("PASS")
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
            m.TaskRuntimeAssignment.operation_key == assignment["operation_key"]))
        original = row.single_task_binding_json
        binding = json.loads(original)
        binding["request"]["session_run_id"] = str(uuid4())
        row.single_task_binding_json = json.dumps(binding)
    assert bridge.post(API + "step", json=step, headers=headers).status_code == 409
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskRuntimeAssignment))
        row.single_task_binding_json = original
        phase = uow.phases.get_by_id(uow.tasks.get_by_id(row.task_id).current_phase_id)
        instruction = uow.phase_instructions.list(phase.id)[0]
        uow.phase_instructions.update(instruction["id"], {"description": "Drift"})
    response = bridge.post(API + "step", json={**step, "report": "Not admitted"}, headers=headers)
    assert response.status_code == 409, response.text
    with SAUnitOfWork() as uow:
        assert not uow.step_history.list(task_id=row.task_id)


@pytest.mark.parametrize("changes", [
    {"decomposition_revision_ref": "fake"}, {"queue_item_ref": "fake"},
    {"root_task_ref": "99999999-9999-4999-8999-999999999999"},
    {"execution_scope": "aggregate"}, {"execution_scope": None},
    {"tech_execution_workspace_ref": "workspace-without-attempt"},
])
def test_single_task_sql_branch_does_not_accept_legacy_resources_or_partial_context(bridge, monkeypatch, changes):
    assignment, _, _, _ = prepare(bridge, monkeypatch)
    with pytest.raises(IntegrityError), SAUnitOfWork() as uow:
        uow.session.execute(m.TaskRuntimeAssignment.__table__.update().where(
            m.TaskRuntimeAssignment.operation_key == assignment["operation_key"]).values(**changes))


def test_delivery_can_retain_real_tech_workspace_pair_without_decomposition(bridge, monkeypatch):
    pair = (str(uuid4()), str(uuid4()))
    assignment, _, step, headers = prepare(bridge, monkeypatch, tech_pair=pair)
    assert bridge.post(API + "step", json=step, headers=headers).status_code == 200
    with SAUnitOfWork() as uow:
        record = uow.tasks.get_assignment_by_operation_key(assignment["operation_key"])
        assert (record.tech_execution_workspace_ref, record.tech_execution_attempt_ref) == pair
        assert record.task_workspace_ref is record.decomposition_revision_ref is None


def test_pm_brainstorming_checkpoints_and_resumes_feedback_before_any_requirements(bridge, monkeypatch):
    identity, observations, headers, step = enroll_pm(bridge, monkeypatch)
    checkpoint = {**PROFILE, **identity, "operation_key": "brainstorm:checkpoint", "expected_version": 1,
                  "expected_fence": 1, "binding_ref": step["binding_ref"], "hermes_run_ref": step["hermes_run_ref"],
                  "session_run_id": SESSION, "checkpoint_ref": str(uuid4()),
                  "requirements_revision": None, "requirements_sha256": None}
    for change in ({"requirements_revision": 1}, {"requirements_sha256": "a" * 64},
                   {"clarification_request_ref": "not-an-existing-question", "clarification_version": 1}):
        response = bridge.post(PM + "checkpoint", json={**checkpoint, **change}, headers=headers)
        assert response.status_code == 422, response.text
    waiting = bridge.post(PM + "checkpoint", json=checkpoint, headers=headers)
    assert waiting.status_code == 200, waiting.text
    assert bridge.post(PM + "checkpoint", json=checkpoint, headers=headers).json() == waiting.json()
    saved = waiting.json()["result"]["checkpoint"]
    assert saved["requirements_revision"] is saved["requirements_sha256"] is None
    assert saved["clarification_request_ref"] is saved["clarification_version"] is None
    new_run = str(uuid4())
    resume = {**checkpoint, "operation_key": "brainstorm:resume", "expected_version": 2,
              "new_session_run_id": new_run, "input": {"input_kind": "feedback", "input_id": str(uuid4())},
              "input_receipt": {"reference": "tracker:real-owner-feedback", "sha256": "b" * 64}}
    for kind in ("answer", "confirmation"):
        response = bridge.post(PM + "resume", json={**resume, "input": {**resume["input"], "input_kind": kind}},
                               headers=WRITER)
        assert response.status_code == 422, response.text
    assert bridge.post(PM + "resume", json=resume, headers=WRITER).status_code == 409
    observations[SESSION].update(status="stopped", checkpoint_ref=checkpoint["checkpoint_ref"])
    reserved = bridge.post(PM + "resume", json=resume, headers=WRITER)
    assert reserved.status_code == 200, reserved.text
    assert bridge.post(PM + "resume", json=resume, headers=WRITER).json() == reserved.json()
    assert reserved.json()["result"]["identity"] == identity
    assert reserved.json()["result"]["resume_input"] == {
        "input": resume["input"], "input_receipt": resume["input_receipt"],
    }
    assert reserved.json()["result"]["checkpoint"] == saved
    with SAUnitOfWork() as uow:
        execution = uow.session.scalar(select(m.PMExecution))
        task = uow.tasks.get_by_key(identity["task"])
        assert execution.execution_ref == identity["execution_ref"]
        assert execution.state == "resume_pending"
        assert task.current_phase_code == "PM-DRAFT-01"
        assert not uow.step_history.list(task_id=task.id)
