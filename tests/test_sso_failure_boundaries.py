"""SSO failures must not create a session, retain authority, or conceal DB faults."""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from project_workflow.infrastructure import platform_auth
from project_workflow.infrastructure.request_clock import RequestClock
from project_workflow.interfaces.ui import project_admission, sso
from tests.test_sso import _app


def _central(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        sso.httpx, "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.parametrize("identity", [
    {"id": "human", "padding": "x" * 16384},
    {"id": ""},
    {"id": 17},
    {"id": None},
])
def test_unbounded_or_non_string_identity_cannot_reach_a_human_handler(monkeypatch, identity):
    app, _ = _app(monkeypatch)
    reached = []
    app.get("/api/protected")(lambda: reached.append(True) or {"ok": True})

    def central(request):
        assert request.url.path == "/auth/me"
        return httpx.Response(200, json=identity)

    _central(monkeypatch, central)
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/protected", headers={"Authorization": "Bearer test-session"})
    assert response.status_code == 503
    assert reached == []
    assert "padding" not in response.text


@pytest.mark.parametrize("sqlstate", ["42501", "40P01"])
def test_db_denial_restores_original_context_but_unrelated_failure_is_not_authorization(monkeypatch, sqlstate):
    app, settings = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "false")
    _central(monkeypatch, lambda request: httpx.Response(200, json={"id": "human", "role": "user"}))
    request = Request({
        "type": "http", "method": "GET", "scheme": "http", "path": "/api/tasks",
        "query_string": b"", "server": ("localhost", 8812),
        "headers": [(b"authorization", b"Bearer test-session")],
    })

    class DriverFailure(Exception):
        pass

    cause = DriverFailure("synthetic-private-database-diagnostic")
    cause.sqlstate = sqlstate
    database_error = DBAPIError(None, None, cause)
    original = RequestClock(time.monotonic() + 30, time.time() + 30)

    async def exercise():
        token = sso.current_clock.set(original)
        try:
            async def handler(_request):
                active = sso.current_clock.get()
                assert active is not None and active is not original
                active.require_current()
                raise database_error

            middleware = sso._SsoMiddleware(app, settings)
            if sqlstate == "42501":
                response = await middleware.dispatch(request, handler)
                assert response.status_code == 403
                assert b"synthetic-private" not in response.body
            else:
                with pytest.raises(DBAPIError) as error:
                    await middleware.dispatch(request, handler)
                assert error.value is database_error
            assert sso.current_clock.get() is original
        finally:
            sso.current_clock.reset(token)

    asyncio.run(exercise())


def test_application_proof_expiring_during_handler_cannot_publish_success(monkeypatch):
    app, settings = _app(monkeypatch, AUTH_APPLICATION_ACCESS_REQUIRED=True)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "false")
    now = datetime.now(timezone.utc)
    clock = {"now": now}
    monkeypatch.setattr(platform_auth, "_utc_now", lambda: clock["now"])
    proof = {"schema_version": 1, "issuer": settings.AUTH_ISSUER, "subject": "human", "role": "user",
             "applications": ["project-workflow"], "revision": 1, "enforced": True,
             "observed_at": now.isoformat(), "expires_at": (now + timedelta(seconds=30)).isoformat()}
    _central(monkeypatch, lambda request: httpx.Response(
        200, json={"id": "human", "status": "active", "role": "user", "application_access": proof},
    ))
    reached = []

    @app.get("/api/slow")
    async def slow(request: Request):
        assert request.state.central_access.is_current()
        reached.append(request.state.central_subject)
        clock["now"] = now + timedelta(seconds=31)
        return {"private_success": True}

    with TestClient(app, follow_redirects=False) as client:
        headers = {"Authorization": "Bearer test-session"}
        assert client.get("/api/tasks", headers=headers).status_code == 200
        response = client.get("/api/slow", headers=headers)
        assert response.status_code == 503
        assert reached == ["human"]
        assert "private_success" not in response.text
        clock["now"] = now
        assert client.get("/api/tasks", headers=headers).status_code == 200


@pytest.mark.parametrize("identity,status", [
    ({"id": "human", "status": "disabled", "role": "user"}, 403),
    ({"id": "human", "status": "active", "role": 17}, 503),
])
def test_project_policy_requires_active_identity_and_typed_role_before_owner_rpc(monkeypatch, identity, status):
    app, _ = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true")
    _central(monkeypatch, lambda request: httpx.Response(200, json=identity))

    async def unexpected(*args, **kwargs):
        pytest.fail("Invalid human authority must not reach the project owner")

    monkeypatch.setattr(project_admission, "confirm", unexpected)
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/tasks", headers={"Authorization": "Bearer test-session"})
    assert response.status_code == status


@pytest.mark.parametrize("clock_case", ["future", "stale", "invalid_observed", "invalid_expiry"])
def test_pat_project_clock_must_be_fresh_before_owner_rpc(monkeypatch, clock_case):
    app, _ = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true")
    now = datetime.now(timezone.utc)
    identity = {"sub": "human", "subject_role": "user", "scopes": ["project-workflow:read"],
                "observed_at": now.isoformat(), "expires_at": (now + timedelta(seconds=30)).isoformat()}
    if clock_case == "future":
        identity["observed_at"] = (now + timedelta(seconds=5)).isoformat()
    elif clock_case == "stale":
        identity["observed_at"] = (now - timedelta(seconds=65)).isoformat()
    elif clock_case == "invalid_observed":
        identity["observed_at"] = "not-a-timestamp"
    else:
        identity["expires_at"] = "not-a-timestamp"

    def introspect(request):
        assert request.url.path == "/auth/tokens/introspect"
        assert request.url.params["include_lifetime"] == "true"
        return httpx.Response(200, json=identity)

    _central(monkeypatch, introspect)

    async def unexpected(*args, **kwargs):
        pytest.fail("An invalid original PAT clock must not reach the project owner")

    monkeypatch.setattr(project_admission, "confirm", unexpected)
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/tasks", headers={"Authorization": "Bearer sdlc_pat_test"})
    assert response.status_code == 503


