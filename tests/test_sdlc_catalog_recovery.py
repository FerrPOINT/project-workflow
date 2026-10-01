"""Recovery keeps versioned catalogs and native continuation fences immutable."""

from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from project_workflow import build_provenance, config
from project_workflow.infrastructure.db import models
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog
from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.routes import runtime_api
from tests.test_managed_catalog import _install_frozen_v1
from tests.test_runtime_api import _assignment, _bind_payload, _headers, _step_payload
from tests.test_runtime_assignment_contract import TEST_RUNTIME_COMPATIBILITY, _continuation

OWNER_TOKEN = "recovery-assignment-owner-token-123456789"
RUNTIME_TOKEN = "recovery-execution-runtime-token-123456789"


@pytest.fixture
def bound_runtime(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"developer": OWNER_TOKEN}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"developer": RUNTIME_TOKEN}))
    config.get_settings.cache_clear()
    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor", lambda: dict(TEST_RUNTIME_COMPATIBILITY))
    monkeypatch.setattr(runtime_api, "runtime_compatibility_descriptor", lambda: dict(TEST_RUNTIME_COMPATIBILITY))
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow)
        project = uow.projects.get_by_cli_command("workflow-developer")
        project_id = project.id
    with TestClient(create_app()) as client:
        request = {**_assignment("DV-901", "recovery-initial", "developer"),
                   "mode_key": "initial", "stage_key": "development"}
        assigned = client.post("/internal/runtime/assign", headers=_headers(OWNER_TOKEN), json=request)
        assert assigned.status_code == 200, assigned.text
        response = client.post("/internal/runtime/bind", headers=_headers(OWNER_TOKEN),
                               json=_bind_payload(assigned.json()["result"]))
        assert response.status_code == 200, response.text
        yield client, project_id, response.json()["result"]


def _snapshot(project_id):
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DV-901", project_id=project_id)
        return (task.to_dict(), [item.to_dict() for item in uow.tasks.list_assignments(task.id)],
                [item.to_dict() for item in uow.tasks.list_phase_events(task.id)])


def _prepare(client, request):
    response = client.post("/internal/runtime/rebind", headers=_headers(OWNER_TOKEN), json=request)
    assert response.status_code == 200, response.text
    return response.json()["result"]


def _confirm(client, prepared, request):
    response = client.post("/internal/runtime/bind", headers=_headers(OWNER_TOKEN),
                           json=_bind_payload(prepared, binding_ref=request["next_binding_ref"],
                                              hermes_run_ref=request["next_hermes_run_ref"]))
    assert response.status_code == 200, response.text
    return response.json()["result"]


def test_http_continuation_requires_owner_bind_and_preserves_phase_history(bound_runtime):
    client, project_id, bound = bound_runtime
    before = _snapshot(project_id)
    request = _continuation(bound)
    prepared = _prepare(client, request)
    replay = _prepare(client, request)
    assert replay == prepared
    assert prepared["binding_state"] == "unbound"
    premature = client.post("/internal/runtime/step", headers=_headers(RUNTIME_TOKEN),
                            json=_step_payload({**prepared, "binding_ref": request["next_binding_ref"],
                                                "hermes_run_ref": request["next_hermes_run_ref"]}))
    assert premature.status_code == 409
    confirmed = _confirm(client, prepared, request)
    for key in ("task_key", "mode_id", "mode_key", "execution_scope", "cycle_number",
                "attempt_number", "current_phase_id", "current_phase_code"):
        assert confirmed[key] == bound[key]
    assert confirmed["assignment_revision"] == bound["assignment_revision"] + 1
    query = client.post("/internal/runtime/step", headers=_headers(RUNTIME_TOKEN), json=_step_payload(confirmed))
    assert query.status_code == 200, query.text
    assert query.json()["result"]["phase_contract"]["allowed_tools"] == [
        "workflow", "history", "context", "skills", "question", "workspace_read", "checkpoint"]
    stale = client.post("/internal/runtime/step", headers=_headers(RUNTIME_TOKEN), json=_step_payload(bound))
    assert stale.status_code == 409
    after = _snapshot(project_id)
    assert after[2] == before[2]
    assert after[1][0] == before[1][0]
    assert len(after[1]) == 2


@pytest.mark.parametrize("token", [None, RUNTIME_TOKEN])
def test_http_continuation_cannot_use_execution_or_missing_credentials(bound_runtime, token):
    client, project_id, bound = bound_runtime
    before = _snapshot(project_id)
    response = client.post("/internal/runtime/rebind", headers=_headers(token) if token else {},
                           json=_continuation(bound))
    assert response.status_code == 401
    assert _snapshot(project_id) == before


@pytest.mark.parametrize("tamper", ["wrong_checkpoint_owner", "wrong_checkpoint_run", "wrong_checkpoint_kind",
                                    "duplicate_checkpoint", "changed_frozen_input", "reused_assignment",
                                    "reused_binding", "reused_run"])
