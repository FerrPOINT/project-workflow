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

from project_workflow.config import Settings
from project_workflow.infrastructure import platform_auth
from project_workflow.infrastructure.request_clock import RequestClock
from project_workflow.interfaces.ui import project_admission, sso
from tests._human_access_helpers import application_access_proof, human_identity, human_token, personal_identity
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


@pytest.mark.parametrize("credential", ["cookie", "bearer", "pat"])
@pytest.mark.parametrize("proof_case", [
    "missing", "null", "unenforced", "stale", "expired", "foreign_subject",
    "foreign_issuer", "foreign_application", "invalid_revision", "malformed",
])
def test_verified_identity_does_not_consume_application_grants(monkeypatch, credential, proof_case):
    app, settings = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "false")
    reached = []
    app.get("/api/protected")(lambda: reached.append(True) or {"private_success": True})
    identity = personal_identity("human") if credential == "pat" else human_identity("human")
    proof = application_access_proof(issuer=settings.AUTH_ISSUER, subject="human")
    if proof_case == "unenforced":
        proof["enforced"] = False
    elif proof_case in {"stale", "expired"}:
        now = datetime.now(timezone.utc)
        age = 10 if proof_case == "stale" else 61
        proof = application_access_proof(
            issuer=settings.AUTH_ISSUER, subject="human", now=now - timedelta(seconds=age),
        )
    elif proof_case == "foreign_subject":
        proof["subject"] = "other-human"
    elif proof_case == "foreign_issuer":
        proof["issuer"] = "https://other-auth.example"
    elif proof_case == "foreign_application":
        proof["applications"] = ["wiki"]
    elif proof_case == "invalid_revision":
        proof["revision"] = 0
    if proof_case != "missing":
        identity["application_access"] = None if proof_case == "null" else proof
    if proof_case == "malformed":
        identity["application_access"] = "not-a-policy"
    _central(monkeypatch, lambda request: httpx.Response(200, json=identity))
    with TestClient(app, follow_redirects=False) as client:
        headers = {}
        if credential == "cookie":
            client.cookies.set(sso.cookie_name(settings, "workflow_sso"),
                               sso._encode_cookie(settings, {"token": human_token("human")}))
        else:
            token = "sdlc_pat_test" if credential == "pat" else human_token("human")
            headers["Authorization"] = "Bearer " + token
        response = client.get("/api/protected", headers=headers)
    assert response.status_code == 200
    assert reached == [True]
    assert response.json() == {"private_success": True}
    assert sso.current_clock.get() is None


@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("credential", ["bearer", "cookie", "pat"])
def test_verified_role_controls_admin_without_application_access(monkeypatch, credential, role):
    from fastapi import Depends

    app, settings = _app(monkeypatch)
    app.post("/api/configuration", dependencies=[Depends(sso.require_administrator)])(lambda: {"ok": True})
    identity = (personal_identity("human", role=role, scopes=["project-workflow:read", "project-workflow:write"])
                if credential == "pat" else human_identity("human", role=role))
    _central(monkeypatch, lambda request: httpx.Response(200, json=identity))
    with TestClient(app) as client:
        if credential == "cookie":
            client.cookies.set(sso.cookie_name(settings, "workflow_sso"),
                               sso._encode_cookie(settings, {"token": human_token("human")}))
            headers = {"origin": settings.AUTH_PUBLIC_ORIGIN}
        else:
            token = "sdlc_pat_test" if credential == "pat" else human_token("human")
            headers = {"Authorization": "Bearer " + token}
        assert client.get("/api/tasks", headers=headers).status_code == 200
        assert client.post("/api/configuration", headers=headers).status_code == (200 if role == "admin" else 403)
        identity["application_access"] = {"role": "admin", "applications": [], "enforced": True}
        assert client.post("/api/configuration", headers=headers).status_code == (200 if role == "admin" else 403)


