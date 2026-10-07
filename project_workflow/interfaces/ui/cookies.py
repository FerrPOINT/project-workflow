"""Keep central-mode browser state separate for applications sharing a host."""

from __future__ import annotations

import hashlib

from project_workflow.config import Settings


def cookie_name(settings: Settings, prefix: str) -> str:
    if not settings.AUTH_ISSUER:
        return prefix
    # Cookie scope has no port; use configured endpoints, never the request Host.
    scope = settings.AUTH_ISSUER.rstrip("/") + "\n" + settings.AUTH_PUBLIC_ORIGIN.rstrip("/")
    return f"{prefix}_{hashlib.sha256(scope.encode()).hexdigest()}"
