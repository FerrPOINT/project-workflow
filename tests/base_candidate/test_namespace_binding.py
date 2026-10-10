"""Actual persisted namespace/profile observation, not source symbols or execution ACK."""

import hashlib
import http.client
import json
import os
import time
from unittest.mock import Mock
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from project_workflow import config
from project_workflow.application import base_admission, base_binding, base_source
from project_workflow.application import state as app_state
from project_workflow.domain.base_admission import BASE_SKILLS_REVISION
from project_workflow.domain.base_binding import BaseBindingInvalidRequest
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import (
    _persist_mode,
    ensure_managed_catalog,
    load_managed_catalog,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.routes import base_api
from scripts.export_base_binding_openapi import OUTPUT, base_binding_openapi
from tests.base_candidate.test_machine_readers import CATALOG_READER, CATALOG_SUBJECT, PM_READER, READER, TESTER_READER
from tests.base_candidate.test_machine_readers import registered_readers as registered_readers
from tests.base_candidate.test_source import RUNTIME_TOKEN, TOKEN
from tests.base_candidate.test_source import source as source

PATH = "/internal/runtime/base/namespace-bindings"


@pytest.fixture
def installed():
    # Fresh disposable pytest SQLite only, never the accepted database or startup.
    with SAUnitOfWork() as uow:
        catalog = ensure_managed_catalog(uow, base_source.CANDIDATE_PATH)
        namespaces = {definition.role_key: uow.projects.get_by_cli_command(f"workflow-{definition.role_key}").id
                      for definition in catalog.workflows}
    return namespaces


@pytest.fixture
def client():
    # Do not exercise unchanged v2 startup against an explicitly installed v3 test DB.
    value = TestClient(create_app())
    yield value
    value.close()


def snapshot():
    with SAUnitOfWork() as uow:
        return {table.name: [dict(row) for row in uow.session.execute(select(table)).mappings()]
                for table in m.Base.metadata.sorted_tables}


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["ok"] is False
    assert response.json()["error_code"] == code
    assert "binding" not in response.json()
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("role", [
    "project_manager", "analyst", "architect", "developer", "reviewer", "tester", "devops",
])
def test_persisted_fk_registered_profile_and_exact_source_binding(source, registered_readers, installed, client, role):
    before = snapshot()
    namespace_id = installed[role]
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_persisted_identity(namespace_id)
        workflow = uow.workflows.get_by_id(namespace["workflow_id"])
        agent = uow.agents.get_by_name(role)
    expected = {
        "ok": True, "binding": {
            "schema": "base-sdlc/workflow-binding/v1", "namespace_id": str(namespace_id),
            "namespace_name": namespace["name"], "workflow_id": str(workflow.id), "workflow_key": workflow.key,
            "role_key": role, "profile": agent.hermes_profile, "catalog_version": 3,
            "catalog_sha256": hashlib.sha256(
                base_source.CANDIDATE_PATH.read_bytes().replace(b"\r\n", b"\n"),
            ).hexdigest(),
            "skills_revision": BASE_SKILLS_REVISION, "runtime_ready": False,
        },
    }
    response = client.get(f"{PATH}/{namespace_id}", headers=CATALOG_READER)
    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert response.headers["cache-control"] == "no-store"
    restarted = TestClient(create_app())
    assert restarted.get(f"{PATH}/{namespace_id}", headers=CATALOG_READER).json() == expected
    restarted.close()
    assert len(registered_readers["calls"]) == 2
    assert snapshot() == before
    assert base_source.export_base_source()["roles"][role]["namespace"] == namespace["name"]
    assert "observed_at" not in response.text
    with pytest.raises(ConflictError, match="trusted owner"):
        base_admission.require_owner_execution_evidence()
    assert load_managed_catalog().catalog_version == 2


def test_reads_arbitrary_actual_numeric_namespace_id_not_symbol_or_workflow_id(
    source, registered_readers, installed, client,
):
    with SAUnitOfWork() as uow:
        namespace = uow.session.get(m.Project, installed["developer"])
        namespace.id = 123
    response = client.get(f"{PATH}/123", headers=CATALOG_READER)
    assert response.status_code == 200, response.text
    binding = response.json()["binding"]
    assert binding["namespace_id"] == "123" and binding["namespace_name"] == "hermes-developer"
    assert binding["workflow_id"] != "123" and binding["workflow_key"] == "hermes-sdlc:developer"


@pytest.mark.parametrize("headers,status", [
    ({}, 401), ({"Authorization": "Bearer admin"}, 401),
    ({"Authorization": f"Bearer {TOKEN}"}, 401), ({"Authorization": f"Bearer {RUNTIME_TOKEN}"}, 401),
    (READER, 403), (PM_READER, 403), (TESTER_READER, 403),
])
def test_auth_before_db_no_role_human_or_legacy_fallback(
    source, registered_readers, client, monkeypatch, headers, status,
):
    database = Mock(side_effect=AssertionError("Unauthorized request opened a database"))
    monkeypatch.setattr(base_api, "SAUnitOfWork", database)
    monkeypatch.setattr(type(app_state._app_state), "create_uow", database)
    assert_error(client.get(f"{PATH}/1", headers=headers), status, "machine-access-denied")
    database.assert_not_called()


@pytest.mark.parametrize("scopes", [
    [], ["project-workflow:write"], ["project-workflow:*"], ["fleet-control:read"],
    ["project-workflow:read", "project-workflow:write"], ["project-workflow:read", "project-workflow:read"],
    ["project-workflow:read", "project-workflow:namespace:read:1"],
])
def test_catalog_requires_exact_registered_issuer_scope(registered_readers, client, scopes):
    registered_readers["value"] = {"sub": CATALOG_SUBJECT, "email": "catalog@test", "scopes": scopes}
    assert_error(client.get(f"{PATH}/1", headers=CATALOG_READER), 403, "machine-access-denied")


def test_human_subject_and_fresh_revocation_are_denied(source, registered_readers, installed, client):
    path = f"{PATH}/{installed['developer']}"
    assert client.get(path, headers=CATALOG_READER).status_code == 200
    registered_readers["value"] = {
        "sub": "55555555-5555-4555-8555-555555555555", "email": "catalog@test", "scopes": ["project-workflow:read"],
    }
    assert_error(client.get(path, headers=CATALOG_READER), 403, "machine-access-denied")
    registered_readers.update(value=None, status=401)
    assert_error(client.get(path, headers=CATALOG_READER), 401, "machine-access-denied")
    assert len(registered_readers["calls"]) == 3


def test_unavailable_authority_is_typed_503(registered_readers, client):
    registered_readers["status"] = 503
    assert_error(client.get(f"{PATH}/1", headers=CATALOG_READER), 503, "authorization-unavailable")


@pytest.mark.parametrize("namespace_id", ["0", "-1", "01", "+1", "1.0", " 1", "1 ", "hermes-developer", "\u0661", "1\n",
                                            str(2**63), "1" * 20])
def test_path_requires_positive_canonical_i64_string(registered_readers, client, namespace_id):
    response = client.get(f"{PATH}/{quote(namespace_id, safe='')}", headers=CATALOG_READER)
    assert response.status_code == 422, response.text
    assert BaseBindingInvalidRequest.model_validate(response.json()).ok is False
    assert registered_readers["calls"] == []


def test_max_canonical_i64_is_valid_path_but_not_synthetic_mapping(source, registered_readers, installed, client):
    assert_error(client.get(f"{PATH}/{2**63 - 1}", headers=CATALOG_READER), 409, "binding-conflict")
    assert len(registered_readers["calls"]) == 1


@pytest.mark.parametrize("version", [None, 2])
def test_absent_or_default_v2_catalog_is_not_adopted(source, registered_readers, client, version):
    if version == 2:
        with SAUnitOfWork() as uow:
            ensure_managed_catalog(uow)
    before = snapshot()
    assert_error(client.get(f"{PATH}/1", headers=CATALOG_READER), 409, "binding-conflict")
    assert snapshot() == before


def test_active_v3_observation_preserves_historical_v2_modes_assignments_history_and_pins(
    source, registered_readers, client,
):
    with SAUnitOfWork() as uow:
        legacy = ensure_managed_catalog(uow)
        namespace = uow.projects.get_by_cli_command("workflow-developer")
        mode = uow.workflows.get_mode_by_key(namespace.workflow_id, "initial")
        phase = uow.phases.list(namespace.workflow_id, mode_id=mode.id)[0]
        task_id = uow.tasks.create({
            "project_id": namespace.id, "workflow_id": namespace.workflow_id, "mode_id": mode.id,
            "task_key": "DEV-HISTORICAL", "current_phase_id": phase.id, "status": "done",
        })
        uow.session.add(m.TaskRuntimeAssignment(
            operation_key="historical-v2-assignment", task_id=task_id, project_id=namespace.id,
            workflow_id=namespace.workflow_id, mode_id=mode.id, cycle_number=0, assignment_revision=1,
            payload=json.dumps({"catalog_version": 2, "skills_revision": legacy.skills_source.revision}),
        ))
        uow.session.add(m.TaskStepHistoryEntry(
            task_id=task_id, workflow_id=namespace.workflow_id, mode_id=mode.id, phase_id=phase.id,
            verdict="pass", worker_report="Historical v2 report, not Base execution proof",
        ))
        namespace_id = namespace.id
    historical = snapshot()
    # Explicit future-adoption fixture: canonical current metadata + appended v3 modes; retain old IDs/pins.
    # The owner adoption/bootstrap capability itself remains out of scope and unchanged.
    candidate = load_managed_catalog(base_source.CANDIDATE_PATH)
    with SAUnitOfWork() as uow:
        for definition in candidate.workflows:
            actual = next(item for item in uow.workflows.list() if item.key == definition.key)
            agent = uow.agents.get_by_name(definition.role_key)
            for new_mode in definition.modes:
                _persist_mode(uow, workflow_id=actual.id, role_key=definition.role_key, agent_id=agent.id,
                              mode=new_mode, catalog_version=3)
            uow.workflows.update(actual.id, {
                "active_catalog_version": 3, "name": definition.name, "description": definition.description,
            })
        assert {mode.catalog_version for mode in uow.workflows.list_modes(namespace.workflow_id)} == {3}
        archived = uow.workflows.list_modes(namespace.workflow_id, catalog_version=2)
        assert {mode.catalog_version for mode in archived} == {2}
        assert base_binding.validate_managed_catalog_state(uow, candidate) is True
    before = snapshot()
    response = client.get(f"{PATH}/{namespace_id}", headers=CATALOG_READER)
    assert response.status_code == 200, response.text
    assert response.json()["binding"]["catalog_version"] == 3
    after = snapshot()
    assert after == before
    for name in ("workflow_modes", "phases", "phase_instructions", "phase_checks", "phase_evidence_requirements",
                 "tasks", "task_runtime_assignments", "task_step_history"):
        assert all(row in after[name] for row in historical[name])


@pytest.mark.parametrize("change", [
    "namespace-name", "namespace-cli", "namespace-fk", "missing-namespace", "workflow-key", "profile",
    "missing-profile", "missing-agent", "other-role-profile", "other-role-version", "mode-version", "phase-agent",
    "instruction", "check", "evidence", "missing-phase",
])
def test_persisted_mapping_or_complete_candidate_drift_never_returns_binding(
    source, registered_readers, installed, client, change,
):
    namespace_id = installed["developer"]
    with SAUnitOfWork() as uow:
        namespace = uow.session.get(m.Project, namespace_id)
        workflow = uow.session.get(m.Workflow, namespace.workflow_id)
        agent = uow.session.scalar(select(m.Agent).where(m.Agent.name == "developer"))
        phase = uow.session.scalar(select(m.Phase).where(m.Phase.workflow_id == workflow.id))
        if change == "namespace-name":
            namespace.name = "foreign"
        elif change == "namespace-cli":
            namespace.cli_command = "foreign-command"
        elif change == "namespace-fk":
            namespace.workflow_id = uow.projects.get_persisted_identity(installed["tester"])["workflow_id"]
        elif change == "missing-namespace":
            uow.session.delete(namespace)
        elif change == "workflow-key":
            workflow.key = "foreign-key"
        elif change in {"profile", "missing-profile"}:
            agent.hermes_profile = "foreign-profile" if change == "profile" else None
        elif change == "missing-agent":
            agent.name = "unregistered-agent"
        elif change == "other-role-profile":
            uow.session.scalar(select(m.Agent).where(m.Agent.name == "tester")).hermes_profile = "foreign-profile"
        elif change == "other-role-version":
            uow.session.get(m.Workflow, uow.projects.get_persisted_identity(installed["tester"])["workflow_id"]
                            ).active_catalog_version = 2
        elif change == "mode-version":
            uow.session.get(m.WorkflowMode, phase.mode_id).catalog_version = 2
        elif change == "phase-agent":
            phase.agent_id = uow.agents.get_by_name("tester").id
        elif change == "instruction":
            uow.session.scalar(select(m.PhaseInstruction).where(m.PhaseInstruction.phase_id == phase.id)
                               ).description = "foreign"
        elif change == "check":
            uow.session.scalar(select(m.PhaseCheck).where(m.PhaseCheck.phase_id == phase.id)).description = "foreign"
        elif change == "evidence":
            uow.session.scalar(select(m.PhaseEvidenceRequirement).where(
                m.PhaseEvidenceRequirement.phase_id == phase.id)).description = "foreign"
        elif change == "missing-phase":
            uow.session.delete(phase)
    before = snapshot()
    assert_error(client.get(f"{PATH}/{namespace_id}", headers=CATALOG_READER), 409, "binding-conflict")
    assert snapshot() == before


@pytest.mark.parametrize("field,value", [
    ("namespace", "foreign"), ("profile", "foreign"), ("modes", ["delivery"]), ("physicalSkills", []),
])
def test_private_base_proof_disagreement_is_not_owner_observation(
    source, registered_readers, installed, client, field, value,
):
    source["roles"]["tester"][field] = value
    assert_error(client.get(f"{PATH}/{installed['developer']}", headers=CATALOG_READER), 503, "binding-unavailable")


def test_candidate_source_blob_drift_is_not_owner_observation(source, registered_readers, installed, client,
                                                            monkeypatch, tmp_path):
    path = tmp_path / "candidate.json"
    path.write_bytes(base_source.CANDIDATE_PATH.read_bytes() + b"\n")
    monkeypatch.setattr(base_source, "CANDIDATE_PATH", path)
    assert_error(client.get(f"{PATH}/{installed['developer']}", headers=CATALOG_READER), 503, "binding-unavailable")


def test_unavailable_pin_or_db_is_sanitized(source, registered_readers, installed, client, monkeypatch):
    path = f"{PATH}/{installed['developer']}"
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", "")
    config.get_settings.cache_clear()
    assert_error(client.get(path, headers=CATALOG_READER), 503, "binding-unavailable")
    monkeypatch.setattr(base_api, "SAUnitOfWork", Mock(side_effect=OperationalError(
        "private-db-url", {}, Exception("secret-credential"),
    )))
    response = client.get(path, headers=CATALOG_READER)
    assert_error(response, 503, "binding-unavailable")
    assert "secret" not in response.text and "private-db" not in response.text


def test_stale_mapping_during_validation_is_refreshed_and_rejected(source, registered_readers, installed, client,
                                                                 monkeypatch):
    validator = base_binding.validate_managed_catalog_state
    calls = []

    def changing_validator(uow, catalog):
        result = validator(uow, catalog)
        calls.append(True)
        if len(calls) == 1:
            with SAUnitOfWork() as writer:
                writer.session.get(m.Project, installed["developer"]).name = "changed-during-readback"
        return result

    monkeypatch.setattr(base_binding, "validate_managed_catalog_state", changing_validator)
    assert_error(client.get(f"{PATH}/{installed['developer']}", headers=CATALOG_READER), 409, "binding-conflict")
    assert calls


def test_successful_observation_never_commits(source, registered_readers, installed, client, monkeypatch):
    commit = Mock(side_effect=AssertionError("Read-only observation committed"))
    monkeypatch.setattr(SAUnitOfWork, "commit", commit)
    assert client.get(f"{PATH}/{installed['developer']}", headers=CATALOG_READER).status_code == 200
    commit.assert_not_called()


def test_generated_binding_openapi_matches_snapshot_and_exact_dto():
    generated = base_binding_openapi()
    assert generated == json.loads(OUTPUT.read_text(encoding="utf-8"))
    schemas = generated["components"]["schemas"]
    binding = schemas["BaseNamespaceBinding"]
    assert set(binding["required"]) == set(binding["properties"]) == {
        "schema", "namespace_id", "namespace_name", "workflow_id", "workflow_key", "role_key", "profile",
        "catalog_version", "catalog_sha256", "skills_revision", "runtime_ready",
    }
    assert binding["properties"]["runtime_ready"]["const"] is False
    assert set(generated["paths"]) == {f"{PATH}/{{namespace_id}}"}
    assert generated["paths"][f"{PATH}/{{namespace_id}}"]['get']["responses"]["422"]["content"][
        "application/json"]["schema"] == {"$ref": "#/components/schemas/BaseBindingInvalidRequest"}


@pytest.mark.parametrize("phrase", ["Unprocessable Entity", "Unprocessable Content"])
def test_binding_openapi_does_not_depend_on_python_status_phrase(monkeypatch, phrase):
    monkeypatch.setitem(http.client.responses, 422, phrase)
    assert base_binding_openapi() == json.loads(OUTPUT.read_text(encoding="utf-8"))


@pytest.mark.skipif(not os.environ.get("WORKFLOW_BASE_PACKAGE_TEST_ROOT"), reason="Private package is explicit opt-in")
def test_actual_private_git_pin_and_persisted_owner_binding(monkeypatch, registered_readers, installed, client):
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", os.environ["WORKFLOW_BASE_PACKAGE_TEST_ROOT"])
    config.get_settings.cache_clear()
    source_costs, validation_costs, totals = [], [], []
    load_source = base_binding.load_base_source
    installed_candidate = base_binding._installed_candidate

    def timed_source():
        start = time.perf_counter()
        result = load_source()
        source_costs.append(time.perf_counter() - start)
        return result

    def timed_candidate(*args):
        start = time.perf_counter()
        result = installed_candidate(*args)
        validation_costs.append(time.perf_counter() - start)
        return result

    monkeypatch.setattr(base_binding, "load_base_source", timed_source)
    monkeypatch.setattr(base_binding, "_installed_candidate", timed_candidate)
    bodies = []
    for _ in range(3):
        start = time.perf_counter()
        response = client.get(f"{PATH}/{installed['developer']}", headers=CATALOG_READER)
        totals.append(time.perf_counter() - start)
        assert response.status_code == 200, response.text
        bodies.append(response.json())
    assert len(source_costs) == 3 and len(validation_costs) == 6 and len(registered_readers["calls"]) == 3
    assert bodies[0] == bodies[1] == bodies[2]
    assert max(totals) < 5, "Actual pin plus double DB validation exceeded Fleet's 5s readback deadline"
    print(f"actual-pin binding costs: source_s={source_costs}, catalog_pass_s={validation_costs}, "
          f"total_http_s={totals}; auth HTTP mocked, isolated SQLite; no accepted runtime attestation")
    assert response.status_code == 200, response.text
    binding = response.json()["binding"]
    assert binding["skills_revision"] == BASE_SKILLS_REVISION
    assert binding["catalog_sha256"] == hashlib.sha256(
        base_source.CANDIDATE_PATH.read_bytes().replace(b"\r\n", b"\n"),
    ).hexdigest()
    assert binding["namespace_id"] == str(installed["developer"])
    assert binding["profile"] == "hermes-sdlc-developer" and binding["runtime_ready"] is False
    assert load_managed_catalog().catalog_version == 2