@pytest.mark.parametrize("spaces", ["false", "true"])
@pytest.mark.parametrize("credential", ["bearer", "cookie", "pat"])
@pytest.mark.parametrize("failure,status", [
    ("revoked", 401), ("inactive", 403), ("machine", 403), ("registered_machine", 403),
    ("unknown_role", 503), ("missing_role", 503), ("expired", 403),
])
def test_identity_negatives_precede_any_handler_or_project_rpc(monkeypatch, spaces, credential, failure, status):
    app, settings = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", spaces)
    reached = []
    app.get("/api/protected")(lambda: reached.append(True))
    identity = personal_identity("human") if credential == "pat" else human_identity("human")
    seconds = -1 if failure == "expired" else 60
    token = "sdlc_pat_test" if credential == "pat" else human_token("human", seconds=seconds)
    if credential == "pat":
        identity = personal_identity("human", seconds=seconds)
    if failure == "inactive":
        identity["status"] = "disabled"
    elif failure in {"machine", "unknown_role"}:
        identity["role"] = "service_account" if failure == "machine" else "member"
        if credential == "pat":
            identity["subject_role"] = identity["role"]
    elif failure == "registered_machine":
        monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE__MACHINE_SUBJECTS", "human")
    elif failure == "missing_role":
        del identity["role"]
    identity["application_access"] = {"role": "admin", "applications": ["project-workflow"]}
    _central(monkeypatch, lambda request: httpx.Response(401 if failure == "revoked" else 200, json=identity))

    async def unexpected(*args, **kwargs):
        pytest.fail("Rejected identity must not reach the project owner")

    monkeypatch.setattr(project_admission, "confirm", unexpected)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + token}
        if credential == "cookie":
            client.cookies.set(sso.cookie_name(settings, "workflow_sso"),
                               sso._encode_cookie(settings, {"token": token}))
            headers = {}
        response = client.get("/api/protected", headers=headers)
    assert response.status_code == status
    assert reached == []
    assert sso.current_clock.get() is None


@pytest.mark.parametrize("configured,claimed,expected", [
    ("https://auth.test", "https://auth.test", 200),
    ("https://auth.test/", "https://auth.test/", 200),
    ("https://auth.test/", "https://auth.test", 503),
    ("https://auth.test", "https://auth.test/", 503),
    ("https://auth.test", "https://foreign.test", 503),
])
def test_jwt_issuer_is_exactly_the_configured_auth_issuer(monkeypatch, configured, claimed, expected):
    app, _ = _app(monkeypatch, AUTH_ISSUER=configured)
    _central(monkeypatch, lambda request: httpx.Response(200, json=human_identity("human")))
    with TestClient(app) as client:
        response = client.get("/api/tasks", headers={"Authorization": "Bearer " + human_token("human", issuer=claimed)})
    assert response.status_code == expected


@pytest.mark.parametrize("claims", [
    {}, {"exp": True}, {"exp": "2100000000"}, {"exp": 1e40}, {"exp": 10**100},
    {"iss": "http://localhost:7701", "sub": "another-human", "exp": 2100000000},
])
def test_jwt_requires_typed_expiry_and_matching_subject(monkeypatch, claims):
    app, _ = _app(monkeypatch)
    _central(monkeypatch, lambda request: httpx.Response(200, json=human_identity("human")))
    token = jwt.encode(claims, key=None, algorithm="none")
    with TestClient(app) as client:
        assert client.get("/api/tasks", headers={"Authorization": "Bearer " + token}).status_code == 503


@pytest.mark.parametrize("sqlstate", ["42501", "40P01"])
def test_db_denial_restores_original_context_but_unrelated_failure_is_not_authorization(monkeypatch, sqlstate):
    app, settings = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "false")
    _central(monkeypatch, lambda request: httpx.Response(200, json=human_identity("human")))
    request = Request({
        "type": "http", "app": app, "method": "GET", "scheme": "http", "path": "/api/tasks",
        "query_string": b"", "server": ("localhost", 8812),
        "headers": [(b"authorization", ("Bearer " + human_token("human")).encode())],
    })

    class DriverFailure(Exception):
        pass

    cause = DriverFailure("synthetic-private-database-diagnostic")
    cause.sqlstate = sqlstate
    database_error = DBAPIError(None, None, cause)
    original = RequestClock(time.monotonic() + 30, time.time() + 30)

    async def exercise():
        async with app.router.lifespan_context(app):
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


