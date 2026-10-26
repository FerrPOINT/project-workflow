"""The two existing CLI commands over configured runtime HTTP, without local files."""

from __future__ import annotations

import os
import sys
from typing import Any
from urllib.parse import urlsplit

import requests

from project_workflow.domain.configured_cli import PROTOCOL, ConfiguredStep
from project_workflow.domain.namespace_ownership import canonical_uuid
from project_workflow.infrastructure.platform_namespace import is_personal_token


def enabled() -> bool:
    protocol = os.environ.get("FLEET_CLI_PROTOCOL")
    if protocol is not None and protocol != PROTOCOL:
        raise ValueError("Unsupported FLEET_CLI_PROTOCOL; no fallback")
    return protocol == PROTOCOL


def environment() -> tuple[str, str, str, int]:
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
        canonical_uuid(agent)
        if not namespace.isdecimal() or int(namespace) < 1:
            raise ValueError
        if not is_personal_token(token) or len(token) > 4096 or any(not 33 <= ord(c) <= 126 for c in token):
            raise ValueError
    except ValueError:
        raise ValueError("Configured CLI requires explicit URL, dedicated PAT, agent UUID and namespace; no fallback")\
            from None
    return url.rstrip("/"), token, agent, int(namespace)


def failure(code: str, *, http_status: int | None = None, unknown: bool = False) -> dict[str, Any]:
    return {"ok": False, "exit_code": 1, "result": {
        "ok": False, "error_code": code, "http_status": http_status,
        "acceptance_unknown": unknown, "error": "Configured CLI failed; retain exact write key/version/report",
    }}


def request(method: str, route: str, task: str, *, body: dict | None = None, params: dict | None = None) -> dict:
    root, token, agent, namespace = environment()
    try:
        from pdlc_cli_core import ApiClient, ApiError
    except ImportError:
        return failure("shared-transport-unavailable")
    try:
        # Reuse Base origin admission and its permanent trusted-origin environment.
        # The explicit token never falls back to the general PDLC PAT.
        admitted = ApiClient(root, token=token)
    except ApiError:
        return failure("origin-or-credential-configuration-invalid")
    try:
        with requests.Session() as client:
            client.trust_env = False
            with client.request(method, admitted.base_url + "internal/runtime/" + route, json=body, params=params,
                                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                                timeout=(3, 120), allow_redirects=False, stream=True) as response:
                status = response.status_code
                if not 200 <= status < 300:
                    return failure("http-refused", http_status=status, unknown=method == "POST" and status >= 500)
                raw = bytearray()
                for chunk in response.iter_content(chunk_size=4096):
                    raw.extend(chunk)
                    if len(raw) > 1024 * 1024:
                        return failure("response-too-large", http_status=status, unknown=method == "POST")
        import json

        value = json.loads(raw)
        result = value.get("result") if isinstance(value, dict) else None
        if (not isinstance(result, dict) or value.get("ok") is not True or value.get("exit_code") != 0
                or result.get("interaction_protocol") != PROTOCOL or result.get("task") != task
                or result.get("namespace_id") != namespace or result.get("concrete_agent_ref") != agent):
            return failure("response-identity-invalid", http_status=status, unknown=method == "POST")
        return value
    except requests.RequestException:
        return failure("transport-unavailable", unknown=method == "POST")
    except (ValueError, TypeError, KeyError):
        return failure("response-invalid", unknown=method == "POST")


def step(task: str, report: str | None, operation_key: str | None, expected_version: int | None, *,
         requirements_revision: int | None = None, requirements_sha256: str | None = None) -> dict:
    _, _, _, namespace = environment()
    if report == "-":
        report = sys.stdin.read(32_001)
    command = ConfiguredStep(interaction_protocol=PROTOCOL, task=task, namespace_id=namespace,
                             report=report, operation_key=operation_key, expected_version=expected_version,
                             requirements_revision=requirements_revision, requirements_sha256=requirements_sha256)
    return request("POST", "step", task, body=command.model_dump(mode="json"))


def history(task: str, n: int | None, operation_key: str | None, execution_ref: str | None) -> dict:
    _, _, _, namespace = environment()
    return request("GET", "history", task, params={"interaction_protocol": PROTOCOL, "task": task,
        "namespace_id": namespace, "n": min(n or 200, 200),
        **({"operation_key": operation_key} if operation_key else {}),
        **({"execution_ref": execution_ref} if execution_ref else {})})
