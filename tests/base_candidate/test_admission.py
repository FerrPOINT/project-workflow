"""Source/API evidence with synthetic Fleet metadata, never live acceptance."""

import copy
import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.application import base_admission
from project_workflow.application.task import TaskService
from project_workflow.domain.base_admission import BASE_SKILLS_REVISION
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure import base_package
from project_workflow.infrastructure.base_package import digest
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog, load_managed_catalog
from project_workflow.infrastructure.db.models import PhaseInstruction
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.routes import runtime_api
from project_workflow.supervisor import SupervisorEngine
from tests.test_runtime_api import _bind_payload, _headers, _step_payload
from tests.test_runtime_assignment_contract import _binding, _continuation

AGENT = "11111111-1111-4111-8111-111111111111"
OWNER = _headers("base-owner-" + "o" * 32)
RUNTIME = _headers("base-runtime-" + "r" * 32)
REAL_GIT_READ = base_package.GitPackage.read
REAL_OWNER_EVIDENCE_GUARD = base_admission.require_owner_execution_evidence


@pytest.fixture
def base(monkeypatch, tmp_path):
    # Component tests only: production admission remains blocked until real
    # owner protocols exist. Security tests restore the real guard explicitly.
    monkeypatch.setattr(base_admission, "require_owner_execution_evidence", lambda: None)
    candidate = load_managed_catalog(base_admission.CANDIDATE_PATH)
    roles = {
        workflow.role_key: {
            "namespace": workflow.hermes_namespace, "profile": workflow.hermes_profile,
            "modes": [mode.key for mode in workflow.modes],
            "physicalSkills": workflow.skill_allowlist,
            "roleInstruction": {"sha256": "d" * 64},
        }
        for workflow in candidate.workflows
    }
    # Private Git verification has its own real synthetic-Git tests. This API
    # fixture isolates the owner boundary using explicit source metadata only.
    monkeypatch.setattr(base_admission, "load_pinned_package", lambda *_: {"roles": roles})
    monkeypatch.setattr(base_admission.GitPackage, "read", lambda *_: b"synthetic manifest")
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", str(tmp_path / "agent-skills"))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"developer": "base-runtime-" + "r" * 32}))
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"developer": "base-owner-" + "o" * 32}))
    config.get_settings.cache_clear()
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow, base_admission.CANDIDATE_PATH)
        uow.commit()
    admission = {
        "contract": "base-sdlc-admission/v1",
        "config_ref": "fleet-config:synthetic@1", "config_sha256": "a" * 64,
        "concrete_agent_ref": AGENT,
        "namespace": roles["developer"]["namespace"], "profile": roles["developer"]["profile"],
        "catalog_sha256": digest(base_admission.CANDIDATE_PATH.read_bytes()),
        "skills_revision": BASE_SKILLS_REVISION,
        "skills_manifest_sha256": digest(b"synthetic manifest"),
        "role_instruction_sha256": "d" * 64,
        "physical_skills": roles["developer"]["physicalSkills"],
    }
    payload = {
        **_binding(runtime_compatibility=None),
        "task": "DEV-1", "mode_key": "initial", "cycle_number": 0,
        "operation_key": "base-assign:1", "expected_revision": 0, "expected_status": "missing",
        "base_admission": admission,
    }
    client = TestClient(create_app())
    yield client, payload
    client.close()


def assign_and_bind(base):
    client, payload = base
    accepted = client.post("/internal/runtime/assign", headers=OWNER, json=payload)
    assert accepted.status_code == 200, accepted.text
    assigned = accepted.json()["result"]
    bind = {**_bind_payload(assigned), "concrete_agent_ref": AGENT}
    bound = client.post("/internal/runtime/bind", headers=OWNER, json=bind)
    assert bound.status_code == 200, bound.text
    return bound.json()["result"], bind


def step(bound, payload, **changes):
    return {
        **_step_payload(bound),
        "base_config_ref": payload["base_admission"]["config_ref"],
        "base_config_sha256": payload["base_admission"]["config_sha256"],
        **changes,
    }


def snapshot():
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-1")
        if task is None:
            return None
        return (
            task.to_dict(),
            [item.to_dict() for item in uow.tasks.list_assignments(task.id)],
            [item.to_dict() for item in uow.tasks.list_phase_events(task.id)],
            [item.to_dict() for item in uow.step_history.list(task_id=task.id)],
        )