def test_credential_expiring_during_handler_cannot_publish_success(monkeypatch):
    app, settings = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "false")
    now = datetime.now(timezone.utc)
    clock = {"now": now}
    monkeypatch.setattr(platform_auth, "_utc_now", lambda: clock["now"])
    _central(monkeypatch, lambda request: httpx.Response(200, json=human_identity("human")))
    reached = []

    @app.get("/api/slow")
    async def slow(request: Request):
        assert request.state.central_access.is_current()
        reached.append(request.state.central_subject)
        clock["now"] = now + timedelta(seconds=31)
        return {"private_success": True}

    with TestClient(app, follow_redirects=False) as client:
        headers = {"Authorization": "Bearer " + human_token("human", seconds=30)}
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
    app, settings = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true")
    _central(monkeypatch, lambda request: httpx.Response(200, json=identity))

    async def unexpected(*args, **kwargs):
        pytest.fail("Invalid human authority must not reach the project owner")

    monkeypatch.setattr(project_admission, "confirm", unexpected)
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/tasks", headers={"Authorization": "Bearer " + human_token("human")})
    assert response.status_code == status


@pytest.mark.parametrize("spaces", ["false", "true"])
@pytest.mark.parametrize("clock_case", [
    "future", "stale", "invalid_observed", "invalid_expiry", "missing_expiry", "naive_expiry", "conflicting_role",
    "null_expiry", "boolean_expiry", "numeric_expiry",
])
def test_pat_clock_and_role_must_be_valid_before_handler_or_owner_rpc(monkeypatch, clock_case, spaces):
    app, settings = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", spaces)
    now = datetime.now(timezone.utc)
    identity = personal_identity("human", seconds=30)
    if clock_case == "future":
        identity["observed_at"] = (now + timedelta(seconds=5)).isoformat()
    elif clock_case == "stale":
        identity["observed_at"] = (now - timedelta(seconds=65)).isoformat()
    elif clock_case == "invalid_observed":
        identity["observed_at"] = "not-a-timestamp"
    elif clock_case == "missing_expiry":
        del identity["expires_at"]
    elif clock_case == "naive_expiry":
        identity["expires_at"] = (now + timedelta(seconds=30)).replace(tzinfo=None).isoformat()
    elif clock_case == "conflicting_role":
        identity["subject_role"] = "admin"
    elif clock_case in {"null_expiry", "boolean_expiry", "numeric_expiry"}:
        identity["expires_at"] = {"null_expiry": None, "boolean_expiry": False, "numeric_expiry": 0}[clock_case]
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
    app, settings = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true")
    _central(monkeypatch, lambda request: httpx.Response(
        200, json=human_identity("human"),
    ))

    async def unexpected(*args, **kwargs):
        pytest.fail("Boolean JWT expiry must not become a project permit")

    monkeypatch.setattr(project_admission, "confirm", unexpected)
    token = jwt.encode({"exp": True}, key=None, algorithm="none")
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/tasks", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 503


@pytest.mark.parametrize("issuer", ["http://localhost:7701", "http://localhost:7701/"])
@pytest.mark.parametrize("failure,expected,calls", [
    ("valid", 303, ["/oidc/token", "/auth/me"]),
    ("exchange_denied", 401, ["/oidc/token"]),
    ("wrong_nonce", 401, ["/oidc/token"]),
    ("wrong_subject", 401, ["/oidc/token", "/auth/me"]),
    ("session_revoked", 401, ["/oidc/token", "/auth/me"]),
    ("token_missing", 503, ["/oidc/token"]),
    ("id_token_invalid", 503, ["/oidc/token"]),
    ("network_error", 503, ["/oidc/token"]),
    ("inactive", 403, ["/oidc/token", "/auth/me"]),
    ("machine", 403, ["/oidc/token", "/auth/me"]),
    ("registered_machine", 403, ["/oidc/token", "/auth/me"]),
    ("unknown_role", 403, ["/oidc/token", "/auth/me"]),
])
def test_oidc_callback_validates_signed_nonce_and_current_subject_before_cookie(
        monkeypatch, failure, expected, calls, issuer):
    app, settings = _app(monkeypatch, AUTH_ISSUER=issuer)
    if failure == "registered_machine":
        monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE__MACHINE_SUBJECTS", "human")
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
        identity = human_identity("other-human" if failure == "wrong_subject" else "human")
        if failure == "inactive":
            identity["status"] = "disabled"
        elif failure in {"machine", "unknown_role"}:
            identity["role"] = "service_account" if failure == "machine" else "member"
        return httpx.Response(401 if failure == "session_revoked" else 200,
                              json=identity)

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
    settings = Settings(PROJECT_WORKFLOW_MODE="platform", AUTH_ISSUER="")
    app = FastAPI()
    with pytest.raises(RuntimeError, match="requires central authentication"):
        sso.install_sso(app, settings)
    assert not app.user_middleware


