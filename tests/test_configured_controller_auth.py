"""Actual Auth HTTP boundary, with a controlled issuer only in unit tests."""

import json

import httpx
import pytest

from project_workflow import config
from project_workflow.infrastructure import namespace_auth
from tests.test_configured_cli import CONTROLLER, WRITER, enroll
from tests.test_configured_cli import configured as configured

INTROSPECT = namespace_auth.introspect
HTTP_CLIENT = httpx.Client


@pytest.fixture
def issuer(configured, monkeypatch):
    state = {"status": 200, "role": "service_account", "subject": CONTROLLER,
             "scopes": ["project-workflow:read", "project-workflow:write"], "calls": 0}
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.test")
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", "https://auth.test")
    config.get_settings.cache_clear()

    def respond(request):
        assert str(request.url) == "https://auth.test/auth/tokens/introspect"
        assert request.headers["authorization"] == WRITER["Authorization"]
        assert request.headers["cache-control"] == "no-cache, no-store"
        state["calls"] += 1
        return httpx.Response(state["status"], json={
            "sub": state["subject"], "role": state["role"], "email": "controller@example.test",
            "scopes": state["scopes"]})

    monkeypatch.setattr(namespace_auth, "introspect", INTROSPECT)
    monkeypatch.setattr(namespace_auth.httpx, "Client", lambda **kwargs: HTTP_CLIENT(
        **kwargs, transport=httpx.MockTransport(respond)))
    return state


@pytest.mark.parametrize("configured", [
    ("project_manager", "draft"), ("analyst", "analysis"), ("architect", "decomposition"),
    ("developer", "initial"), ("developer", "rework"), ("reviewer", "delivery"),
    ("tester", "delivery"), ("devops", "delivery"),
], indirect=True)
def test_revoked_controller_cannot_replay_enrollment_or_read_history(configured, issuer):
    client, request = configured
    original = enroll(configured)
    assert enroll(configured) == original
    query = {"interaction_protocol": "configured-cli-v1", "namespace_id": request["namespace_id"],
             "task": request["task"]}
    assert client.get("/internal/runtime/history", headers=WRITER, params=query).status_code == 200
    assert issuer["calls"] == 3  # One fresh issuer read per request, including replay/history.
    issuer["status"] = 401
    assert client.post("/internal/runtime/assign", headers=WRITER, json=request).status_code == 401
    assert client.get("/internal/runtime/history", headers=WRITER, params=query).status_code == 401
    receipt = {"interaction_protocol": "configured-cli-v1", "workflow_receipt": {
        "reference": f"workflow-configured-cli:{original['execution_ref']}:1", "sha256": "a" * 64}}
    assert client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=receipt).status_code == 401


def test_readonly_controller_reads_but_cannot_enroll(configured, issuer):
    from project_workflow.interfaces.ui.routes.runtime_api import _authorized_service_credential

    client, request = configured
    enroll(configured)
    issuer["scopes"] = ["project-workflow:read"]
    authority = _authorized_service_credential(WRITER["Authorization"])
    assert authority is not None and not authority.can_assign
    assert client.post("/internal/runtime/assign", headers=WRITER, json=request).status_code == 403
    query = {"interaction_protocol": "configured-cli-v1", "namespace_id": request["namespace_id"],
             "task": request["task"]}
    assert client.get("/internal/runtime/history", headers=WRITER, params=query).status_code == 200


def test_registered_catalog_pat_cannot_become_an_assignment_controller(configured, issuer, monkeypatch):
    client, request = configured
    issuer["scopes"] = ["project-workflow:read"]
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON", json.dumps({CONTROLLER: "catalog"}))
    config.get_settings.cache_clear()
    response = client.get("/internal/runtime/profiles/single-task-v1/installation", headers=WRITER)
    assert response.status_code == 200 and len(response.json()["installation"]["bindings"]) == 7
    assert client.post("/internal/runtime/assign", headers=WRITER, json=request).status_code == 403


@pytest.mark.parametrize("mutation", ["human", "unregistered", "wrong-role", "extra-scope", "duplicate-scope"])
def test_controller_authority_cannot_come_from_email_or_token_value(configured, issuer, monkeypatch, mutation):
    client, request = configured
    if mutation == "human":
        issuer["role"] = "admin"
    elif mutation == "unregistered":
        issuer["subject"] = "11111111-1111-4111-8111-111111111111"
    elif mutation == "wrong-role":
        monkeypatch.setenv("PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON", json.dumps({CONTROLLER: "tester"}))
        config.get_settings.cache_clear()
    elif mutation == "extra-scope":
        issuer["scopes"].append("task-tracker:write")
    else:
        issuer["scopes"].append("project-workflow:read")
    assert client.post("/internal/runtime/assign", headers=WRITER, json=request).status_code == 403
