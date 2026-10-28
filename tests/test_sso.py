"""Fail-closed checks for the server-rendered OIDC boundary."""

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_workflow.config import Settings
from project_workflow.interfaces.ui import sso


@pytest.mark.parametrize("result", ["error", "login-required"])
def test_callback_entry_reports_result_before_any_product_route(monkeypatch, result):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the executable bridge regression")
    app, _ = _app(monkeypatch, UI_PLATFORM_ORIGIN="http://portal.test")
    with TestClient(app, follow_redirects=False) as client:
        if result == "login-required":
            from urllib.parse import parse_qs, urlparse

            login = client.get("/login?next=/phases&silent=1")
            state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
            response = client.get("/sso/callback", params={"error": "login_required", "state": state})
        else:
            response = client.get("/sso/callback?error=access_denied&state=foreign")
        assert response.status_code == 401
        check = subprocess.run(
            [node, str(Path(__file__).resolve().parents[1] / "scripts/check_sso_entry.mjs")],
            input=json.dumps({"html": response.text, "expected": result}), text=True, capture_output=True, check=False,
        )
        assert check.returncode == 0, check.stderr


def _app(monkeypatch, **overrides):
    settings = Settings(
        DATABASE_URL="postgresql+psycopg://unused@localhost/unused",
        AUTH_ISSUER="http://localhost:7701",
        AUTH_INTERNAL_BASE_URL="http://auth:7701",
        AUTH_PUBLIC_ORIGIN="http://localhost:8812",
        AUTH_SESSION_SECRET="test-only-secret-with-at-least-thirty-two-bytes",
    )
    settings = settings.model_copy(update=overrides)
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
        assert page.headers["location"] == "/login?next=%2F&silent=1"
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
        client.cookies.set(
            sso.cookie_name(settings, "workflow_sso"), sso._encode_cookie(settings, {"token": "sso-jwt"}),
        )
        response = client.get("/api/tasks")
        assert response.status_code == 503
        assert "временно недоступен" in response.json()["error"]


def test_login_logout_and_canonical_origin(monkeypatch):
    app, settings = _app(monkeypatch)
    with TestClient(app, base_url="http://localhost:8812", follow_redirects=False) as client:
        login = client.get("/login?next=//outside.example")
        assert login.status_code == 303
        assert login.headers["location"].startswith("http://localhost:7701/oidc/authorize?")
        transaction_name = sso.cookie_name(settings, "workflow_oidc_state")
        assert transaction_name + "=" in login.headers["set-cookie"]
        transaction = sso._decode_cookie(settings, client.cookies.get(transaction_name), 600)
        assert transaction is not None
        assert transaction["next"] == "/"

        logout = client.get("/logout")
        assert logout.status_code == 303
        assert logout.headers["location"] == "http://localhost:7701/oidc/logout?client_id=project-workflow"
        assert sso.cookie_name(settings, "workflow_sso") + "=" in logout.headers["set-cookie"]

    with TestClient(app, base_url="http://127.0.0.1:8812", follow_redirects=False) as client:
        canonical = client.get("/api/tasks?state=open")
        assert canonical.status_code == 307
        assert canonical.headers["location"] == "http://localhost:8812/api/tasks?state=open"


@pytest.mark.parametrize("extra,origin,expected", [
    ([], "http://localhost:8812", 200),
    ([], "https://192.168.1.69:18443", 403),
    (["https://192.168.1.69:18443"], "http://localhost:8812", 200),
    (["https://192.168.1.69:18443"], "https://192.168.1.69:18443", 200),
    (["https://192.168.1.69:18443"], "https://192.168.1.69:18444", 403),
    (["https://192.168.1.69:18443"], "http://192.168.1.69:18443", 403),
    (["https://192.168.1.69:18443"], "https://evil.example", 403),
    (["https://192.168.1.69:18443"], "null", 403),
])
def test_cookie_session_checks_identity_and_csrf(monkeypatch, extra, origin, expected):
    app, settings = _app(monkeypatch, AUTH_BROWSER_ORIGINS=extra)
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
            sso.cookie_name(settings, "workflow_sso"),
            sso._encode_cookie(settings, {"token": "sso-jwt"}),
        )
        assert client.get("/").status_code == 200
        assert client.post("/api/tasks").status_code == 403
        accepted = client.post("/api/tasks", headers={"origin": origin})
        assert accepted.status_code == expected


@pytest.mark.parametrize("prefix", ["sdlc_pat_", "pdlc_pat_"])
def test_personal_token_scopes_and_invalid_central_responses(monkeypatch, prefix):
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
    headers = {"authorization": f"Bearer {prefix}test"}
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