@pytest.mark.parametrize("missing,match", [
    ({"AUTH_ISSUER": ""}, "AUTH_ISSUER"),
    ({"AUTH_INTERNAL_BASE_URL": ""}, "AUTH_INTERNAL_BASE_URL"),
    ({"AUTH_SESSION_SECRET": ""}, "at least 32"),
    ({"AUTH_SESSION_SECRET": "short"}, "at least 32"),
])
def test_incomplete_platform_settings_fail_before_partial_sso_routes(monkeypatch, missing, match):
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "false")
    settings = Settings(
        PROJECT_WORKFLOW_MODE="platform", AUTH_ISSUER="https://auth.fixture.invalid",
        AUTH_INTERNAL_BASE_URL="https://auth-internal.fixture.invalid",
        AUTH_SESSION_SECRET="synthetic-secret-with-at-least-thirty-two-bytes",
    ).model_copy(update=missing)
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "standalone")
    monkeypatch.setattr(sso, "get_settings", lambda: settings)
    app = FastAPI()
    with pytest.raises(RuntimeError, match=match):
        sso.install_sso(app)
    assert not app.user_middleware
    assert not {"/login", "/sso/callback", "/logout"}.intersection(route.path for route in app.routes)


def test_standalone_refuses_shared_policy_even_with_configured_auth(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true")
    settings = Settings(
        PROJECT_WORKFLOW_MODE="standalone", AUTH_ISSUER="https://auth.fixture.invalid",
    )
    app = FastAPI()
    with pytest.raises(RuntimeError, match="Standalone mode conflicts with shared project policy"):
        sso.install_sso(app, settings)
    assert not app.user_middleware
    assert not {"/login", "/sso/callback", "/logout"}.intersection(route.path for route in app.routes)


@pytest.mark.parametrize("explicit_settings", [False, True])
@pytest.mark.parametrize("ambient_mode", [None, "standalone"])
def test_dotenv_platform_settings_never_lose_sso_middleware(
    tmp_path, monkeypatch, explicit_settings, ambient_mode,
):
    for name in ("PROJECT_WORKFLOW_MODE", "AUTH_ISSUER", "AUTH_INTERNAL_BASE_URL", "AUTH_SESSION_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "false")
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "PROJECT_WORKFLOW_MODE=platform\nAUTH_ISSUER=https://auth.fixture.invalid\n"
        "AUTH_INTERNAL_BASE_URL=https://auth-internal.fixture.invalid\n"
        "AUTH_SESSION_SECRET=synthetic-secret-with-at-least-thirty-two-bytes\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=dotenv)
    assert settings.PROJECT_WORKFLOW_MODE == "platform"
    assert settings.AUTH_ISSUER == "https://auth.fixture.invalid"
    if ambient_mode is not None:
        monkeypatch.setenv("PROJECT_WORKFLOW_MODE", ambient_mode)
    lookups = []

    def resolved_settings():
        lookups.append(True)
        return settings

    monkeypatch.setattr(sso, "get_settings", resolved_settings)
    app = FastAPI()
    app.get("/api/protected")(lambda: {"private_success": True})
    sso.install_sso(app, settings if explicit_settings else None)
    assert lookups == ([] if explicit_settings else [True])
    assert len(app.user_middleware) == 1
    assert app.user_middleware[0].cls is sso._SsoMiddleware
    assert app.user_middleware[0].kwargs["settings"] is settings
    assert {"/login", "/sso/callback", "/logout"}.issubset(route.path for route in app.routes)
    with TestClient(app, follow_redirects=False) as client:
        assert client.get("/api/protected").status_code == 401
        login = client.get("/login")
    assert login.status_code == 303
    assert login.headers["location"].startswith(settings.AUTH_ISSUER + "/oidc/authorize?")


@pytest.mark.parametrize("spaces", ["false", "true"])
def test_persistent_machine_pat_cannot_enter_human_routes(monkeypatch, spaces):
    app, settings = _app(monkeypatch)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", spaces)
    identity = personal_identity("machine", role="service_account", scopes=["project-workflow:read"])
    identity["expires_at"] = None
    _central(monkeypatch, lambda request: httpx.Response(200, json=identity))

    async def unexpected(*args, **kwargs):
        pytest.fail("A persistent machine PAT must not reach the human project owner")

    monkeypatch.setattr(project_admission, "confirm", unexpected)
    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/api/tasks", headers={"Authorization": "Bearer pdlc_pat_machine"})
    assert response.status_code == 403
