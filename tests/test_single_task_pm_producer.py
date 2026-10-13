"""Actual initial PM bridge exchanges; synthetic authority, real SQLite ledgers."""

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from project_workflow import config
from project_workflow.application.namespace_ownership import NamespaceOwnershipService
from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest
from project_workflow.domain.pm_execution import RuntimeObservation
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.infrastructure.namespace_auth import NamespacePrincipal
from tests.test_single_task_installation import assignment_payload
from tests.test_single_task_runtime import (
    API,
    PM,
    PROFILE,
    RUNNER,
    SESSION,
    WRITER,
)
from tests.test_single_task_runtime import (
    bridge as bridge,
)

FIXTURE = Path(__file__).parent / "fixtures" / "single_task_pm_initial_dispatch.json"


@pytest.fixture
def initial_pm(bridge, monkeypatch):
    original_input = b"Owner original input for this isolated producer contract test."
    refs = [{"kind": "original_input", "ref": "22222222-2222-4222-8222-222222222222",
             "revision": "1", "hash": hashlib.sha256(original_input).hexdigest()}]
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"project_manager": "w" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"project_manager": "r" * 40}))
    config.get_settings.cache_clear()
    assignment = {**assignment_payload(), "role_key": "project_manager",
                  "workflow_key": "single-task-v1:project_manager",
                  "mode_key": "draft", "stage_key": "Draft", "execution_scope": "business", "exact_input_refs": refs}
    assign_exchange, accepted = exchange(bridge, API + "assign", assignment, WRITER)
    binding = {**PROFILE, "task": assignment["task"], "bind_operation_key": "bind:1",
               "assignment_operation_key": assignment["operation_key"], "assignment_revision": 1,
               "assignment_ref": assignment["assignment_ref"], "binding_ref": "binding:1", "hermes_run_ref": "run:1",
               "mode_key": "draft", "cycle_number": 0, "attempt_number": 1, "expected_binding_state": "unbound",
               "concrete_agent_ref": assignment["concrete_agent_ref"], "session_run_id": SESSION}
    bind_exchange, bound = exchange(bridge, API + "bind", binding, WRITER, "<execution-token-from-bind>")
    step = {**PROFILE, "task": assignment["task"], "step_operation_key": "step:read",
            "assignment_revision": 1, "assignment_ref": assignment["assignment_ref"],
            "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"], "mode_key": "draft",
            "cycle_number": 0, "attempt_number": 1, "expected_phase_code": accepted["result"]["current_phase_code"],
            "expected_status": "active", "session_run_id": SESSION,
            "single_task_context_sha256": bound["result"]["single_task_context_sha256"]}
    general_headers = {**RUNNER, "X-Workflow-Execution-Token": bound["execution_token"]}
    identity = {"task": assignment["task"], "execution_ref": assignment["execution_ref"],
                "tracker_instance_ref": assignment["tracker_instance_ref"],
                "tracker_project_ref": assignment["tracker_project_ref"], "task_ref": assignment["business_task_ref"],
                "root_ref": assignment["root_task_ref"], "agent_ref": assignment["concrete_agent_ref"],
                "assignment_operation_key": assignment["operation_key"], "assignment_ref": assignment["assignment_ref"],
                "assignment_revision": 1}
    command = {**PROFILE, **identity, "operation_key": "pm:bind", "expected_version": 0,
               "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
               "session_run_id": SESSION}
    observation = {**identity, "observation_ref": "observed:1", "status": "running",
                   "binding_ref": binding["binding_ref"], "hermes_run_ref": binding["hermes_run_ref"],
                   "dispatch_operation_key": command["operation_key"], "fence": 1, "session_run_id": SESSION,
                   "checkpoint_ref": None}
    monkeypatch.setattr(pm_readback, "observe_run", lambda run: RuntimeObservation.model_validate(observation))

    def no_model(*args, **kwargs):
        pytest.fail("Initial dispatch/first instruction read must not evaluate a model report")

    monkeypatch.setattr(OpenAICompatibleClient, "chat", no_model)
    return assignment, binding, step, general_headers, command, observation, assign_exchange, bind_exchange


def provision(assignment, tracker_project_ref=None):
    with SAUnitOfWork() as uow:
        project = uow.projects.get_by_cli_command("workflow-single-task-project-manager")
        request = NamespaceOwnershipRequest(
            contract_version=1, tracker_instance_ref=assignment["tracker_instance_ref"],
            tracker_project_ref=tracker_project_ref or assignment["tracker_project_ref"],
        )
        principal = NamespacePrincipal(
            issuer="http://auth.test", subject="33333333-3333-4333-8333-333333333333",
        )
        first, created = NamespaceOwnershipService(uow).provision(project.id, request, principal)
        assert created
        second, created = NamespaceOwnershipService(uow).provision(project.id, request, principal)
        assert not created and first == second


