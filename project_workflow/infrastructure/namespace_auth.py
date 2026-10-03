"""Fresh bounded Central PAT introspection at a fixed trusted root."""

import json
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from project_workflow import config
from project_workflow.domain.namespace_ownership import canonical_uuid

MAX_BODY = 16384
_monotonic = time.monotonic


class NamespaceAuthError(RuntimeError):
    def __init__(self, status: int):
        self.status = status
        super().__init__("Namespace machine authorization unavailable" if status == 503 else "Machine access denied")


@dataclass(frozen=True)
class NamespacePrincipal:
    issuer: str
    subject: str


def _root(value: str) -> str:
    url = urlsplit(value)
    if (
        not value or len(value) > 512 or value != value.strip() or any(
            character.isspace() or ord(character) < 32 or 127 <= ord(character) <= 159 for character in value
        )
        or url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
        or url.path not in {"", "/"} or url.query or url.fragment or "\\" in value
    ):
        raise ValueError("Invalid trusted authority root")
    _ = url.port
    return value.rstrip("/")


def authorize(authorization: str | None, namespace_id: int, *, provision: bool) -> NamespacePrincipal:
    settings = config.get_settings()
    try:
        root = _root(settings.AUTH_INTERNAL_BASE_URL)
        issuer = _root(settings.AUTH_ISSUER)
        provisioner = canonical_uuid(settings.PROJECT_WORKFLOW_NAMESPACE_PROVISIONER_SUBJECT)
    except ValueError:
        raise NamespaceAuthError(503) from None
    if not authorization or not authorization.startswith("Bearer sdlc_pat_"):
        raise NamespaceAuthError(401)
    token = authorization[7:]
    if len(token) > 4096 or any(not 33 <= ord(character) <= 126 for character in token):
        raise NamespaceAuthError(401)
    try:
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            started = _monotonic()
            with client.stream("GET", root + "/auth/tokens/introspect", headers={
                "Authorization": "Bearer " + token, "Accept-Encoding": "identity",
            }) as response:
                if response.status_code == 401:
                    raise NamespaceAuthError(401)
                if response.status_code != 200:
                    raise NamespaceAuthError(503)
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    raise NamespaceAuthError(503)
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=1024):
                    body.extend(chunk)
                    if len(body) > MAX_BODY or _monotonic() - started > 5:
                        raise NamespaceAuthError(503)
                value = json.loads(body)
        if not isinstance(value, dict) or set(value) != {"sub", "email", "scopes"}:
            raise ValueError("Invalid introspection")
        subject = canonical_uuid(value["sub"]) if isinstance(value["sub"], str) else ""
        scopes = value["scopes"]
        if not subject or not isinstance(value["email"], str) or not isinstance(scopes, list) or any(
            not isinstance(scope, str) for scope in scopes
        ):
            raise ValueError("Invalid introspection")
    except (httpx.HTTPError, ValueError, TypeError):
        raise NamespaceAuthError(503) from None
    action = "provision" if provision else "read"
    standard = "write" if provision else "read"
    if (
        f"project-workflow:{standard}" not in scopes
        or f"project-workflow:namespace-owner:{action}:{namespace_id}" not in scopes
        or (provision and subject != provisioner)
    ):
        raise NamespaceAuthError(403)
    return NamespacePrincipal(issuer=issuer, subject=subject)
