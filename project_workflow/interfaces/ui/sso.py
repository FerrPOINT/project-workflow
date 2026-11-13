"""Server-side OIDC login and fail-closed browser/API authentication."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.exc import DBAPIError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from project_workflow.config import Settings, get_settings
from project_workflow.infrastructure.platform_auth import HumanAccess, human_access
from project_workflow.infrastructure.platform_namespace import (
    is_personal_token as platform_personal_token,
)
from project_workflow.infrastructure.request_clock import RequestClock, current_clock
from project_workflow.interfaces.ui.cookies import cookie_name
from project_workflow.interfaces.ui.templates import templates

_CLIENT_ID = "project-workflow"
_SESSION_COOKIE = "workflow_sso"
_TRANSACTION_COOKIE = "workflow_oidc_state"

# The branding bridge reads only its configured public source; callers cannot select an upstream.
_PUBLIC_PATHS = frozenset({
    "/health", "/login", "/sso/callback", "/logout", "/ui-assets/htmx-2.0.11.min.js", "/api/platform/branding",
})


def _cipher(settings: Settings) -> Fernet:
    if len(settings.AUTH_SESSION_SECRET) < 32:
        raise RuntimeError("AUTH_SESSION_SECRET must contain at least 32 characters")
    digest = hashlib.sha256(b"project-workflow/browser-session/v1:" + settings.AUTH_SESSION_SECRET.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _safe_next(value: str | None) -> str:
    return value if value and value.startswith("/") and not value.startswith("//") and "\\" not in value else "/"


def _sso_entry(request: Request, *, message: str, next_path: str = "/", login_required: bool = False,
               status_code: int = 401) -> Response:
    return templates.TemplateResponse(request=request, name="sso_entry.html", status_code=status_code, context={
        "message": message, "login_required": login_required,
        "access_denied": status_code == 403,
        "login_url": get_settings().UI_BASE_PATH + "/login?" + urlencode({"next": _safe_next(next_path)}),
        "platform_origin": get_settings().UI_PLATFORM_ORIGIN,
    })


def _decode_cookie(settings: Settings, value: str | None, max_age: int) -> dict[str, object] | None:
    if not value:
        return None
    try:
        payload = _cipher(settings).decrypt(value.encode(), ttl=max_age)
        data = json.loads(payload)
        return data if isinstance(data, dict) else None
    except (InvalidToken, ValueError, json.JSONDecodeError):
        return None


def _encode_cookie(settings: Settings, data: dict[str, object]) -> str:
    return _cipher(settings).encrypt(json.dumps(data, separators=(",", ":")).encode()).decode()


def _auth_error(request: Request, status: int, message: str) -> Response:
    if request.url.path.startswith("/api/"):
        return JSONResponse({"ok": False, "error": message}, status_code=status)
    if request.url.path == "/sso/callback":
        return _sso_entry(request, message=message, status_code=status)
    if status == 401:
        destination = _safe_next(request.url.path + (f"?{request.url.query}" if request.url.query else ""))
        return RedirectResponse(
            f"{get_settings().UI_BASE_PATH}/login?{urlencode({'next': destination, 'silent': '1'})}",
            status_code=303,
        )
    return _sso_entry(request, message=message, status_code=status)


class _SsoMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings):
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next):
        settings = self.settings
        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith((
            "/internal/runtime/", "/api/pm/namespace-ownership/", "/api/internal/v1/user-deletions/",
            "/ui-assets/controllers/",
            "/base-assets/fonts/",
        )):
            return await call_next(request)
        canonical_hostname = urlparse(settings.AUTH_PUBLIC_ORIGIN).hostname
        if request.url.hostname in {"127.0.0.1", "localhost"} and canonical_hostname in {"127.0.0.1", "localhost"} \
                and request.url.hostname != canonical_hostname:
            return RedirectResponse(settings.AUTH_PUBLIC_ORIGIN.rstrip("/") + settings.UI_BASE_PATH + path +
                                    (f"?{request.url.query}" if request.url.query else ""), status_code=307)

        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        cookie = _decode_cookie(settings, request.cookies.get(cookie_name(settings, _SESSION_COOKIE)), 24 * 3600)
        token = bearer or (str(cookie.get("token")) if cookie else "")
        if not token:
            return _auth_error(request, 401, "Требуется вход через Central Auth")
        if cookie and not bearer and request.method not in {"GET", "HEAD", "OPTIONS"}:
            allowed_origins = {settings.AUTH_PUBLIC_ORIGIN.rstrip("/"), *settings.AUTH_BROWSER_ORIGINS}
            if request.headers.get("origin") not in allowed_origins:
                return _auth_error(request, 403, "Неверный источник запроса")

        original_started = time.monotonic()
        is_personal_token = platform_personal_token(bearer)
        path = "/auth/tokens/introspect" if is_personal_token else "/auth/me"
        started = time.monotonic()
        wall_started = datetime.now(timezone.utc)
        try:
            response = await request.app.state.central_auth_http.get(
                settings.AUTH_INTERNAL_BASE_URL.rstrip("/") + path,
                params={"include_lifetime": "true"} if is_personal_token else None,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.RequestError:
            return _auth_error(request, 503, "Central Auth временно недоступен")
        if response.status_code == 401:
            return _auth_error(request, 401, "Сессия истекла или отозвана")
        if response.status_code != 200:
            return _auth_error(request, 503, "Central Auth временно недоступен")
        try:
            if len(response.content) > 16384:
                raise ValueError("oversized identity")
            identity = response.json()
            if not isinstance(identity, dict):
                raise ValueError("invalid identity")
            subject = identity["sub" if is_personal_token else "id"]
            if not isinstance(subject, str) or not subject:
                raise ValueError("invalid identity")
            machines = os.environ.get("PROJECT_WORKFLOW_NAMESPACE__MACHINE_SUBJECTS", "").split(",")
            machine_subjects = [item.strip() for item in machines if item.strip()]
            if (identity.get("role") == "service_account" or identity.get("subject_role") == "service_account"
                    or subject in machine_subjects):
                return _auth_error(request, 403, "Машинный credential не разрешён на human routes")
            if is_personal_token:
                # Auth introspection rejects inactive owners before returning 200.
                if "status" in identity and identity["status"] != "active":
                    return _auth_error(request, 403, "Учётная запись не активна")
                if identity["subject_role"] != identity["role"]:
                    raise ValueError("conflicting human role")
                if not isinstance(identity["expires_at"], str):
                    raise ValueError("Human PAT requires a finite credential expiry")
                observed = datetime.fromisoformat(identity["observed_at"].replace("Z", "+00:00"))
                expires_at = datetime.fromisoformat(identity["expires_at"].replace("Z", "+00:00"))
                if (observed.tzinfo is None or observed.utcoffset() is None
                        or observed.timestamp() > time.time() + 1
                        or observed.timestamp() < wall_started.timestamp() - 60):
                    raise ValueError("invalid token clock")
                scopes = identity["scopes"]
                if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes):
                    raise ValueError("invalid token scopes")
                action = "read" if request.method in {"GET", "HEAD", "OPTIONS"} else "write"
                if f"project-workflow:{action}" not in scopes:
                    return _auth_error(request, 403, "Недостаточно прав токена")
            else:
                if not isinstance(identity.get("status"), str):
                    raise ValueError("missing account status")
                if identity["status"] != "active":
                    return _auth_error(request, 403, "Учётная запись не активна")
                # Auth has verified this exact JWT; claims only bind identity and shorten its clock.
                claims = jwt.decode(token, options={"verify_signature": False})
                if (claims.get("iss") != settings.AUTH_ISSUER or claims.get("sub") != subject
                        or type(claims.get("exp")) is not int):
                    raise ValueError("invalid credential binding or expiry")
                expires_at = datetime.fromtimestamp(claims["exp"], timezone.utc)
            access = human_access(identity, issuer=settings.AUTH_ISSUER, subject=subject,
                                  started=started, wall_started=wall_started,
                                  expires_at=expires_at)
            request.state.central_access = access
            request.state.central_subject = subject
        except PermissionError:
            return _auth_error(request, 403, "Личность пользователя не подтверждена или срок учётных данных истёк")
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError, OSError, jwt.PyJWTError):
            return _auth_error(request, 503, "Central Auth вернул некорректный ответ")
        async def authorized_dispatch():
            clock_token = None
            try:
                clock_token = current_clock.set(RequestClock.from_access(access))
                result = await call_next(request)
            except SpaceAccessDenied:
                return _auth_error(request, 403, "Действующий допуск к операции не подтверждён")
            except DBAPIError as error:
                if getattr(error.orig, "sqlstate", None) != "42501":
                    raise
                return _auth_error(request, 403, "Действующий допуск к операции не подтверждён")
            finally:
                if clock_token is not None:
                    current_clock.reset(clock_token)
            if not access.is_current():
                return _auth_error(request, 503, "Подтверждение доступа истекло. Повторите запрос")
            result.headers["Cache-Control"] = "private, no-store"
            return result

        from project_workflow.domain.project_admission import SpaceAccessDenied, human_scope
        from project_workflow.interfaces.ui.project_admission import confirm, policy_active
        if not policy_active():
            return await authorized_dispatch()
        try:
            scope = await confirm(request, token=token, issuer=access.issuer,
                                  subject=subject, role=access.role, original_started=original_started,
                                  token_expiry=access.expires_at.timestamp())
            scope = replace(scope, deadline=min(scope.deadline, access.monotonic_deadline()))
            request.state.project_scope = scope
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                scope.require_operator()
            context_token = human_scope.set(scope)
            try:
                result = await authorized_dispatch()
                scope.require_current()
                result.headers["Cache-Control"] = "private, no-store"
                return result
            finally:
                human_scope.reset(context_token)
        except SpaceAccessDenied:
            return _auth_error(request, 403, "Доступ к проекту или операции закрыт")
        except (KeyError, TypeError, ValueError, httpx.HTTPError):
            return _auth_error(request, 503, "Актуальный допуск к проектам недоступен")


def can_administer(request: Request) -> bool:
    """Use the same current authority for server dependencies and rendered controls."""
    if get_settings().PROJECT_WORKFLOW_MODE == "standalone":
        return True
    access = getattr(request.state, "central_access", None)
    return isinstance(access, HumanAccess) and access.permits(administration=True)


def visible_services(request: Request, services: list[dict]) -> list[dict]:
    """Filter a per-request view; never cache personal access in the public catalog."""
    if get_settings().PROJECT_WORKFLOW_MODE == "standalone":
        return list(services)
    access = getattr(request.state, "central_access", None)
    if not isinstance(access, HumanAccess):
        return []
    return [service for service in services if isinstance(service.get("key"), str) and access.permits()]


def require_administrator(request: Request) -> None:
    """Declared dependency; local history and application scopes never grant administration."""
    if not can_administer(request):
        raise HTTPException(status_code=403, detail="Требуются права администратора PDLC")


def install_sso(app: FastAPI, settings: Settings | None = None) -> None:
    settings = get_settings() if settings is None else settings
    if settings.PROJECT_WORKFLOW_MODE == "standalone":
        if os.environ.get("PROJECT_WORKFLOW_SPACES__ENABLED") == "true":
            raise RuntimeError("Standalone mode conflicts with shared project policy")
        return
    if not settings.AUTH_ISSUER:
        raise RuntimeError("Platform mode requires central authentication (AUTH_ISSUER)")
    if not settings.AUTH_INTERNAL_BASE_URL:
        raise RuntimeError("AUTH_INTERNAL_BASE_URL is required for SSO")
    _cipher(settings)
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def auth_lifespan(current_app: FastAPI) -> AsyncIterator[Mapping[str, object]]:
        async with previous_lifespan(current_app) as state:
            # Pool connections, never an upstream cookie session shared by different callers.
            cookies = CookieJar(policy=DefaultCookiePolicy(allowed_domains=[]))
            async with httpx.AsyncClient(timeout=5, follow_redirects=False, cookies=cookies) as client:
                current_app.state.central_auth_http = client
                try:
                    yield {} if state is None else state
                finally:
                    del current_app.state.central_auth_http

    app.router.lifespan_context = auth_lifespan
    app.add_middleware(_SsoMiddleware, settings=settings)

    @app.get("/login", include_in_schema=False)
    async def login(request: Request, next: str = "/", silent: bool = False, platform_return: str = "") -> Response:
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        transaction: dict[str, object] = {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32),
                                          "verifier": verifier, "next": _safe_next(next), "silent": silent,
                                          "platform_return": _safe_next(platform_return) if platform_return else ""}
        params = {
            "response_type": "code", "client_id": _CLIENT_ID,
            "redirect_uri": settings.AUTH_PUBLIC_ORIGIN.rstrip("/") + settings.UI_BASE_PATH + "/sso/callback",
            "scope": "openid email profile", "state": transaction["state"], "nonce": transaction["nonce"],
            "code_challenge": challenge, "code_challenge_method": "S256",
        }
        if silent:
            params["prompt"] = "none"
        authorize_url = settings.AUTH_ISSUER.rstrip("/") + "/oidc/authorize?" + urlencode(params)
        response = RedirectResponse(authorize_url, status_code=303)
        response.set_cookie(cookie_name(settings, _TRANSACTION_COOKIE), _encode_cookie(settings, transaction),
                            max_age=600, path=settings.UI_BASE_PATH + "/sso/callback", httponly=True, samesite="lax",
                            secure=settings.AUTH_COOKIE_SECURE)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/sso/callback", include_in_schema=False)
    async def callback(request: Request, code: str = "", state: str = "", error: str = "") -> Response:
        transaction = _decode_cookie(settings, request.cookies.get(cookie_name(settings, _TRANSACTION_COOKIE)), 600)
        if not transaction or not state or not secrets.compare_digest(str(transaction.get("state")), state):
            return _auth_error(request, 401, "Вход не подтверждён")
        if error:
            if error == "login_required" and transaction.get("silent") is True and not code:
                response = _sso_entry(request, message="Требуется вход через SSO.",
                                      next_path=str(transaction["next"]), login_required=True)
                response.delete_cookie(
                    cookie_name(settings, _TRANSACTION_COOKIE),
                    path=settings.UI_BASE_PATH + "/sso/callback",
                    httponly=True,
                    samesite="lax",
                    secure=settings.AUTH_COOKIE_SECURE,
                )
                return response
            return _auth_error(request, 401, "Central Auth не подтвердил вход")
        if not code:
            return _auth_error(request, 401, "Вход не подтверждён")
        try:
            client = request.app.state.central_auth_http
            exchange = await client.post(settings.AUTH_INTERNAL_BASE_URL.rstrip("/") + "/oidc/token", data={
                "grant_type": "authorization_code", "client_id": _CLIENT_ID,
                "redirect_uri": settings.AUTH_PUBLIC_ORIGIN.rstrip("/") + settings.UI_BASE_PATH + "/sso/callback",
                "code": code, "code_verifier": transaction["verifier"],
            })
            if exchange.status_code != 200:
                return _auth_error(request, 401, "Central Auth отклонил вход")
            tokens = exchange.json()
            access_token = tokens["access_token"]
            jwks_url = settings.AUTH_INTERNAL_BASE_URL.rstrip("/") + "/oidc/jwks"
            signing_key = await asyncio.to_thread(jwt.PyJWKClient(jwks_url, timeout=5).get_signing_key_from_jwt,
                                                  tokens["id_token"])
            claims = jwt.decode(tokens["id_token"], signing_key.key, algorithms=["ES256"],
                                audience=_CLIENT_ID, issuer=settings.AUTH_ISSUER,
                                options={"require": ["exp", "sub", "iss", "aud", "nonce"]})
            if not secrets.compare_digest(str(claims["nonce"]), str(transaction["nonce"])):
                return _auth_error(request, 401, "Подтверждение входа не совпало")
            confirmation = await client.get(settings.AUTH_INTERNAL_BASE_URL.rstrip("/") + "/auth/me",
                                            headers={"Authorization": f"Bearer {access_token}"})
            if confirmation.status_code != 200:
                return _auth_error(request, 401, "Центральная сессия недействительна")
            identity = confirmation.json()
            if not isinstance(identity, dict) or identity.get("id") != claims["sub"]:
                return _auth_error(request, 401, "Центральная сессия недействительна")
            machines = {item.strip() for item in os.environ.get(
                "PROJECT_WORKFLOW_NAMESPACE__MACHINE_SUBJECTS", "").split(",") if item.strip()}
            if (identity.get("status") != "active" or identity.get("role") not in ("user", "admin")
                    or identity.get("subject_role") == "service_account"
                    or identity["id"] in machines):
                return _auth_error(request, 403, "Действующая учётная запись пользователя не подтверждена")
        except (httpx.RequestError, jwt.PyJWTError, KeyError, ValueError, TypeError):
            return _auth_error(request, 503, "Не удалось завершить центральный вход")
        destination = settings.UI_BASE_PATH + _safe_next(str(transaction["next"]))
        platform_return = transaction.get("platform_return")
        if isinstance(platform_return, str) and platform_return and settings.UI_PLATFORM_ORIGIN:
            destination = settings.UI_PLATFORM_ORIGIN.rstrip("/") + _safe_next(platform_return)
        response = RedirectResponse(destination, status_code=303)
        session = {"token": access_token, "sub": claims["sub"], "issued": int(time.time())}
        response.set_cookie(
            cookie_name(settings, _SESSION_COOKIE),
            _encode_cookie(settings, session),
            max_age=int(tokens["expires_in"]),
            path=settings.UI_BASE_PATH or "/",
            httponly=True,
            samesite="lax",
            secure=settings.AUTH_COOKIE_SECURE,
        )
        response.delete_cookie(cookie_name(settings, _TRANSACTION_COOKIE), path=settings.UI_BASE_PATH + "/sso/callback",
                               httponly=True, samesite="lax", secure=settings.AUTH_COOKIE_SECURE)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/logout", include_in_schema=False)
    async def logout() -> Response:
        response = RedirectResponse(settings.AUTH_ISSUER.rstrip("/") + "/oidc/logout?client_id=" + _CLIENT_ID,
                                    status_code=303)
        response.delete_cookie(cookie_name(settings, _SESSION_COOKIE), path=settings.UI_BASE_PATH or "/",
                               httponly=True, samesite="lax", secure=settings.AUTH_COOKIE_SECURE)
        response.delete_cookie(cookie_name(settings, _TRANSACTION_COOKIE), path=settings.UI_BASE_PATH + "/sso/callback",
                               httponly=True, samesite="lax", secure=settings.AUTH_COOKIE_SECURE)
        response.headers["Cache-Control"] = "no-store"
        return response
