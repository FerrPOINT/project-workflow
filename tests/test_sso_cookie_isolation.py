"""One host cookie jar must keep two configured Workflow origins independent."""

import hashlib
from http.cookiejar import CookieJar
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from project_workflow.interfaces.ui import sso
from project_workflow.interfaces.ui.cookies import cookie_name
from project_workflow.interfaces.ui.routes import pages
from tests.test_sso import _app


def test_cookie_scope_uses_configured_issuer_and_origin_not_internal_address(monkeypatch):
    _, settings = _app(monkeypatch)
    digest = hashlib.sha256(b"http://localhost:7701\nhttp://localhost:8812").hexdigest()
    for prefix in ("workflow_sso", "workflow_oidc_state", "workflow_namespace_id"):
        assert cookie_name(settings, prefix) == f"{prefix}_{digest}"
        for override in ({"AUTH_ISSUER": "http://localhost:8701"}, {"AUTH_PUBLIC_ORIGIN": "http://localhost:9812"}):
            assert cookie_name(settings.model_copy(update=override), prefix) != cookie_name(settings, prefix)
        same = settings.model_copy(update={"AUTH_INTERNAL_BASE_URL": "http://other-container:7701"})
        assert cookie_name(same, prefix) == cookie_name(settings, prefix)
        slashes = settings.model_copy(update={
            "AUTH_ISSUER": settings.AUTH_ISSUER + "/", "AUTH_PUBLIC_ORIGIN": settings.AUTH_PUBLIC_ORIGIN + "/",
        })
        assert cookie_name(slashes, prefix) == cookie_name(settings, prefix)
        assert cookie_name(settings.model_copy(update={"AUTH_ISSUER": ""}), prefix) == prefix


def test_shared_jar_keeps_both_pending_logins_sessions_and_logout_independent(monkeypatch):
    app_a, settings_a = _app(monkeypatch)
    app_b, settings_b = _app(monkeypatch, AUTH_PUBLIC_ORIGIN="http://localhost:9812")
    settings_by_origin = {item.AUTH_PUBLIC_ORIGIN: item for item in (settings_a, settings_b)}
    claims = {}
    original_client = httpx.AsyncClient

    def central(request):
        if request.url.path == "/oidc/token":
            origin = parse_qs(request.content.decode())["redirect_uri"][0].removesuffix("/sso/callback")
            assert origin in settings_by_origin
            form = parse_qs(request.content.decode())
            assert form["code_verifier"][0] == claims[origin]["verifier"]
            return httpx.Response(200, json={"access_token": origin, "id_token": origin, "expires_in": 900})
        assert request.url.path == "/auth/me"
        origin = request.headers["authorization"].removeprefix("Bearer ")
        assert origin in settings_by_origin
        return httpx.Response(200, json={"id": origin})

    monkeypatch.setattr(sso.httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(central), **kwargs,
    ))
    monkeypatch.setattr(sso.jwt, "PyJWKClient", lambda *_args, **_kwargs: SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=object()),
    ))
    monkeypatch.setattr(sso.jwt, "decode", lambda token, *_args, **_kwargs: {
        "nonce": claims[token]["nonce"], "sub": token,
    })
    jar = CookieJar()
    with (
        TestClient(app_a, base_url=settings_a.AUTH_PUBLIC_ORIGIN, cookies=jar, follow_redirects=False) as client_a,
        TestClient(app_b, base_url=settings_b.AUTH_PUBLIC_ORIGIN, cookies=jar, follow_redirects=False) as client_b,
    ):
        assert client_a.get("/login").status_code == 303
        assert client_b.get("/login").status_code == 303
        for client, settings in ((client_a, settings_a), (client_b, settings_b)):
            state_cookie = client.cookies.get(cookie_name(settings, "workflow_oidc_state"))
            transaction = sso._decode_cookie(settings, state_cookie, 600)
            assert transaction is not None
            claims[settings.AUTH_PUBLIC_ORIGIN] = transaction
        assert len(list(jar)) == 2
        for client, settings in ((client_a, settings_a), (client_b, settings_b)):
            transaction = claims[settings.AUTH_PUBLIC_ORIGIN]
            callback = client.get("/sso/callback", params={"code": "test-code", "state": transaction["state"]})
            assert callback.status_code == 303
            session = sso._decode_cookie(settings, client.cookies.get(cookie_name(settings, "workflow_sso")), 900)
            assert session is not None and session["sub"] == settings.AUTH_PUBLIC_ORIGIN
            assert settings.AUTH_PUBLIC_ORIGIN not in callback.headers["set-cookie"]
        assert len(list(jar)) == 2
        assert client_a.get("/").status_code == 200
        assert client_b.get("/").status_code == 200
        # A new pending transaction in B must also survive logout from A.
        assert client_b.get("/login").status_code == 303
        foreign_cookies = {
            item.name: item.value for item in jar
            if item.name in {cookie_name(settings_b, "workflow_sso"), cookie_name(settings_b, "workflow_oidc_state")}
        }
        logout = client_a.get("/logout")
        assert logout.status_code == 303
        assert logout.headers["location"].startswith(settings_a.AUTH_ISSUER + "/oidc/logout?")
        assert client_a.get("/api/tasks").status_code == 401
        assert client_b.get("/api/tasks").status_code == 200
        assert {item.name: item.value for item in jar} == foreign_cookies