def test_owner_api_issues_first_candidate_step_without_model_or_cursor_mutation(base, monkeypatch):
    client, payload = base
    bound, bind = assign_and_bind(base)
    before = snapshot()
    evaluator = Mock(side_effect=AssertionError("First instruction must not evaluate"))
    monkeypatch.setattr(SupervisorEngine, "evaluate", evaluator)
    response = client.post("/internal/runtime/step", headers=RUNTIME, json=step(bound, payload))
    assert response.status_code == 200, response.text
    assert response.json()["result"]["phase_code"] == "DV-INITIAL-01"
    assert response.json()["result"]["phase_contract"]["instructions"]
    receipt = response.json()["base_admission_receipt"]
    assert receipt["base_admission"] == payload["base_admission"]
    assert receipt["receipt_sha256"] == payload_sha256({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    assert "complete" not in receipt
    assert snapshot() == before
    assert client.post("/internal/runtime/bind", headers=OWNER, json=bind).status_code == 200
    evaluator.assert_not_called()


@pytest.mark.parametrize("scope", ["delivery", "aggregate"])
def test_developer_initial_scope_is_independent_of_mode(base, scope):
    client, payload = base
    payload["execution_scope"] = scope
    bound, _ = assign_and_bind(base)
    response = client.post("/internal/runtime/step", headers=RUNTIME, json=step(bound, payload))
    assert response.status_code == 200, response.text
    assert response.json()["base_admission_receipt"]["execution_scope"] == scope
    assert bound["mode_key"] == "initial"


@pytest.mark.parametrize("field,value", [
    ("namespace", "foreign"), ("profile", "foreign"), ("catalog_sha256", "0" * 64),
    ("skills_manifest_sha256", "0" * 64), ("role_instruction_sha256", "0" * 64),
    ("physical_skills", ["foreign"]),
])
def test_bad_package_config_never_creates_assignment(base, field, value):
    client, payload = base
    payload["base_admission"][field] = value
    response = client.post("/internal/runtime/assign", headers=OWNER, json=payload)
    assert response.status_code == 409, response.text
    assert snapshot() is None


@pytest.mark.parametrize("field,value", [
    ("mode_key", "delivery"), ("execution_scope", "business"), ("workflow_key", "hermes-sdlc:tester"),
    ("role_key", "tester"), ("base_admission", None),
])
def test_wrong_assignment_policy_never_creates_assignment(base, field, value):
    client, payload = base
    payload[field] = value
    assert client.post("/internal/runtime/assign", headers=OWNER, json=payload).status_code in {403, 409}
    assert snapshot() is None


def test_runtime_token_cannot_issue_owner_config_or_bind(base):
    client, payload = base
    assert client.post("/internal/runtime/assign", headers=RUNTIME, json=payload).status_code == 403
    bound, bind = assign_and_bind(base)
    assert client.post("/internal/runtime/bind", headers=RUNTIME, json=bind).status_code == 403
    assert bound["concrete_agent_ref"] == AGENT


def test_wrong_concrete_agent_bind_leaves_assignment_unbound(base):
    client, payload = base
    assigned = client.post("/internal/runtime/assign", headers=OWNER, json=payload).json()["result"]
    before = snapshot()
    bind = {**_bind_payload(assigned), "concrete_agent_ref": "22222222-2222-4222-8222-222222222222"}
    assert client.post("/internal/runtime/bind", headers=OWNER, json=bind).status_code == 409
    assert snapshot() == before


@pytest.mark.parametrize("changes", [
    {"base_config_ref": None}, {"base_config_sha256": None},
    {"base_config_ref": "stale"}, {"base_config_sha256": "0" * 64},
    {"assignment_revision": 2}, {"hermes_run_ref": "stale"}, {"binding_ref": "foreign"},
    {"expected_phase_code": "DV-INITIAL-02"}, {"mode_key": "rework"},
])
def test_bad_first_step_fails_before_executor_without_changes(base, monkeypatch, changes):
    client, payload = base
    bound, _ = assign_and_bind(base)
    before = snapshot()
    executor = Mock(side_effect=AssertionError("Rejected admission reached executor"))
    monkeypatch.setattr(runtime_api, "execute_namespace_step", executor)
    response = client.post("/internal/runtime/step", headers=RUNTIME, json=step(bound, payload, **changes))
    assert response.status_code == 409, response.text
    assert snapshot() == before
    executor.assert_not_called()


def test_candidate_catalog_drift_fails_before_first_step(base, monkeypatch):
    client, payload = base
    bound, _ = assign_and_bind(base)
    with SAUnitOfWork() as uow:
        instruction = uow.session.query(PhaseInstruction).filter_by(phase_id=bound["current_phase_id"]).first()
        instruction.description = "Drifted source instruction"
        uow.commit()
    executor = Mock(side_effect=AssertionError("Drift reached executor"))
    monkeypatch.setattr(runtime_api, "execute_namespace_step", executor)
    assert client.post("/internal/runtime/step", headers=RUNTIME, json=step(bound, payload)).status_code == 409
    executor.assert_not_called()


def test_unscoped_generic_supervisor_cannot_bypass_base_admission(base):
    assign_and_bind(base)
    before = snapshot()
    with SAUnitOfWork() as uow, pytest.raises(ConflictError, match="admitted runtime step"):
        SupervisorEngine("DEV-1", uow=uow, create_if_missing=False)
    assert snapshot() == before


def test_replay_config_collision_and_restart_use_existing_ledger(base, supervisor_llm):
    client, payload = base
    bound, _ = assign_and_bind(base)
    supervisor_llm("PASS")
    request = step(bound, payload, report="Synthetic admission evidence")
    response = client.post("/internal/runtime/step", headers=RUNTIME, json=request)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["verdict"] == "PASS"
    before = snapshot()
    restarted = TestClient(create_app())
    try:
        replay = restarted.post("/internal/runtime/step", headers=RUNTIME, json=request)
        assert replay.json() == response.json()
        assert snapshot() == before
        altered = {**request, "base_config_sha256": "0" * 64}
        assert restarted.post("/internal/runtime/step", headers=RUNTIME, json=altered).status_code == 409
        assert snapshot() == before
    finally:
        restarted.close()
    assert client.get("/internal/runtime/history", headers=RUNTIME, params={"task": "DEV-1"}).status_code == 200


def test_assignment_payload_collision_preserves_frozen_config(base):
    client, payload = base
    assign_and_bind(base)
    before = snapshot()
    changed = copy.deepcopy(payload)
    changed["base_admission"]["config_ref"] = "fleet-config:synthetic@2"
    assert client.post("/internal/runtime/assign", headers=OWNER, json=changed).status_code == 409
    assert snapshot() == before


def test_base_rebind_without_trusted_checkpoint_ack_is_blocked(base):
    client, _ = base
    bound, _ = assign_and_bind(base)
    before = snapshot()
    request = _continuation(bound)
    response = client.post("/internal/runtime/rebind", headers=OWNER, json=request)
    assert response.status_code == 409, response.text
    assert "checkpoint ACK" in response.json()["error"]
    assert snapshot() == before


def test_developer_rework_uses_same_cursor_engine_after_completed_initial(base, supervisor_llm):
    client, payload = base
    bound, _ = assign_and_bind(base)
    supervisor_llm("PASS")
    for number in range(1, 4):
        response = client.post("/internal/runtime/step", headers=RUNTIME, json=step(
            bound, payload, report=f"Synthetic phase {number} evidence",
            step_operation_key=f"base-initial-report:{number}", expected_phase_code=f"DV-INITIAL-{number:02}",
        ))
        assert response.status_code == 200, response.text
        assert response.json()["result"]["verdict"] == "PASS"
    rework = {
        **payload, "mode_key": "rework", "cycle_number": 1, "stage_key": "rework",
        "expected_revision": 1, "expected_status": "done", "expected_mode_key": "initial",
        "expected_cycle_number": 0, "operation_key": "base-rework:1", "assignment_ref": "assignment:rework@1",
    }
    assigned = client.post("/internal/runtime/assign", headers=OWNER, json=rework)
    assert assigned.status_code == 200, assigned.text
    bind = {**_bind_payload(assigned.json()["result"]), "concrete_agent_ref": AGENT}
    bound_response = client.post("/internal/runtime/bind", headers=OWNER, json=bind)
    assert bound_response.status_code == 200, bound_response.text
    response = client.post(
        "/internal/runtime/step", headers=RUNTIME, json=step(bound_response.json()["result"], payload),
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["phase_code"] == "DV-REWORK-01"
    assert response.json()["base_admission_receipt"]["cycle_number"] == 1
    history = client.get("/internal/runtime/history", headers=RUNTIME, params={"task": "DEV-1"})
    assert len(history.json()["result"]["records"]) == 3


def test_package_becoming_unavailable_blocks_work_before_executor(base, monkeypatch):
    client, payload = base
    bound, _ = assign_and_bind(base)
    before = snapshot()

    def unavailable(*_args):
        raise ValueError("Pinned commit is unavailable")

    monkeypatch.setattr(base_admission, "load_pinned_package", unavailable)
    executor = Mock(side_effect=AssertionError("Missing source reached executor"))
    monkeypatch.setattr(runtime_api, "execute_namespace_step", executor)
    assert client.post("/internal/runtime/step", headers=RUNTIME, json=step(bound, payload)).status_code == 409
    assert snapshot() == before
    executor.assert_not_called()


def test_base_admission_cannot_approve_legacy_catalog(base):
    client, payload = base
    with SAUnitOfWork() as uow:
        project = uow.projects.get_by_cli_command("workflow-developer")
        workflow = uow.workflows.get_by_id(project.workflow_id)
        uow.workflows.update(workflow.id, {"active_catalog_version": 2})
        uow.commit()
    assert client.post("/internal/runtime/assign", headers=OWNER, json=payload).status_code == 409
    assert snapshot() is None


def test_generic_cli_cannot_create_an_unadmitted_candidate_cursor(base):
    with SAUnitOfWork() as uow:
        project = uow.projects.get_by_cli_command("workflow-developer")
        with pytest.raises((ConflictError, ValueError)):
            runtime_api.execute_namespace_step(
                uow, namespace_id=project.id, task="DEV-1", report=None, create_if_missing=True,
            )
        with pytest.raises(ConflictError, match="owner-issued admission"):
            TaskService(uow).create_task({
                "project_id": project.id, "workflow_id": project.workflow_id,
                "task_key": "DEV-1", "title": "Synthetic candidate task",
            })
    assert snapshot() is None


@pytest.mark.parametrize("role_key,mode_key,scope", [
    ("project_manager", "draft", "business"), ("analyst", "analysis", "business"),
    ("architect", "decomposition", "business"), ("reviewer", "delivery", "delivery"),
    ("reviewer", "integration", "aggregate"), ("tester", "delivery", "delivery"),
    ("tester", "integration", "aggregate"), ("devops", "delivery", "delivery"),
    ("devops", "integration", "aggregate"),
])
def test_first_step_for_other_canonical_roles_uses_existing_executor(base, monkeypatch, role_key, mode_key, scope):
    client, payload = base
    owner_token = "source-test-owner-" + "o" * 32
    runtime_token = "source-test-runtime-" + "r" * 32
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({role_key: owner_token}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({role_key: runtime_token}))
    config.get_settings.cache_clear()
    candidate = load_managed_catalog(base_admission.CANDIDATE_PATH)
    workflow = next(item for item in candidate.workflows if item.role_key == role_key)
    payload.update(role_key=role_key, workflow_key=workflow.key, mode_key=mode_key, execution_scope=scope)
    if scope == "business":
        payload.update(tech_execution_workspace_ref=None, tech_execution_attempt_ref=None)
    payload["base_admission"].update(
        namespace=workflow.hermes_namespace, profile=workflow.hermes_profile,
        physical_skills=workflow.skill_allowlist,
    )
    assigned = client.post("/internal/runtime/assign", headers=_headers(owner_token), json=payload)
    assert assigned.status_code == 200, assigned.text
    bind = {**_bind_payload(assigned.json()["result"]), "concrete_agent_ref": AGENT}
    bound = client.post("/internal/runtime/bind", headers=_headers(owner_token), json=bind)
    assert bound.status_code == 200, bound.text
    response = client.post("/internal/runtime/step", headers=_headers(runtime_token), json=step(
        bound.json()["result"], payload,
    ))
    assert response.status_code == 200, response.text
    expected = next(item for item in workflow.modes if item.key == mode_key).phases[0]
    assert response.json()["result"]["phase_code"] == expected.code


@pytest.mark.parametrize("field,value", [
    ("skills_revision", "HEAD"), ("contract", "unknown/v1"), ("config_sha256", "malformed"),
])
def test_invalid_source_envelope_is_rejected_without_writes(base, field, value):
    client, payload = base
    payload["base_admission"][field] = value
    assert client.post("/internal/runtime/assign", headers=OWNER, json=payload).status_code == 422
    assert snapshot() is None


def test_callable_admission_with_authorized_private_git_package(base, monkeypatch):
    skills_root = os.environ.get("WORKFLOW_BASE_PACKAGE_TEST_ROOT")
    if not skills_root:
        pytest.skip("Optional authorized private Git source check; no fallback")
    monkeypatch.setattr(base_admission, "load_pinned_package", base_package.load_pinned_package)
    monkeypatch.setattr(base_package.GitPackage, "read", REAL_GIT_READ)
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", skills_root)
    config.get_settings.cache_clear()
    client, payload = base
    candidate = load_managed_catalog(base_admission.CANDIDATE_PATH)
    manifest = base_package.load_pinned_package(Path(skills_root), candidate.skills_source)
    package = base_package.GitPackage(Path(skills_root).resolve().parent, BASE_SKILLS_REVISION)
    role = manifest["roles"]["developer"]
    payload["base_admission"].update(
        skills_manifest_sha256=digest(package.read("manifest.json")),
        role_instruction_sha256=role["roleInstruction"]["sha256"],
        physical_skills=role["physicalSkills"],
    )
    bound, _ = assign_and_bind(base)
    response = client.post("/internal/runtime/step", headers=RUNTIME, json=step(bound, payload))
    assert response.status_code == 200, response.text
    assert response.json()["result"]["phase_code"] == "DV-INITIAL-01"