def exchange(client, path, body, headers, token_marker=None):
    response = client.post(path, json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert client.post(path, json=body, headers=headers).json() == response.json()
    captured = response.json()
    if token_marker:
        assert len(captured["execution_token"]) == 64
        captured["execution_token"] = token_marker
    return {"path": path, "request": body, "status_code": response.status_code, "response": captured}, response.json()


def test_pm_initial_dispatch_actual_producer_fixture(bridge, initial_pm):
    assignment, binding, step, general_headers, command, observation, assign_exchange, bind_exchange = initial_pm
    accepted = assign_exchange["response"]
    bound = bind_exchange["response"]
    assert accepted["result"]["exact_input_refs"] == assignment["exact_input_refs"]
    assert accepted["result"]["concrete_agent_ref"] is None
    assert accepted["result"]["current_phase_code"] == "PM-DRAFT-01"
    assert bridge.post(API + "step", json=step, headers=general_headers).status_code == 409
    provision(assignment)
    pm_exchange, enrolled = exchange(bridge, PM + "bind", command, WRITER, "<execution-token-from-pm-bind>")
    assert enrolled["execution_token"] != general_headers["X-Workflow-Execution-Token"]
    assert enrolled["result"]["single_task_context_sha256"] != bound["result"]["single_task_context_sha256"]
    headers = {**RUNNER, "X-Workflow-Execution-Token": enrolled["execution_token"]}
    current_step = {**step, "single_task_context_sha256": enrolled["result"]["single_task_context_sha256"]}
    assert bridge.post(API + "step", json=current_step, headers=general_headers).status_code == 403
    assert bridge.post(API + "step", json=step, headers=headers).status_code == 409
    first_exchange, first = exchange(bridge, API + "step", current_step, headers)
    assert first["result"]["phase_code"] == "PM-DRAFT-01"
    assert first["result"]["status"] == "active"
    assert first["result"]["phase_contract"]["allowed_tools"]
    assert "workflow_receipt" not in first["result"] and "complete" not in first["result"]
    readback_exchange, readback = exchange(
        bridge, PM + "readback",
        {**PROFILE, **enrolled["result"]["identity"], "operation_key": command["operation_key"]},
        WRITER, "<execution-token-from-pm-bind>",
    )
    snapshot = dict(readback["result"])
    operation = snapshot.pop("operation")
    assert snapshot == operation["result"] == enrolled["result"]
    assert readback["execution_token"] == enrolled["execution_token"]
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key(assignment["task"])
        records = uow.tasks.list_assignments(task.id)
        assert len(records) == 1 and task.current_phase_code == "PM-DRAFT-01"
        assert task.status == "active" and task.cycle_number == 0
        assert records[0].exact_input_refs == assignment["exact_input_refs"]
        assert records[0].decomposition_revision_ref is records[0].queue_item_ref is None
        assert not uow.step_history.list(task_id=task.id)
        assert len(uow.session.scalars(select(m.PMExecution)).all()) == 1
        assert len(uow.session.scalars(select(m.PMRun)).all()) == 1
    captured = {
        "authority": "Isolated SQLite/TestClient; synthetic Tracker inputs and runtime observation, not live QA.",
        "credential_redaction": "Only execution_token values replaced; all other response values are actual.",
        "runtime_observation": observation, "assign": assign_exchange, "bind": bind_exchange,
        "pm_bind": pm_exchange, "first_step": first_exchange, "pm_readback": readback_exchange,
    }
    assert captured == json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("failure", ["missing_owner", "foreign_owner", "foreign_observation", "stopped", "unavailable"])
def test_pm_initial_dispatch_requires_actual_owner_and_current_running_readback(
    bridge, initial_pm, monkeypatch, failure,
):
    assignment, _, _, _, command, observation, _, _ = initial_pm
    if failure != "missing_owner":
        provision(assignment, "44444444-4444-4444-8444-444444444444" if failure == "foreign_owner" else None)
    if failure == "foreign_observation":
        observation["execution_ref"] = "55555555-5555-4555-8555-555555555555"
    if failure == "stopped":
        observation["status"] = "stopped"
    if failure == "unavailable":
        def unavailable(run):
            raise pm_readback.ReadbackUnavailable("Synthetic runtime readback unavailable")
        monkeypatch.setattr(pm_readback, "observe_run", unavailable)
    response = bridge.post(PM + "bind", json=command, headers=WRITER)
    assert response.status_code == (503 if failure == "unavailable" else 409), response.text
    with SAUnitOfWork() as uow:
        assert not uow.session.scalars(select(m.PMExecution)).all()
        assert not uow.session.scalars(select(m.PMRun)).all()
        task = uow.tasks.get_by_key(assignment["task"])
        assert not uow.step_history.list(task_id=task.id)


def test_profile_pm_packet_is_not_legacy_pm_assign(bridge, initial_pm):
    assignment, _, _, _, _, _, _, _ = initial_pm
    assert bridge.post(PM + "assign", json=assignment, headers=WRITER).status_code == 422
