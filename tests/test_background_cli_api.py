"""Controlled source-only runs through the real shared HTTP step/history routes."""

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from project_workflow import config
from project_workflow.infrastructure import background_admission, namespace_auth
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests._report_helpers import report_json
from tests.test_background_execution import execution as execution


@pytest.fixture
def api(execution, monkeypatch):
    _, admission, command = execution
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.fixture.invalid")
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", "https://auth.fixture.invalid")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "background-controlled-http-test-only")
    config.get_settings.cache_clear()
    calls = []

    def read(run, authorization, **options):
        assert run == admission.run_id and authorization == "Bearer fixture-agent"
        calls.append(options)
        return admission.model_copy(deep=True)

    monkeypatch.setattr(background_admission, "read", read)
    client = TestClient(create_app(), headers={"Authorization": "Bearer fixture-agent"})
    yield client, admission, command.model_dump(mode="json"), calls
    client.close()


def history_params(admission, **extra):
    return {"interaction_protocol": "configured-cli-v1", "background_run": admission.run_id,
            "namespace_id": admission.context.namespace_id, **extra}


def test_registered_backend_reads_saved_history_without_renewing_owner_or_agent_access(
        api, monkeypatch, supervisor_llm):
    from uuid import uuid4

    from project_workflow.infrastructure import base_auth

    client, admission, command, calls = api
    path = f"/internal/runtime/background/runs/{admission.run_id}/history"
    principal = namespace_auth.NamespacePrincipal(issuer="https://auth.fixture.invalid", subject=str(uuid4()))
    scopes = ["project-workflow:background:history:read"]
    monkeypatch.setattr(namespace_auth, "introspect", lambda *args, **kwargs: (principal, scopes))
    monkeypatch.setattr(base_auth, "registered_subjects", lambda: {principal.subject: "catalog"})
    assert client.get(path).status_code == 404
    assert client.post("/internal/runtime/step", json=command).status_code == 200
    supervisor_llm("PASS")
    for version in (1, 2):
        report = {**command, "report": report_json(f"Saved phase {version}"),
                  "operation_key": f"saved-phase-{version}", "expected_version": version}
        assert client.post("/internal/runtime/step", json=report).status_code == 200
    previous_calls = len(calls)
    def revoked(*args, **kwargs):
        raise namespace_auth.NamespaceAuthError(403)
    monkeypatch.setattr(background_admission, "read", revoked)
    response = client.get(path, params={"n": 1})
    assert response.status_code == 200, response.text
    first = response.json()["result"]
    assert first["project_id"] == admission.project_id and first["run_id"] == admission.run_id
    assert len(first["records"]) == 1 and first["records"][0]["phase_name"]
    assert first["records"][0]["verdict"] == "pass"
    older = client.get(path, params={"n": 1, "before_history_id": first["next_before"]})
    assert older.status_code == 200
    assert older.json()["result"]["records"][0]["history_id"] < first["records"][0]["history_id"]
    assert len(calls) == previous_calls
    for denied in (["project-workflow:read"], ["project-workflow:background:read"],
                   ["project-workflow:background:history:read", "project-workflow:background:write"]):
        scopes[:] = denied
        assert client.get(path).status_code == 403
    scopes[:] = ["project-workflow:background:history:read"]
    monkeypatch.setattr(base_auth, "registered_subjects", lambda: {})
    assert client.get(path).status_code == 403
    assert client.get("/internal/runtime/background/runs/not-a-run/history").status_code == 409


