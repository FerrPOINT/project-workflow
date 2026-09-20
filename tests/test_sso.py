"""Fail-closed checks for the server-rendered OIDC boundary."""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_workflow.config import Settings
from project_workflow.interfaces.ui import sso


def _app(monkeypatch):
    settings = Settings(
        DATABASE_URL="postgresql+psycopg://unused@localhost/unused",
        AUTH_ISSUER="http://localhost:7701",
        AUTH_INTERNAL_BASE_URL="http://auth:7701",
        AUTH_PUBLIC_ORIGIN="http://localhost:8812",
        AUTH_SESSION_SECRET="test-only-secret-with-at-least-thirty-two-bytes",
    )
    monkeypatch.setenv("AUTH_ISSUER", settings.AUTH_ISSUER)
    monkeypatch.setattr(sso, "get_settings", lambda: settings)
    app = FastAPI()
    sso.install_sso(app)
    app.get("/")(lambda: {"ok": True})
    app.get("/api/tasks")(lambda: {"ok": True})
    app.post("/api/tasks")(lambda: {"ok": True})
    app.post("/internal/runtime/step")(lambda: {"ok": True})
    return app, settings


def test_pages_redirect_to_sso_and_api_denies_anonymous(monkeypatch):
    app, _ = _app(monkeypatch)
    with TestClient(app, follow_redirects=False) as client:
        page = client.get("/")
        assert page.status_code == 303
        assert page.headers["location"] == "/login?next=%2F"
        api = client.get("/api/tasks")
        assert api.status_code == 401
        assert client.post("/internal/runtime/step").status_code == 200


def test_broken_login_state_never_reflects_code_in_redirect(monkeypatch):
    app, _ = _app(monkeypatch)
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/sso/callback?code=private-code&state=bad")
        assert response.status_code == 401
        assert "private-code" not in response.text
        assert "location" not in response.headers


def test_central_outage_rejects_existing_session(monkeypatch):
    app, settings = _app(monkeypatch)
    original_client = httpx.AsyncClient

    def unavailable(_request):
        raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(sso.httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(unavailable), **kwargs,
    ))
    with TestClient(app, follow_redirects=False) as client:
        client.cookies.set("workflow_sso", sso._encode_cookie(settings, {"token": "sso-jwt"}))
        response = client.get("/api/tasks")
        assert response.status_code == 503
        assert "временно недоступен" in response.json()["error"]


def test_login_logout_and_canonical_origin(monkeypatch):
    app, settings = _app(monkeypatch)
    with TestClient(app, base_url="http://localhost:8812", follow_redirects=False) as client:
        login = client.get("/login?next=//outside.example")
        assert login.status_code == 303
        assert login.headers["location"].startswith("http://localhost:7701/oidc/authorize?")
        assert "workflow_oidc_state=" in login.headers["set-cookie"]
        transaction = sso._decode_cookie(settings, client.cookies.get("workflow_oidc_state"), 600)
        assert transaction is not None
        assert transaction["next"] == "/"

        logout = client.get("/logout")
        assert logout.status_code == 303
        assert logout.headers["location"] == "http://localhost:7701/oidc/logout?client_id=project-workflow"
        assert "workflow_sso=" in logout.headers["set-cookie"]

    with TestClient(app, base_url="http://127.0.0.1:8812", follow_redirects=False) as client:
        canonical = client.get("/api/tasks?state=open")
        assert canonical.status_code == 307
        assert canonical.headers["location"] == "http://localhost:8812/api/tasks?state=open"


def test_cookie_session_checks_identity_and_csrf(monkeypatch):
    app, settings = _app(monkeypatch)
    original_client = httpx.AsyncClient

    def identity(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/me"
        return httpx.Response(200, json={"id": "central-user"})

    monkeypatch.setattr(
        sso.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(identity), **kwargs),
    )
    with TestClient(app, follow_redirects=False) as client:
        client.cookies.set(
            "workflow_sso",
            sso._encode_cookie(settings, {"token": "sso-jwt"}),
        )
        assert client.get("/").status_code == 200
        assert client.post("/api/tasks").status_code == 403
        accepted = client.post("/api/tasks", headers={"origin": "http://localhost:8812"})
        assert accepted.status_code == 200