@pytest.mark.parametrize("own_value", [None, "", "invalid-encrypted-cookie"])
def test_legacy_and_foreign_cookies_never_restore_an_own_session(monkeypatch, own_value):
    app, settings = _app(monkeypatch)
    foreign = settings.model_copy(update={"AUTH_PUBLIC_ORIGIN": "http://localhost:9812"})
    encoded = sso._encode_cookie(settings, {"token": "sso-jwt"})
    with TestClient(app, follow_redirects=False) as client:
        client.cookies.set("workflow_sso", encoded)
        client.cookies.set(cookie_name(foreign, "workflow_sso"), encoded)
        client.cookies.set("workflow_oidc_state", sso._encode_cookie(settings, {"state": "legacy-state"}))
        if own_value is not None:
            client.cookies.set(cookie_name(settings, "workflow_sso"), own_value)
        assert client.get("/api/tasks").status_code == 401
        assert client.get("/sso/callback?code=test-code&state=legacy-state").status_code == 401


def test_installed_middleware_does_not_disable_auth_when_global_settings_change(monkeypatch):
    app, settings = _app(monkeypatch)
    monkeypatch.setattr(sso, "get_settings", lambda: settings.model_copy(update={"AUTH_ISSUER": ""}))
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/api/tasks").status_code == 401
        assert client.get("/").status_code == 303


def test_secure_set_and_delete_cookie_attributes_and_host_header(monkeypatch):
    app, settings = _app(monkeypatch, AUTH_PUBLIC_ORIGIN="https://localhost:8812", AUTH_COOKIE_SECURE=True)
    with TestClient(app, base_url=settings.AUTH_PUBLIC_ORIGIN, follow_redirects=False) as client:
        login = client.get("/login", headers={"host": "untrusted.example"})
        transaction_name = cookie_name(settings, "workflow_oidc_state")
        assert login.headers["set-cookie"].startswith(transaction_name + "=")
        assert "Secure" in login.headers["set-cookie"]
        logout = client.get("/logout")
        deleted = logout.headers.get_list("set-cookie")
        assert len(deleted) == 2
        for item in deleted:
            assert "HttpOnly" in item and "Secure" in item and "SameSite=lax" in item and "Max-Age=0" in item
        assert "Path=/sso/callback" in deleted[1]
        assert len(client.cookies) == 0


def test_namespace_cookie_and_template_writes_use_the_same_scope(monkeypatch):
    _, settings = _app(monkeypatch, AUTH_COOKIE_SECURE=True)
    monkeypatch.setattr(pages, "get_settings", lambda: settings)
    monkeypatch.setattr(pages, "_load_namespaces", lambda: [
        {"id": 1, "name": "First", "task_count": 0}, {"id": 2, "name": "Second", "task_count": 0},
    ])
    monkeypatch.setattr(pages, "load_service_catalog", lambda *_args, **_kwargs: SimpleNamespace(
        services=[], source="runtime",
    ))
    own_name = cookie_name(settings, "workflow_namespace_id")
    other_name = cookie_name(settings.model_copy(update={"AUTH_PUBLIC_ORIGIN": "http://localhost:9812"}),
                             "workflow_namespace_id")
    request = Request({"type": "http", "method": "GET", "scheme": "https", "server": ("localhost", 8812),
                       "path": "/namespaces", "query_string": b"", "headers": [(b"cookie", (
                           f"workflow_namespace_id=1; {other_name}=1; {own_name}=2"
                       ).encode())]})
    context = pages._namespace_context(request, page="namespaces")
    context.update(edited_namespace=context["selected_namespace"], create_mode=False, workflows=[])
    assert context["selected_namespace"]["id"] == 2
    response = pages._template_response(request=request, name="namespaces.html", context=context)
    assert response.headers["set-cookie"].startswith(own_name + "=2;")
    assert "Secure" in response.headers["set-cookie"]
    assert "HttpOnly" not in response.headers["set-cookie"]
    html = bytes(response.body).decode()
    assert html.count(f'document.cookie="{own_name}"') == 2
    assert "+'; Secure'" in html
    assert "document.cookie='workflow_namespace_id='" not in html
