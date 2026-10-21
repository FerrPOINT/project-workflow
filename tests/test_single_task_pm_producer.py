"""Actual initial PM bridge exchanges; synthetic authority, real SQLite ledgers."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select

from project_workflow import config
from project_workflow.application.namespace_ownership import NamespaceOwnershipService
from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest
from project_workflow.domain.pm_execution import RuntimeObservation
from project_workflow.domain.runtime_assignment import canonical_json
from project_workflow.domain.single_task_profile import MANIFEST_SHA256
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.infrastructure.namespace_auth import NamespacePrincipal
from tests import test_single_task_runtime as runtime_fixture
from tests.test_single_task_installation import assignment_payload
from tests.test_single_task_runtime import (
    API,
    PM,
    PROFILE,
    RUNNER,
    SESSION,
    WRITER,
)

FIXTURE = Path(__file__).parent / "fixtures" / "single_task_pm_initial_dispatch.json"
PRE_BACKLOG_MANIFEST = "19d3228270bc76959f91a06f3b946a39b4509b14a2c29b62acc8762dd5cc3fe2"


ORIGINAL_INPUT = {"title": "Owner goal", "description": "Exact original input"}


@pytest.fixture
def bridge(monkeypatch, request):
    manifest = getattr(request, "param", MANIFEST_SHA256)
    if manifest != MANIFEST_SHA256:
        from tests import test_single_task_installation as installation_fixture
        from tests.test_single_task_profile_compatibility import install_retained

        install_retained(monkeypatch, manifest)
        profile = {**runtime_fixture.PROFILE, "instruction_manifest_sha256": manifest}
        monkeypatch.setattr(runtime_fixture, "PROFILE", profile)
        monkeypatch.setattr(installation_fixture, "MANIFEST_SHA256", manifest)
        monkeypatch.setitem(globals(), "PROFILE", profile)
        monkeypatch.setitem(globals(), "FIXTURE", FIXTURE.parent / "retained" / manifest / FIXTURE.name)
    yield from runtime_fixture.bridge.__wrapped__(monkeypatch)


@pytest.fixture
def initial_pm(bridge, monkeypatch):
    refs = [{"kind": "pm_draft_input", "ref": "22222222-2222-4222-8222-222222222222",
             "hash": hashlib.sha256(canonical_json(ORIGINAL_INPUT).encode("utf-8")).hexdigest()}]
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"project_manager": "w" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"project_manager": "r" * 40}))
    config.get_settings.cache_clear()
    assignment = {**assignment_payload(), "role_key": "project_manager",
                  "workflow_key": "single-task-v1:project_manager",
                  "mode_key": "draft", "stage_key": "Draft", "execution_scope": "business", "exact_input_refs": refs,
                  "task": "SDLC-7", "operation_key": "pm-draft:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}
    assign_exchange, accepted = exchange(bridge, API + "assign", assignment, WRITER)
    binding = {**PROFILE, "task": assignment["task"], "bind_operation_key": "fleet-pm-runtime-bind:" + SESSION,
               "assignment_operation_key": assignment["operation_key"], "assignment_revision": 1,
               "assignment_ref": assignment["assignment_ref"], "binding_ref": "fleet:pm:" + SESSION,
               "hermes_run_ref": "run_pm",
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
    command = {**PROFILE, **identity, "operation_key": "fleet-pm-bind:" + SESSION, "expected_version": 0,
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


@pytest.mark.parametrize("bridge", [MANIFEST_SHA256, PRE_BACKLOG_MANIFEST],
                         indirect=True, ids=["current", "retained19"])
def test_pm_initial_dispatch_actual_producer_fixture(bridge, initial_pm):
    assignment, binding, step, general_headers, command, observation, assign_exchange, bind_exchange = initial_pm
    accepted = assign_exchange["response"]
    bound = bind_exchange["response"]
    assert accepted["result"]["exact_input_refs"] == assignment["exact_input_refs"]
    assert "revision" not in accepted["result"]["exact_input_refs"][0]
    assert bound["result"]["exact_input_refs"] == assignment["exact_input_refs"]
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
        "creation_uuid": SESSION,
        "original_input": {**ORIGINAL_INPUT, "id": assignment["exact_input_refs"][0]["ref"],
                           "sha256": assignment["exact_input_refs"][0]["hash"]},
        "runtime_observation": observation, "assign": assign_exchange, "bind": bind_exchange,
        "pm_bind": pm_exchange, "first_step": first_exchange, "pm_readback": readback_exchange,
    }
    if PROFILE["instruction_manifest_sha256"] == PRE_BACKLOG_MANIFEST:
        assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == (
            "b7bbea38b215cdcb27f70bd1197f9dbb39f8d66a6a9c87899b4a1b13a586ca73"
        )
    if (PROFILE["instruction_manifest_sha256"] == MANIFEST_SHA256
        and os.environ.get("WORKFLOW_UPDATE_PM_INITIAL_FIXTURE") == "1"):
        FIXTURE.write_text(json.dumps(captured, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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


def test_profile_assign_preserves_omitted_input_fields_in_response_and_ledger(bridge, initial_pm):
    assignment, _, _, _, _, _, accepted, bound = initial_pm
    expected = assignment["exact_input_refs"]
    assert set(expected[0]) == {"kind", "ref", "hash"}
    assert accepted["response"]["result"]["exact_input_refs"] == expected
    assert bound["response"]["result"]["exact_input_refs"] == expected
    replay = bridge.post(API + "assign", json=assignment, headers=WRITER)
    assert replay.status_code == 200, replay.text
    assert replay.json()["result"]["exact_input_refs"] == expected
    explicit_null = {**assignment, "exact_input_refs": [{**expected[0], "revision": None}]}
    assert bridge.post(API + "assign", json=explicit_null, headers=WRITER).status_code == 409
    with SAUnitOfWork() as uow:
        record = uow.tasks.get_assignment_by_operation_key(assignment["operation_key"])
        assert record.exact_input_refs == record.payload["exact_input_refs"] == expected


def test_legacy_assignment_and_input_request_schemas_match_existing_public_contract(bridge):
    published = json.loads((FIXTURE.parents[2] / "docs" / "pm-continuation-openapi.json").read_text(encoding="utf-8"))
    actual = bridge.get("/openapi.json").json()["components"]["schemas"]
    for name in ("RuntimeAssignmentRequest", "ExactInputRef", "PMDraftAssignment"):
        assert actual[name] == published["components"]["schemas"][name]
