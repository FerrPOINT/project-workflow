"""The two existing CLI commands over configured runtime HTTP, without local files."""

from __future__ import annotations

import os
import sys
from typing import Any
from urllib.parse import urlsplit

from project_workflow.domain.configured_cli import PROTOCOL, ConfiguredStep
from project_workflow.domain.namespace_ownership import canonical_uuid
from project_workflow.domain.phase_report import PhaseReport
from project_workflow.domain.standalone import StandaloneStep
from project_workflow.infrastructure.platform_namespace import is_personal_token

_RESPONSE_BYTES = 1024 * 1024
_HISTORY_RESPONSE_BYTES = 64 * _RESPONSE_BYTES


def validate_protocol() -> None:
    if os.environ.get("FLEET_CLI_PROTOCOL", PROTOCOL) != PROTOCOL:
        raise ValueError("Unsupported FLEET_CLI_PROTOCOL; no fallback")


def mode() -> str:
    value = os.environ.get("PROJECT_WORKFLOW_MODE", "platform")
    if value not in {"platform", "standalone"}:
        raise ValueError("Explicit supported Workflow mode required")
    return value


def environment() -> tuple[str, str, str, int]:
    validate_protocol()
    url = os.environ.get("PROJECT_WORKFLOW_URL", "").strip()
    token = os.environ.get("PROJECT_WORKFLOW_API_TOKEN", "")
    agent = os.environ.get("FLEET_AGENT_ID", "")
    namespace = os.environ.get("PROJECT_WORKFLOW_NAMESPACE_ID", "")
    try:
        parsed = urlsplit(url)
        if (not url or parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment or "\\" in url
                or any(c.isspace() or ord(c) < 32 for c in url)):
            raise ValueError
        _ = parsed.port
        if mode() == "platform":
            canonical_uuid(agent)
        elif parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError
        if not namespace.isdecimal() or int(namespace) < 1:
            raise ValueError
        if mode() == "platform" and (
                not is_personal_token(token) or len(token) > 4096 or any(not 33 <= ord(c) <= 126 for c in token)):
            raise ValueError
    except ValueError:
        raise ValueError("Configured CLI requires explicit URL, dedicated PAT, agent UUID and namespace; no fallback")\
            from None
    return url.rstrip("/"), token if mode() == "platform" else "", agent, int(namespace)


def failure(code: str, *, http_status: int | None = None, unknown: bool = False) -> dict[str, Any]:
    return {"ok": False, "exit_code": 1, "result": {
        "ok": False, "error_code": code, "http_status": http_status,
        "acceptance_unknown": unknown, "error": "Configured CLI failed; retain exact write key/version/report",
    }}


def request(method: str, route: str, task: str, *, body: dict | None = None, params: dict | None = None) -> dict:
    root, token, agent, namespace = environment()
    local = mode() == "standalone"
    write = method == "POST" and body is not None and (body.get("report") is not None or body.get("start") is True)
    try:
        from pdlc_cli_core import ApiClient, ApiError
    except ImportError:
        return failure("shared-transport-unavailable")
    try:
        auth_options: dict[str, Any] = {"require_token": False} if local else {}
        response_budget = (_HISTORY_RESPONSE_BYTES
                           if method == "GET" and route == "history" and not (params or {}).get("projection")
                           else _RESPONSE_BYTES)
        client = ApiClient(root, token=token, timeout=(30, 1500),
                           max_response_bytes=response_budget, trust_env=False, **auth_options)
    except ApiError:
        return failure("origin-or-credential-configuration-invalid")
    except TypeError:
        return failure("shared-transport-incompatible")
    try:
        value = client.request_json(method, "internal/runtime/" + route, body=body, params=params)
        result = value.get("result")
        if (not isinstance(result, dict) or value.get("ok") is not True or value.get("exit_code") != 0
                or result.get("interaction_protocol") != PROTOCOL or result.get("task") != task
                or result.get("namespace_id") != namespace
                or (result.get("execution_mode") != "standalone" if local
                    else result.get("concrete_agent_ref") != agent)):
            return failure("response-identity-invalid", unknown=write)
        return value
    except ApiError as error:
        return failure(error.code, http_status=error.http_status, unknown=write and error.acceptance_unknown)


def step(task: str, report: str | None, operation_key: str | None, expected_version: int | None, *,
         requirements_revision: int | None = None, requirements_sha256: str | None = None,
         start: bool = False, workflow_id: int | None = None, mode_key: str | None = None) -> dict:
    _, _, _, namespace = environment()
    if report == "-":
        report = sys.stdin.read(32_001)
    if report is not None:
        PhaseReport.parse(report)
    if mode() == "standalone":
        if requirements_revision is not None or requirements_sha256 is not None:
            raise ValueError("Tracker confirmation is not a standalone parameter")
        local = StandaloneStep(interaction_protocol=PROTOCOL, task=task, namespace_id=namespace,
            start=start, workflow_id=workflow_id, mode_key=mode_key, report=report,
            operation_key=operation_key, expected_version=expected_version)
        return request("POST", "step", task, body=local.model_dump(mode="json"))
    if start or workflow_id is not None or mode_key is not None:
        raise ValueError("Explicit start belongs to standalone mode")
    command = ConfiguredStep(interaction_protocol=PROTOCOL, task=task, namespace_id=namespace,
                             report=report, operation_key=operation_key, expected_version=expected_version,
                             requirements_revision=requirements_revision, requirements_sha256=requirements_sha256)
    return request("POST", "step", task, body=command.model_dump(mode="json"))


def history(task: str, n: int | None, operation_key: str | None, execution_ref: str | None,
            before_history_id: int | None = None, *, diagnostics: bool = False) -> dict:
    _, _, _, namespace = environment()
    if mode() == "standalone" and (diagnostics or execution_ref is not None):
        raise ValueError("Platform projection is not a standalone history selector")
    if diagnostics and (n is not None and n != 1 or operation_key is not None or execution_ref is not None):
        raise ValueError("Diagnostics requires n=1 and cannot select an operation or execution")
    if before_history_id is not None and (before_history_id <= 0 or operation_key is not None):
        raise ValueError("A history page cursor cannot select an operation")
    return request("GET", "history", task, params={"interaction_protocol": PROTOCOL, "task": task,
        "namespace_id": namespace, "n": min(n or (1 if diagnostics else 200), 200),
        **({"projection": "evaluator-diagnostics-v1"} if diagnostics else {}),
        **({"operation_key": operation_key} if operation_key else {}),
        **({"before_history_id": before_history_id} if before_history_id is not None else {}),
        **({"execution_ref": execution_ref} if execution_ref else {})})
