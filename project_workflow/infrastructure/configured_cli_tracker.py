"""Fixed-root Tracker reads for current assignment and real owner confirmation."""

import json
import re
import time
from typing import Any

import httpx

from project_workflow import config
from project_workflow.domain.configured_cli import PROTOCOL
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure import namespace_auth

STAGES = {
    ("project_manager", "draft"): {"Draft", "Backlog"},
    ("analyst", "analysis"): {"Analysis"},
    ("architect", "decomposition"): {"Architecture"},
    ("developer", "initial"): {"Development"},
    ("developer", "rework"): {"Rework"},
    ("reviewer", "delivery"): {"Review"},
    ("tester", "delivery"): {"Testing"},
    ("devops", "delivery"): {"Deployment"},
}


def read(request: dict[str, Any], suffix: str) -> dict[str, Any]:
    settings = config.get_settings()
    try:
        root = namespace_auth._root(settings.PROJECT_WORKFLOW_CONFIGURED_TRACKER_URL)
    except ValueError:
        raise RuntimeError("Configured Tracker authority unavailable") from None
    token = settings.PROJECT_WORKFLOW_CONFIGURED_TRACKER_READ_TOKEN
    if not token:
        raise RuntimeError("Configured Tracker read credential unavailable")
    path = f"/api/v1/issues/{request['tracker_task_id']}/sdlc/{suffix}"
    try:
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            started = time.monotonic()
            with client.stream("GET", root + path, headers={"Authorization": "Bearer " + token}) as response:
                if response.status_code != 200:
                    raise ConflictError("Exact Tracker assignment/confirmation is unavailable")
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=1024):
                    body.extend(chunk)
                    if len(body) > 262144 or time.monotonic() - started > 5:
                        raise RuntimeError("Tracker read exceeded its bound")
                value = json.loads(body, object_pairs_hook=namespace_auth.unique_object)
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (httpx.HTTPError, ValueError):
        raise RuntimeError("Tracker authority readback unavailable") from None


def assignment(request: dict[str, Any], *, allow_completed_read: bool = False) -> None:
    context = read(request, "context")
    expected = {"assignment_id": request["assignment_ref"], "execution_id": request["tracker_execution_id"],
                "agent_id": request["concrete_agent_ref"], "version": request["assignment_version"],
                "machine_subject": request["machine_subject"]}
    actual = context.get("assignment")
    stages = STAGES.get((request["role_key"], request["mode_key"]), set())
    completed_pm = (allow_completed_read and request["role_key"] == "project_manager"
                    and request["mode_key"] == "draft" and context.get("stage") == "Backlog"
                    and context.get("status") == "Ready")
    active = (context.get("status") == "InProgress"
              and (request["role_key"] != "project_manager" or context.get("stage") == "Draft"))
    if (type(context.get("contract_version")) is not int or context.get("contract_version") != 1
            or context.get("interaction_protocol") != PROTOCOL
            or context.get("stage") not in stages
            or not (active or completed_pm)
            or not isinstance(actual, dict) or type(actual.get("version")) is not int
            or context.get("task_id") != request["tracker_task_id"]
            or context.get("root_task_id") != request["tracker_task_id"]
            or context.get("workflow_task_key") != request["task"]
            or context.get("owner_subject") != request["owner_subject"] or context.get("assignment") != expected):
        raise ConflictError("Current Tracker owner/assignment/agent differs from enrollment")


def confirmation(request: dict[str, Any]) -> dict[str, Any]:
    revision = read(request, "requirements")
    number, digest = revision.get("revision"), revision.get("content_hash")
    if (type(number) is not int or number <= 0 or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ConflictError("Latest requirements identity is invalid")
    accepted = read(request, f"requirements/{number}/confirmation")
    if (accepted.get("task_id") != request["tracker_task_id"] or type(accepted.get("revision")) is not int
            or accepted.get("revision") != number or accepted.get("content_hash") != digest
            or accepted.get("owner_subject") != request["owner_subject"] or accepted.get("stage") != "Draft"):
        raise ConflictError("Tracker confirmation does not match latest requirements and owner")
    try:
        namespace_auth.canonical_uuid(accepted.get("id", ""))
    except (ValueError, TypeError):
        raise ConflictError("Tracker confirmation ID is invalid") from None
    return accepted