@pytest.mark.parametrize("platform_origin,platform_return,expected", [
    ("", "", "/workflows"),
    ("http://localhost:7990", "/workflow/phases?namespace_id=7", "http://localhost:7990/workflow/phases?namespace_id=7"),
    ("http://localhost:7990", "//external.test/path", "http://localhost:7990/"),
    ("", "/workflow/phases", "/workflows"),
])
def test_callback_exchanges_code_and_sets_encrypted_session(monkeypatch, platform_origin, platform_return, expected):
    app, settings = _app(monkeypatch, UI_PLATFORM_ORIGIN=platform_origin)
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
        {"state": "state-1", "nonce": "nonce-1", "verifier": "verifier-1", "next": "/workflows",
         "platform_return": platform_return},
    )
    with TestClient(app, follow_redirects=False) as client:
        client.cookies.set(sso.cookie_name(settings, "workflow_oidc_state"), transaction, path="/sso/callback")
        callback = client.get("/sso/callback?code=code-1&state=state-1")
        assert callback.status_code == 303
        assert callback.headers["location"] == expected
        session = sso._decode_cookie(settings, client.cookies.get(sso.cookie_name(settings, "workflow_sso")), 900)
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


@pytest.mark.parametrize("prefix", ["sdlc_pat_", "pdlc_pat_"])
def test_machine_principal_cannot_enter_human_routes_even_with_write_scope(monkeypatch, prefix):
    app, _ = _app(monkeypatch)
    original_client = httpx.AsyncClient
    identity = {
        "sub": "registered-reader", "role": "admin",
        "scopes": ["project-workflow:read", "project-workflow:write"],
    }
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE__MACHINE_SUBJECTS", "registered-reader")
    monkeypatch.setattr(
        sso.httpx, "AsyncClient",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=identity)), **kwargs,
        ),
    )
    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {prefix}test"}
        assert client.get("/api/tasks", headers=headers).status_code == 403
        assert client.post("/api/tasks", headers=headers).status_code == 403
        identity["sub"] = "human"
        assert client.get("/api/tasks", headers=headers).status_code == 200
        identity["role"] = "service_account"
        assert client.get("/api/tasks", headers=headers).status_code == 403
def test_silent_login_requests_none_and_handles_matching_missing_session(monkeypatch):
    from urllib.parse import parse_qs, urlparse

    app, settings = _app(monkeypatch, UI_PLATFORM_ORIGIN="http://localhost:7990")
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/login?next=/phases&silent=1")
        params = parse_qs(urlparse(response.headers["location"]).query)
        assert params["prompt"] == ["none"]
        callback = client.get("/sso/callback", params={"error": "login_required", "state": params["state"][0]})
        assert callback.status_code == 401
        assert "Войти через SSO" in callback.text
        assert "data-platform-login-required" in callback.text.partition("<head>")[0]
        assert client.cookies.get(sso.cookie_name(settings, "workflow_sso")) is None
        assert client.cookies.get(sso.cookie_name(settings, "workflow_oidc_state")) is None


def test_silent_error_cannot_bypass_oidc_state(monkeypatch):
    app, _ = _app(monkeypatch)
    with TestClient(app, follow_redirects=False) as client:
        client.get("/login?silent=1")
        response = client.get("/sso/callback?error=login_required&state=foreign")
        assert response.status_code == 401
        assert "Вход не подтверждён" in response.text
        assert "data-platform-login-required" not in response.text.partition("<head>")[0]


@pytest.mark.parametrize("code,error", [("", "access_denied"), ("unexpected-code", "login_required"), ("", "")])
def test_matching_silent_state_does_not_admit_invalid_callback_payload(monkeypatch, code, error):
    from urllib.parse import parse_qs, urlparse

    app, settings = _app(monkeypatch)
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/login?silent=1")
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        response = client.get("/sso/callback", params={"state": state, "code": code, "error": error})
        assert response.status_code == 401
        assert client.cookies.get(sso.cookie_name(settings, "workflow_sso")) is None
        assert "data-platform-login-required" not in response.text.partition("<head>")[0]


def test_canonical_loopback_does_not_redirect_to_itself(monkeypatch):
    app, _ = _app(monkeypatch, AUTH_PUBLIC_ORIGIN="http://127.0.0.1:8812")
    with TestClient(app, base_url="http://127.0.0.1:8812", follow_redirects=False) as client:
        response = client.get("/phases?namespace_id=7")
        assert response.status_code == 303
        assert response.headers["location"].startswith("/login?")
    with TestClient(app, base_url="http://localhost:8812", follow_redirects=False) as client:
        response = client.get("/phases?namespace_id=7")
        assert response.status_code == 307
        assert response.headers["location"] == "http://127.0.0.1:8812/phases?namespace_id=7"


