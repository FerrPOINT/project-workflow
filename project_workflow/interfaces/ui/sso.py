"""Server-side OIDC login and fail-closed browser/API authentication."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from project_workflow.config import Settings, get_settings

_CLIENT_ID = "project-workflow"
_SESSION_COOKIE = "workflow_sso"
_TRANSACTION_COOKIE = "workflow_oidc_state"
_PUBLIC_PATHS = frozenset({"/health", "/login", "/sso/callback", "/logout"})


def _cipher(settings: Settings) -> Fernet:
    if len(settings.AUTH_SESSION_SECRET) < 32:
        raise RuntimeError("AUTH_SESSION_SECRET must contain at least 32 characters")
    digest = hashlib.sha256(b"project-workflow/browser-session/v1:" + settings.AUTH_SESSION_SECRET.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _safe_next(value: str | None) -> str:
    return value if value and value.startswith("/") and not value.startswith("//") else "/"


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
        return HTMLResponse(
            '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Ошибка входа</title>'
            '<main style="max-width:32rem;margin:10vh auto;font:16px system-ui">'
            '<h1>Не удалось войти</h1><p>Повторите вход через Central Auth.</p>'
            '<a href="/login">Повторить</a></main></html>', status_code=status,
        )
    if status == 401:
        destination = _safe_next(request.url.path + (f"?{request.url.query}" if request.url.query else ""))
        return RedirectResponse(f"/login?{urlencode({'next': destination})}", status_code=303)
    return HTMLResponse(
        '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Вход недоступен</title>'
        '<main style="max-width:32rem;margin:10vh auto;font:16px system-ui"><h1>Central Auth недоступен</h1>'
        '<p>Попробуйте позже. Локальный вход не используется.</p></main></html>',
        status_code=status,
    )


class _SsoMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        settings = get_settings()
        if not settings.AUTH_ISSUER:
            return await call_next(request)
        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith("/internal/runtime/"):
            return await call_next(request)
        if request.url.hostname == "127.0.0.1":
            return RedirectResponse(settings.AUTH_PUBLIC_ORIGIN.rstrip("/") + path +
                                    (f"?{request.url.query}" if request.url.query else ""), status_code=307)

        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        cookie = _decode_cookie(settings, request.cookies.get(_SESSION_COOKIE), 24 * 3600)
        token = bearer or (str(cookie.get("token")) if cookie else "")
        if not token:
            return _auth_error(request, 401, "Требуется вход через Central Auth")
        if cookie and not bearer and request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("origin") != settings.AUTH_PUBLIC_ORIGIN.rstrip("/"):
                return _auth_error(request, 403, "Неверный источник запроса")

        is_personal_token = bearer.startswith("sdlc_pat_")
        path = "/auth/tokens/introspect" if is_personal_token else "/auth/me"
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(settings.AUTH_INTERNAL_BASE_URL.rstrip("/") + path,
                                            headers={"Authorization": f"Bearer {token}"})
        except httpx.RequestError:
            return _auth_error(request, 503, "Central Auth временно недоступен")
        if response.status_code == 401:
            return _auth_error(request, 401, "Сессия истекла или отозвана")
        if response.status_code != 200:
            return _auth_error(request, 503, "Central Auth временно недоступен")
        try:
            identity = response.json()
            subject = identity["sub" if is_personal_token else "id"]
            if not isinstance(subject, str) or not subject:
                raise ValueError("invalid identity")
            if is_personal_token:
                action = "read" if request.method in {"GET", "HEAD", "OPTIONS"} else "write"
                if f"project-workflow:{action}" not in identity["scopes"]:
                    return _auth_error(request, 403, "Недостаточно прав токена")
            request.state.central_subject = subject
        except (KeyError, TypeError, ValueError):
            return _auth_error(request, 503, "Central Auth вернул некорректный ответ")
        return await call_next(request)


def install_sso(app: FastAPI) -> None:
    if not os.environ.get("AUTH_ISSUER"):
        return
    settings = get_settings()
    if not settings.AUTH_ISSUER:
        return
    _cipher(settings)
    if not settings.AUTH_INTERNAL_BASE_URL:
        raise RuntimeError("AUTH_INTERNAL_BASE_URL is required for SSO")
    app.add_middleware(_SsoMiddleware)

    @app.get("/login", include_in_schema=False)
    async def login(request: Request, next: str = "/") -> Response:
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        transaction: dict[str, object] = {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32),
                                          "verifier": verifier, "next": _safe_next(next)}
        params = {
            "response_type": "code", "client_id": _CLIENT_ID,
            "redirect_uri": settings.AUTH_PUBLIC_ORIGIN.rstrip("/") + "/sso/callback",
            "scope": "openid email profile", "state": transaction["state"], "nonce": transaction["nonce"],
            "code_challenge": challenge, "code_challenge_method": "S256",
        }
        authorize_url = settings.AUTH_ISSUER.rstrip("/") + "/oidc/authorize?" + urlencode(params)
        response = RedirectResponse(authorize_url, status_code=303)
        response.set_cookie(_TRANSACTION_COOKIE, _encode_cookie(settings, transaction),
                            max_age=600, path="/sso/callback", httponly=True, samesite="lax",
                            secure=settings.AUTH_COOKIE_SECURE)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/sso/callback", include_in_schema=False)
    async def callback(request: Request, code: str = "", state: str = "") -> Response:
        transaction = _decode_cookie(settings, request.cookies.get(_TRANSACTION_COOKIE), 600)
        if not transaction or not code or not state or not secrets.compare_digest(str(transaction.get("state")), state):
            return _auth_error(request, 401, "Вход не подтверждён")
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                exchange = await client.post(settings.AUTH_INTERNAL_BASE_URL.rstrip("/") + "/oidc/token", data={
                    "grant_type": "authorization_code", "client_id": _CLIENT_ID,
                    "redirect_uri": settings.AUTH_PUBLIC_ORIGIN.rstrip("/") + "/sso/callback",
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
                                    audience=_CLIENT_ID, issuer=settings.AUTH_ISSUER.rstrip("/"),
                                    options={"require": ["exp", "sub", "iss", "aud", "nonce"]})
                if not secrets.compare_digest(str(claims["nonce"]), str(transaction["nonce"])):
                    return _auth_error(request, 401, "Подтверждение входа не совпало")
                confirmation = await client.get(settings.AUTH_INTERNAL_BASE_URL.rstrip("/") + "/auth/me",
                                                headers={"Authorization": f"Bearer {access_token}"})
                if confirmation.status_code != 200 or confirmation.json().get("id") != claims["sub"]:
                    return _auth_error(request, 401, "Центральная сессия недействительна")
        except (httpx.RequestError, jwt.PyJWTError, KeyError, ValueError, TypeError):
            return _auth_error(request, 503, "Не удалось завершить центральный вход")
        response = RedirectResponse(_safe_next(str(transaction["next"])), status_code=303)
        session = {"token": access_token, "sub": claims["sub"], "issued": int(time.time())}
        response.set_cookie(_SESSION_COOKIE, _encode_cookie(settings, session),
                            max_age=int(tokens["expires_in"]), path="/", httponly=True, samesite="lax",
                            secure=settings.AUTH_COOKIE_SECURE)
        response.delete_cookie(_TRANSACTION_COOKIE, path="/sso/callback")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/logout", include_in_schema=False)
    async def logout() -> Response:
        response = RedirectResponse(settings.AUTH_ISSUER.rstrip("/") + "/oidc/logout?client_id=" + _CLIENT_ID,
                                    status_code=303)
        response.delete_cookie(_SESSION_COOKIE, path="/")
        response.headers["Cache-Control"] = "no-store"
        return response
