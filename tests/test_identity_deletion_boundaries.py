"""Private owner HTTP/Auth rejection boundaries; durable PG effects remain a separate gate."""

import asyncio
import time
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.domain.identity_deletion import ReferenceSummary
from project_workflow.infrastructure import identity_deletion_auth as owner_auth
from project_workflow.infrastructure.db import identity_deletion as owner_store
from project_workflow.infrastructure.db.identity_deletion import OwnerError
from project_workflow.infrastructure.identity_deletion_auth import Authority, authorize
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.routes import identity_deletion_api as route
from tests.test_identity_deletion import ISSUER, command, introspection, wire


@pytest.mark.parametrize("setting,value", [
    ("AUTH_INTERNAL_BASE_URL", "http://auth.internal.test/foreign-path"),
    ("AUTH_INTERNAL_BASE_URL", "http://user:synthetic-secret@auth.internal.test"),
    ("PROJECT_WORKFLOW_IDENTITY_DELETION_COORDINATOR_SUBJECTS", "not-a-uuid"),
])
def test_invalid_coordinator_configuration_never_contacts_auth(monkeypatch, setting, value):
    calls = wire(monkeypatch, introspection())
    monkeypatch.setenv(setting, value)
    config.get_settings.cache_clear()
    with pytest.raises(OwnerError) as rejected:
        asyncio.run(authorize("Bearer pdlc_pat_fixture", time.monotonic() + 9))
    assert (rejected.value.status, rejected.value.code) == (503, "identity_deletion_authorization_unavailable")
    assert not calls
    assert "synthetic-secret" not in str(rejected.value)


@pytest.mark.parametrize("authorization", [None, "", "Basic synthetic", "bearer pdlc_pat_fixture"])
def test_missing_bearer_authority_is_401_before_introspection(monkeypatch, authorization):
    calls = wire(monkeypatch, introspection())
    with pytest.raises(OwnerError) as rejected:
        asyncio.run(authorize(authorization, time.monotonic() + 9))
    assert (rejected.value.status, rejected.value.code) == (401, "identity_deletion_access_denied")
    assert not calls


@pytest.mark.parametrize("oversized", [False, True])
def test_auth_401_remains_denied_and_oversized_proof_is_not_an_identity(monkeypatch, oversized):
    payload = introspection()
    if oversized:
        payload["email"] = "synthetic-private-" + "x" * 17000
    calls = wire(monkeypatch, payload, status=200 if oversized else 401)
    with pytest.raises(OwnerError) as rejected:
        asyncio.run(authorize("Bearer pdlc_pat_fixture", time.monotonic() + 9))
    expected = (503, "identity_deletion_authorization_unavailable") if oversized else (
        401, "identity_deletion_access_denied")
    assert (rejected.value.status, rejected.value.code) == expected
    assert len(calls) == 1 and "synthetic-private" not in str(rejected.value)


@pytest.mark.parametrize("expired_after_effect", [False, True])
def test_private_ack_rechecks_original_authority_after_effect(monkeypatch, expired_after_effect):
    wall = {"now": time.time()}
    monkeypatch.setattr(owner_auth, "time", SimpleNamespace(time=lambda: wall["now"], monotonic=time.monotonic))
    original_expiry = wall["now"] + 1
    proof = Authority(ISSUER, time.monotonic() + 30, wall["now"] - 1, original_expiry)
    effects = []

    async def authority(*args):
        assert proof.current()
        return proof

    def effect(action, request, supplied):
        assert supplied is proof and supplied.current()
        effects.append((action, request.operation_id))
        if expired_after_effect:
            wall["now"] += 2
        return ReferenceSummary(request=request, revision=7, reference_count=3)

    monkeypatch.setattr(route, "authorize", authority)
    monkeypatch.setattr(route, "execute", effect)
    body = command()
    with TestClient(create_app()) as client:
        response = client.post(f"/api/internal/v1/user-deletions/{body['operation_id']}/check", json=body)
    assert response.headers["cache-control"] == "no-store"
    assert effects == [("check", UUID(body["operation_id"]))]
    assert proof.expires_at == original_expiry
    if expired_after_effect:
        assert response.status_code == 401
        assert response.json() == {"error": {"code": "identity_deletion_authority_expired"}}
    else:
        assert response.status_code == 200
        assert response.json()["revision"] == 7 and response.json()["reference_count"] == 3


def test_private_invalid_action_and_foreign_issuer_never_reach_storage(monkeypatch):
    calls = wire(monkeypatch, introspection())
    monkeypatch.setenv("AUTH_SESSION_SECRET", "synthetic-owner-http-session-secret-32-characters")
    monkeypatch.setenv("PROJECT_WORKFLOW_IDENTITY_LEGACY_ISSUER", ISSUER)
    config.get_settings.cache_clear()
    engine_calls = []

    def forbidden_engine():
        engine_calls.append("opened")
        raise AssertionError("Rejected private request must not open a storage transaction")

    monkeypatch.setattr(owner_store, "get_engine", forbidden_engine)
    body = command()
    path = f"/api/internal/v1/user-deletions/{body['operation_id']}"
    with TestClient(create_app()) as client:
        invalid = client.post(path + "/erase", json=body)
        assert invalid.status_code == 422
        assert invalid.json() == {"error": {"code": "invalid_identity_deletion_request"}}
        assert not calls
        body["identity"]["issuer"] = "https://foreign-authority.example.test"
        foreign = client.post(path + "/freeze", json=body, headers={"Authorization": "Bearer pdlc_pat_fixture"})
    assert foreign.status_code == 403
    assert foreign.json() == {"error": {"code": "identity_deletion_access_denied"}}
    assert invalid.headers["cache-control"] == foreign.headers["cache-control"] == "no-store"
    assert len(calls) == 1 and not engine_calls