def test_current_role_and_apps_apply_to_the_same_open_session(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from fastapi import Depends
    app, settings = _app(monkeypatch, AUTH_APPLICATION_ACCESS_REQUIRED=True)
    app.post("/api/configuration", dependencies=[Depends(sso.require_administrator)])(lambda: {"ok": True})
    from project_workflow.interfaces.ui.project_admission import space_admission
    app.get("/api/v1/space-admission")(space_admission)
    state = {"role": "user", "apps": ["project-workflow"], "proof": True, "enforced": True}
    original_client = httpx.AsyncClient

    def identity(_request):
        now = datetime.now(timezone.utc)
        value = {"id": "central-user", "role": state["role"]}
        if state["proof"]:
            value["application_access"] = {"schema_version": 1, "issuer": settings.AUTH_ISSUER,
                "subject": "central-user", "role": state["role"], "applications": state["apps"],
                "revision": 1, "enforced": state["enforced"], "observed_at": now.isoformat(),
                "expires_at": (now+timedelta(seconds=60)).isoformat()}
        return httpx.Response(200, json=value)

    monkeypatch.setattr(sso.httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(identity), **kwargs))
    with TestClient(app, follow_redirects=False) as client:
        headers = {"authorization": "Bearer one-verified-session"}
        assert client.get("/api/tasks", headers=headers).status_code == 200
        display = client.get("/api/v1/space-admission", headers=headers)
        assert display.status_code == 200 and display.json()["enforced"] is True
        assert 0 < display.json()["remaining_millis"] <= 60_000
        assert display.headers["cache-control"] == "private, no-store"
        assert client.post("/api/configuration", headers=headers).status_code == 403
        state["role"] = "admin"
        assert client.post("/api/configuration", headers=headers).status_code == 200
        state["role"] = "user"
        assert client.post("/api/configuration", headers=headers).status_code == 403
        state["apps"] = []
        assert client.get("/api/tasks", headers=headers).status_code == 403
        page = client.get("/", headers=headers)
        assert page.status_code == 403
        assert "Нет доступа" in page.text
        assert "Войти через SSO" not in page.text
        assert "location" not in page.headers
        state["apps"] = ["project-workflow"]
        state["proof"] = False
        assert client.get("/api/tasks", headers=headers).status_code == 403
        state["proof"] = True
        state["enforced"] = False
        assert client.get("/api/tasks", headers=headers).status_code == 403
        state["enforced"] = True
        state["apps"] = ["wrong/path"]
        assert client.get("/api/tasks", headers=headers).status_code == 503
        state["apps"] = ["project-workflow"]
        from project_workflow.domain.project_admission import SpaceAccessDenied

        def expired_before_dispatch(_access):
            raise SpaceAccessDenied("Original application admission expired")

        monkeypatch.setattr(sso.RequestClock, "from_access", expired_before_dispatch)
        assert client.get("/api/tasks", headers=headers).status_code == 403
        assert sso.current_clock.get() is None


def test_real_configuration_routes_declare_administrator_dependency():
    from project_workflow.interfaces.ui.app import create_app
    app = create_app()
    methods = {"POST", "PUT", "DELETE"}
    configuration = {"api_phase_create", "api_phase_delete", "api_phase_batch_order", "api_phase_update",
        "api_workflow_create", "api_workflow_update", "api_workflow_delete", "api_namespace_create",
        "api_namespace_update", "api_namespace_delete", "api_instruction_create", "api_instruction_update",
        "api_instruction_delete", "api_instructions_reorder"}
    seen = set()
    for route in app.routes:
        if getattr(route, "name", None) in configuration:
            assert methods.intersection(route.methods)
            assert any(dependency.call is sso.require_administrator for dependency in route.dependant.dependencies)
            seen.add(route.name)
    assert seen == configuration


@pytest.mark.parametrize("origin", [
    "null", "*", "https://*.example", "https://user:pass@example.test", "https://example.test/path",
    "https://example.test?query", "https://example.test#fragment", "https://example.test:bad",
])
def test_browser_origin_configuration_rejects_non_origins(origin):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(DATABASE_URL="sqlite:///:memory:", AUTH_BROWSER_ORIGINS=[origin])


def test_browser_origin_configuration_normalizes_exact_origins():
    settings = Settings(DATABASE_URL="sqlite:///:memory:", AUTH_BROWSER_ORIGINS=["https://EXAMPLE.test/", "https://example.test"])
    assert settings.AUTH_BROWSER_ORIGINS == ["https://example.test"]
