"""Tracker human access client; source clocks are only attenuated, never renewed."""

from __future__ import annotations

import hashlib
import json
import os
import time
from urllib.parse import urlparse

import httpx
from fastapi import Request

from project_workflow.domain.project_admission import (
    HumanProjectScope,
    ProjectAccessV2,
    SpaceAccessDenied,
)


def policy_active() -> bool:
    return os.environ.get("PROJECT_WORKFLOW_SPACES__ENABLED") == "true"


async def confirm(request: Request, *, token: str, issuer: str, subject: str, role: str,
                  original_started: float, token_expiry: float) -> HumanProjectScope:
    if role not in {"member", "user", "operator", "admin", "platform_admin",
                    "platform_operator", "editor", "platform_editor"}:
        raise SpaceAccessDenied("Confirmed human role required")
    origin = os.environ.get("PROJECT_WORKFLOW_SPACES__TRACKER_URL", "")
    instance = os.environ.get("PROJECT_WORKFLOW_SPACES__TRACKER_INSTANCE_ID", "")
    url = urlparse(origin)
    if (url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in {"", "/"} or not instance):
        raise ValueError("Project admission is not configured")
    async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
        response = await client.get(origin.rstrip("/") + "/api/v2/sdlc/project-access",
                                    headers={"Authorization": f"Bearer {token}"})
    if response.status_code in {401, 403}:
        raise SpaceAccessDenied("Project admission denied")
    response.raise_for_status()
    proof = ProjectAccessV2.model_validate(response.json())
    mono, now = time.monotonic(), time.time()
    if (proof.identity.issuer != issuer or proof.identity.subject != subject
            or proof.tracker_instance_id != instance or proof.validity.observed_at > now + 1
            or proof.validity.valid_until > token_expiry):
        raise ValueError("Project admission identity or clock mismatch")
    deadline = min(original_started + 60, mono + proof.validity.valid_until - now, mono + token_expiry - now)
    scope = HumanProjectScope(proof, deadline, role)
    scope.require_current()
    request.state.project_scope = scope
    return scope


def display_window() -> dict:
    """Display metadata only; every resource retains its own server-side admission."""
    from project_workflow.domain.project_admission import human_scope
    if not policy_active():
        return {"schema_version": 1, "enforced": False, "remaining_millis": None, "scope_revision": None}
    scope = human_scope.get()
    if scope is None:
        raise SpaceAccessDenied("Human owner admission required")
    scope.require_current()
    remaining = int(min(scope.deadline - time.monotonic(),
                        scope.proof.validity.valid_until - time.time()) * 1000)
    if not 1 <= remaining <= 60_000:
        raise SpaceAccessDenied("Original project admission expired")
    rights = scope.proof.model_dump(mode="json", exclude={"validity"})
    # List order and a new clock are not changes to effective access.
    for name in ("readable_spaces", "writable_spaces", "project_ids", "writable_project_ids"):
        rights[name] = sorted(rights[name], key=lambda value: json.dumps(value, sort_keys=True))
    rights["product_role"] = scope.product_role
    revision = hashlib.sha256(json.dumps(rights, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"schema_version": 1, "enforced": True, "remaining_millis": remaining, "scope_revision": revision}


async def space_admission():
    from fastapi.responses import JSONResponse
    return JSONResponse(display_window(), headers={"Cache-Control": "private, no-store"})