def test_boolean_jwt_expiry_is_not_an_integer_project_permit(monkeypatch):
    app, _ = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true")
    _central(monkeypatch, lambda request: httpx.Response(
        200, json={"id": "human", "status": "active", "role": "user"},
    ))

    async def unexpected(*args, **kwargs):
        pytest.fail("Boolean JWT expiry must not become a project permit")

    monkeypatch.setattr(project_admission, "confirm", unexpected)
    token = jwt.encode({"exp": True}, key=None, algorithm="none")
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/tasks", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 503


@pytest.mark.parametrize("failure,expected,calls", [
    ("valid", 303, ["/oidc/token", "/auth/me"]),
    ("exchange_denied", 401, ["/oidc/token"]),
    ("wrong_nonce", 401, ["/oidc/token"]),
    ("wrong_subject", 401, ["/oidc/token", "/auth/me"]),
    ("session_revoked", 401, ["/oidc/token", "/auth/me"]),
    ("token_missing", 503, ["/oidc/token"]),
    ("id_token_invalid", 503, ["/oidc/token"]),
    ("network_error", 503, ["/oidc/token"]),
])
def test_oidc_callback_validates_signed_nonce_and_current_subject_before_cookie(monkeypatch, failure, expected, calls):
    app, settings = _app(monkeypatch)
    key = ec.generate_private_key(ec.SECP256R1())
    transaction = {}
    now = int(time.time())
    claims = {"iss": settings.AUTH_ISSUER, "aud": "project-workflow", "sub": "human",
              "exp": now + 300}
    contacted = []

    def central(request):
        contacted.append(request.url.path)
        if request.url.path == "/oidc/token":
            if failure == "network_error":
                raise httpx.ReadTimeout("synthetic-private-exchange-error", request=request)
            if failure == "exchange_denied":
                return httpx.Response(401, json={"private": "synthetic-private-exchange-error"})
            form = parse_qs(request.content.decode())
            assert form["code_verifier"] == [transaction["verifier"]]
            assert form["client_id"] == ["project-workflow"]
            assert form["redirect_uri"] == [settings.AUTH_PUBLIC_ORIGIN + "/sso/callback"]
            nonce = "foreign-nonce" if failure == "wrong_nonce" else transaction["nonce"]
            signed = jwt.encode({**claims, "nonce": nonce}, key, algorithm="ES256")
            if failure == "token_missing":
                return httpx.Response(200, json={"id_token": signed})
            return httpx.Response(200, json={"access_token": "synthetic-private-access-token",
                "id_token": "not-a-jwt" if failure == "id_token_invalid" else signed, "expires_in": 300})
        assert request.url.path == "/auth/me"
        assert request.headers["authorization"] == "Bearer synthetic-private-access-token"
        return httpx.Response(401 if failure == "session_revoked" else 200,
                              json={"id": "other-human" if failure == "wrong_subject" else "human"})

    class LocalJwk:
        def __init__(self, url, **kwargs):
            assert url == settings.AUTH_INTERNAL_BASE_URL + "/oidc/jwks"

        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=key.public_key())

    _central(monkeypatch, central)
    monkeypatch.setattr(sso.jwt, "PyJWKClient", LocalJwk)
    with TestClient(app, follow_redirects=False) as client:
        transaction_name = sso.cookie_name(settings, "workflow_oidc_state")
        session_name = sso.cookie_name(settings, "workflow_sso")
        login = client.get("/login?next=/api/tasks")
        assert login.status_code == 303
        pending = sso._decode_cookie(settings, client.cookies.get(transaction_name), 600)
        assert pending is not None
        transaction.update(pending)
        response = client.get("/sso/callback", params={"state": transaction["state"], "code": "synthetic-private-code"})
        assert response.status_code == expected
        assert contacted == calls
        if failure == "valid":
            assert response.headers["location"] == "/api/tasks"
            session = sso._decode_cookie(settings, client.cookies.get(session_name), 300)
            assert session is not None and session["sub"] == "human"
            assert session["token"] == "synthetic-private-access-token"
            assert client.cookies.get(transaction_name) is None
            assert response.headers["cache-control"] == "no-store"
            assert "synthetic-private" not in response.headers["set-cookie"]
        else:
            assert client.cookies.get(session_name) is None
            assert all(not row.startswith(session_name + "=") for row in response.headers.get_list("set-cookie"))
            assert "location" not in response.headers
            assert "synthetic-private" not in response.text


def test_shared_policy_without_auth_refuses_startup(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true")
    monkeypatch.delenv("AUTH_ISSUER", raising=False)
    app = FastAPI()
    with pytest.raises(RuntimeError, match="requires central authentication"):
        sso.install_sso(app)
    assert not app.user_middleware


def test_explicit_disabled_settings_do_not_install_partial_sso_routes(monkeypatch):
    _, settings = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "false")
    monkeypatch.setattr(sso, "get_settings", lambda: settings.model_copy(update={"AUTH_ISSUER": ""}))
    app = FastAPI()
    sso.install_sso(app)
    assert not app.user_middleware
    assert not {"/login", "/sso/callback", "/logout"}.intersection(route.path for route in app.routes)