def test_http_continuation_rejects_checkpoint_or_identity_tampering_without_mutation(bound_runtime, tamper):
    client, project_id, bound = bound_runtime
    before = _snapshot(project_id)
    request = copy.deepcopy(_continuation(bound))
    if tamper == "wrong_checkpoint_owner":
        request["checkpoint_owner_assignment_ref"] = "assignment:foreign"
    elif tamper == "wrong_checkpoint_run":
        request["checkpoint_hermes_run_ref"] = "run:foreign"
    elif tamper == "wrong_checkpoint_kind":
        request["exact_input_refs"][-1]["kind"] = "business-phase-checkpoint"
    elif tamper == "duplicate_checkpoint":
        request["exact_input_refs"].append({**request["exact_input_refs"][-1], "ref": "receipt:another"})
    elif tamper == "changed_frozen_input":
        request["exact_input_refs"][0]["revision"] = "changed"
    else:
        next_key, old_key = {
            "reused_assignment": ("next_assignment_ref", "assignment_ref"),
            "reused_binding": ("next_binding_ref", "binding_ref"),
            "reused_run": ("next_hermes_run_ref", "hermes_run_ref"),
        }[tamper]
        request[next_key] = bound[old_key]
    response = client.post("/internal/runtime/rebind", headers=_headers(OWNER_TOKEN), json=request)
    assert response.status_code == 409, response.text
    assert _snapshot(project_id) == before


def test_prepared_continuation_cannot_bind_against_changed_capability_pins(bound_runtime, monkeypatch):
    client, project_id, bound = bound_runtime
    request = _continuation(bound)
    prepared = _prepare(client, request)
    before = _snapshot(project_id)
    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor",
                        lambda: {**TEST_RUNTIME_COMPATIBILITY, "capabilitySha256": "f" * 64})
    response = client.post("/internal/runtime/bind", headers=_headers(OWNER_TOKEN),
                           json=_bind_payload(prepared, binding_ref=request["next_binding_ref"],
                                              hermes_run_ref=request["next_hermes_run_ref"]))
    assert response.status_code == 409
    assert "compatibility changed" in response.json()["error"]
    assert _snapshot(project_id) == before
    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor", lambda: dict(TEST_RUNTIME_COMPATIBILITY))
    confirmed = _confirm(client, prepared, request)
    assert confirmed["binding_state"] == "bound"


def test_late_first_continuation_replay_cannot_replace_second_checkpoint(bound_runtime):
    client, project_id, bound = bound_runtime
    first_request = _continuation(bound)
    first = _confirm(client, _prepare(client, first_request), first_request)
    checkpoint = {"kind": "tech-execution-terminal-receipt", "ref": "receipt:second",
                  "revision": "second", "hash": "b" * 64}
    second_request = _continuation(
        first, operation_key="continue:second", run_sequence=2,
        next_assignment_ref="assignment:second", next_binding_ref="binding:second", next_hermes_run_ref="run:second",
        checkpoint_ref=checkpoint["ref"], checkpoint_revision=checkpoint["hash"],
        lease_generation=first["lease_generation"] + 1,
        exact_input_refs=[*[item for item in first["exact_input_refs"]
                           if item["kind"] != "tech-execution-terminal-receipt"], checkpoint],
    )
    second = _confirm(client, _prepare(client, second_request), second_request)
    before = _snapshot(project_id)
    delayed = client.post("/internal/runtime/rebind", headers=_headers(OWNER_TOKEN), json=first_request)
    assert delayed.status_code == 409
    assert "superseded" in delayed.json()["error"]
    assert _snapshot(project_id) == before
    assert second["current_phase_code"] == bound["current_phase_code"]
    assert second["assignment_revision"] == bound["assignment_revision"] + 2


def test_partial_v2_adoption_rolls_back_all_role_switches_and_preserves_legacy_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'partial-adoption.db'}"
    with SAUnitOfWork(url) as uow:
        ensure_schema(uow.session.get_bind())
        _install_frozen_v1(uow)
        workflow = next(item for item in uow.workflows.list() if item.key == "hermes-sdlc:developer")
        uow.workflows.create_mode({"workflow_id": workflow.id, "key": "initial", "name": "Partial v2",
                                   "mode_order": 1, "catalog_version": 2, "role_key": "developer",
                                   "execution_scopes": ["delivery", "aggregate"], "tech_workspace_policy": "required"})
    def snapshot():
        with SAUnitOfWork(url) as uow:
            return tuple(tuple(tuple(getattr(row, column.name) for column in model.__table__.columns)
                               for row in uow.session.scalars(select(model).order_by(model.id)))
                         for model in (models.Workflow, models.WorkflowMode, models.Phase,
                                       models.PhaseInstruction, models.Project))
    before = snapshot()
    with pytest.raises(ValueError, match="Partial managed catalog adoption"):
        with SAUnitOfWork(url) as uow:
            ensure_managed_catalog(uow)
    assert snapshot() == before
    with SAUnitOfWork(url) as uow:
        assert all(item.active_catalog_version == 1 for item in uow.workflows.list())
