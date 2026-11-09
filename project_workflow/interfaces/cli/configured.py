"""The two existing CLI commands over configured runtime HTTP, without local files."""

from __future__ import annotations

import os
import sys
from typing import Any
from urllib.parse import urlsplit

from project_workflow.domain.background import BackgroundConclusion, BackgroundStep
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


def _archive_page(result: dict[str, Any]) -> bool:
    if (set(result) != {"interaction_protocol", "task", "namespace_id", "archived", "records", "next_before"}
            or result["archived"] is not True or type(result["namespace_id"]) is not int
            or not isinstance(result["records"], list)):
        return False
    records = result["records"]
    for record in records:
        if (not isinstance(record, dict) or set(record) != {"history_id", "worker_report", "result"}
                or type(record["history_id"]) is not int or not 0 < record["history_id"] <= 2**63 - 1
                or not isinstance(record["worker_report"], str) or not isinstance(record["result"], dict)):
            return False
    before = result["next_before"]
    return before is None or (
        type(before) is int and 0 < before <= 2**63 - 1
        and bool(records) and before == records[-1]["history_id"]
    )


def request(method: str, route: str, task: str, *, body: dict | None = None, params: dict | None = None) -> dict:
    root, token, agent, namespace = environment()
    local = mode() == "standalone"
    background_run = ((body or {}).get("run_id") if (body or {}).get("execution_mode") == "background"
                      else (params or {}).get("background_run"))
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
                or result.get("namespace_id") != namespace):
            return failure("response-identity-invalid", unknown=write)
        if "archived" in result:
            ordinary_page = (not local and background_run is None
                             and method == "GET" and route == "history" and body is None
                             and not any(key in (params or {}) for key in (
                                 "operation_key", "execution_ref", "projection", "assignment_operation_key")))
            if not ordinary_page or type(value.get("exit_code")) is not int or not _archive_page(result):
                return failure("response-identity-invalid", unknown=write)
        elif (result.get("execution_mode") != "standalone" if local else result.get("concrete_agent_ref") != agent):
            return failure("response-identity-invalid", unknown=write)
        if background_run is not None and (
                result.get("execution_mode") != "background" or result.get("run_id") != background_run):
            return failure("response-identity-invalid", unknown=write)
        return value
    except ApiError as error:
        return failure(error.code, http_status=error.http_status, unknown=write and error.acceptance_unknown)


def step(task: str | None, report: str | None, operation_key: str | None, expected_version: int | None, *,
         requirements_revision: int | None = None, requirements_sha256: str | None = None,
         start: bool = False, workflow_id: int | None = None, mode_key: str | None = None,
         background_run: str | None = None, research_result: dict[str, Any] | None = None) -> dict:
    _, _, _, namespace = environment()
    if report == "-":
        report = sys.stdin.read()
    if report is not None:
        PhaseReport.parse(report)
    if background_run is not None:
        if (mode() != "platform" or task is not None or start or workflow_id is not None or mode_key is not None
                or requirements_revision is not None or requirements_sha256 is not None):
            raise ValueError("Background invocation cannot select Tracker, standalone or runtime settings")
        background_command = BackgroundStep(interaction_protocol=PROTOCOL, execution_mode="background",
            run_id=canonical_uuid(background_run), namespace_id=namespace,
            report=report, operation_key=operation_key, expected_version=expected_version,
            research_result=(BackgroundConclusion.model_validate(research_result)
                             if research_result is not None else None))
        key = "BG-" + background_run.replace("-", "").upper()
        return request("POST", "step", key, body=background_command.model_dump(mode="json"))
    if task is None:
        raise ValueError("Explicit task or background run required")
    if research_result is not None:
        raise ValueError("Research result belongs only to background execution")
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


def history(task: str | None, n: int | None, operation_key: str | None, execution_ref: str | None,
            before_history_id: int | None = None, *, diagnostics: bool = False,
            background_run: str | None = None) -> dict:
    _, _, _, namespace = environment()
    if background_run is not None:
        if (mode() != "platform" or task is not None or diagnostics or execution_ref is not None
                or n is not None and not 1 <= n <= 200
                or before_history_id is not None and (before_history_id <= 0 or operation_key is not None)):
            raise ValueError("Invalid background history selector")
        canonical_uuid(background_run)
        key = "BG-" + background_run.replace("-", "").upper()
        return request("GET", "history", key, params={"interaction_protocol": PROTOCOL,
            "background_run": background_run, "namespace_id": namespace, "n": n or 200,
            **({"operation_key": operation_key} if operation_key else {}),
            **({"before_history_id": before_history_id} if before_history_id is not None else {})})
    if task is None:
        raise ValueError("Explicit task or background run required")
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