def test_personal_token_scopes_and_invalid_central_responses(monkeypatch):
    app, _ = _app(monkeypatch)
    original_client = httpx.AsyncClient
    response = {"status": 200, "body": {"sub": "user-1", "scopes": ["project-workflow:read"]}}

    def introspect(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/auth/tokens/introspect"
        return httpx.Response(response["status"], json=response["body"])

    monkeypatch.setattr(
        sso.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(introspect), **kwargs),
    )
    headers = {"authorization": "Bearer sdlc_pat_test"}
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/api/tasks", headers=headers).status_code == 200
        assert client.post("/api/tasks", headers=headers).status_code == 403

        response["body"] = {"sub": "user-1", "scopes": ["project-workflow:write"]}
        assert client.post("/api/tasks", headers=headers).status_code == 200

        response.update(status=401, body={})
        assert client.get("/api/tasks", headers=headers).status_code == 401

        response.update(status=500, body={})
        assert client.get("/api/tasks", headers=headers).status_code == 503

        response.update(status=200, body={"scopes": []})
        invalid = client.get("/api/tasks", headers=headers)
        assert invalid.status_code == 503
        assert "некорректный ответ" in invalid.json()["error"]


def test_callback_exchanges_code_and_sets_encrypted_session(monkeypatch):
    app, settings = _app(monkeypatch)
    original_client = httpx.AsyncClient

    def oidc(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oidc/token":
            return httpx.Response(
                200,
                json={"access_token": "access-token", "id_token": "id-token", "expires_in": 900},
            )
        assert request.url.path == "/auth/me"
        return httpx.Response(200, json={"id": "central-sub"})

    class SigningKey:
        key = object()

    class JwkClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_signing_key_from_jwt(self, token):
            assert token == "id-token"
            return SigningKey()

    monkeypatch.setattr(
        sso.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(oidc), **kwargs),
    )
    monkeypatch.setattr(sso.jwt, "PyJWKClient", JwkClient)
    monkeypatch.setattr(
        sso.jwt,
        "decode",
        lambda *_args, **_kwargs: {"nonce": "nonce-1", "sub": "central-sub"},
    )

    transaction = sso._encode_cookie(
        settings,
        {"state": "state-1", "nonce": "nonce-1", "verifier": "verifier-1", "next": "/workflows"},
    )
    with TestClient(app, follow_redirects=False) as client:
        client.cookies.set("workflow_oidc_state", transaction, path="/sso/callback")
        callback = client.get("/sso/callback?code=code-1&state=state-1")
        assert callback.status_code == 303
        assert callback.headers["location"] == "/workflows"
        session = sso._decode_cookie(settings, client.cookies.get("workflow_sso"), 900)
        assert session is not None
        assert session["token"] == "access-token"
        assert session["sub"] == "central-sub"


def test_sso_is_disabled_without_issuer(monkeypatch):
    """Standalone mode must keep UI and API available without Central Auth."""
    monkeypatch.delenv("AUTH_ISSUER", raising=False)
    app = FastAPI()
    sso.install_sso(app)
    app.get("/")(lambda: {"ok": True})
    app.get("/api/tasks")(lambda: {"ok": True})

    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/tasks").status_code == 200


def test_sso_configuration_and_cookie_validation_fail_closed(monkeypatch):
    settings = Settings(
        DATABASE_URL="postgresql+psycopg://unused@localhost/unused",
        AUTH_ISSUER="http://localhost:7701",
        AUTH_INTERNAL_BASE_URL="",
        AUTH_PUBLIC_ORIGIN="http://localhost:8812",
        AUTH_SESSION_SECRET="short",
    )
    with pytest.raises(RuntimeError, match="at least 32"):
        sso._cipher(settings)

    app = FastAPI()
    monkeypatch.setenv("AUTH_ISSUER", "http://localhost:7701")
    settings.AUTH_SESSION_SECRET = "test-only-secret-with-at-least-thirty-two-bytes"
    monkeypatch.setattr(sso, "get_settings", lambda: settings)
    with pytest.raises(RuntimeError, match="AUTH_INTERNAL_BASE_URL"):
        sso.install_sso(app)
    assert sso._decode_cookie(settings, "not-a-cookie", 60) is None