def test_shared_http_routes_complete_replay_and_paginate_without_tracker(api, supervisor_llm):
    client, admission, command, calls = api
    response = client.post("/internal/runtime/step", json=command)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["version"] == 1
    supervisor_llm("PASS")
    for version in range(1, 6):
        report = {**command, "report": report_json(f"Controlled phase {version}"),
                  "operation_key": f"http-phase-{version}", "expected_version": version}
        if version == 5:
            report["research_result"] = {"status": "incomplete", "summary": "Missing fixture source",
                                        "coverage": ["Controlled contract"], "limitations": ["No source access"]}
        response = client.post("/internal/runtime/step", json=report)
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["complete"] is (version == 5)
        replay = client.post("/internal/runtime/step", json=report)
        assert replay.status_code == 200 and replay.json()["result"] == result
        receipt = client.get("/internal/runtime/history", params=history_params(
            admission, operation_key=report["operation_key"]))
        assert receipt.status_code == 200 and receipt.json()["result"] == result
    page = client.get("/internal/runtime/history", params=history_params(admission, n=2))
    assert page.status_code == 200
    result = page.json()["result"]
    assert result["research_result"]["status"] == "incomplete" and len(result["records"]) == 2
    next_page = client.get("/internal/runtime/history", params=history_params(
        admission, n=2, before_history_id=result["next_before"]))
    assert next_page.status_code == 200
    assert next_page.json()["result"]["records"][0]["history_id"] < result["next_before"]
    assert calls[-1] == {"write": False, "namespace_id": command["namespace_id"], "active": False}
    assert calls[0] == {"write": True, "namespace_id": command["namespace_id"]}
    with SAUnitOfWork() as uow:
        assignment = uow.session.scalar(select(m.TaskRuntimeAssignment))
        assert assignment.business_task_ref is None and assignment.binding_ref is None


@pytest.mark.parametrize("route", ["step", "history"])
@pytest.mark.parametrize("status", [403, 503])
def test_http_admission_failure_is_redacted_and_creates_no_cursor(api, monkeypatch, route, status):
    client, admission, command, _ = api

    def denied(*args, **kwargs):
        raise namespace_auth.NamespaceAuthError(status)

    monkeypatch.setattr(background_admission, "read", denied)
    response = (client.post("/internal/runtime/step", json=command) if route == "step" else
                client.get("/internal/runtime/history", params=history_params(admission)))
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert "fixture-agent" not in response.text
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskRuntimeAssignment)) == 0


def test_launch_identity_change_before_commit_rolls_back_cursor(api, monkeypatch):
    client, admission, command, _ = api
    calls = 0

    def changed(*args, **kwargs):
        nonlocal calls
        calls += 1
        current = admission.model_copy(deep=True)
        if calls > 1:
            current.context.config_revision += 1
        return current

    monkeypatch.setattr(background_admission, "read", changed)
    response = client.post("/internal/runtime/step", json=command)
    assert response.status_code == 409
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskRuntimeAssignment)) == 0


@pytest.mark.parametrize("extra", [{"task": "FAKE-1"}, {"execution_ref": "fake"},
    {"assignment_operation_key": "fake"}, {"projection": "fleet-summary-v1"}, {"background_run": "bad"}])
def test_history_rejects_mixed_execution_selectors_before_admission(api, extra):
    client, admission, _, calls = api
    response = client.get("/internal/runtime/history", params=history_params(admission, **extra))
    assert response.status_code == 422 and not calls


def test_unknown_history_receipt_and_mixed_pagination_have_no_side_effect(api):
    client, admission, command, _ = api
    assert client.post("/internal/runtime/step", json=command).status_code == 200
    missing = client.get("/internal/runtime/history", params=history_params(admission, operation_key="unknown"))
    assert missing.status_code == 404
    mixed = client.get("/internal/runtime/history", params=history_params(
        admission, operation_key="unknown", before_history_id=1))
    assert mixed.status_code == 409


@pytest.mark.parametrize("field,value", [("task", "FAKE-1"), ("model", "forbidden"), ("start", True)])
def test_step_rejects_foreign_authority_before_admission(api, field, value):
    client, _, command, calls = api
    invalid = deepcopy(command)
    invalid[field] = value
    response = client.post("/internal/runtime/step", json=invalid)
    assert response.status_code == 422 and not calls
