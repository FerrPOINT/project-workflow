"""Private role-scoped runtime bridge for isolated Hermes wrappers."""

from __future__ import annotations

import hmac
import json
import re
from typing import Any

from fastapi import Header, Query
from fastapi.responses import JSONResponse

from project_workflow import config, supervisor
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import _require_valid_key, _resolve_namespace_id
from project_workflow.interfaces.ui.schemas import RuntimeStepRequest
from project_workflow.supervisor import format_result

_ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
_CATALOG_ROLE = "fleet-control"


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _runtime_tokens() -> dict[str, str]:
    raw = config.get_settings().PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON.strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Некорректная конфигурация runtime tokens") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Некорректная конфигурация runtime tokens")
    result: dict[str, str] = {}
    for role, token in value.items():
        if (
            not isinstance(role, str)
            or _ROLE_RE.fullmatch(role) is None
            or not isinstance(token, str)
            or len(token) < 32
        ):
            raise RuntimeError("Некорректная конфигурация runtime tokens")
        result[role] = token
    if len(result.values()) != len(set(result.values())):
        raise RuntimeError("Runtime tokens должны быть уникальными")
    return result


def _authorized_role(authorization: str | None) -> str | None:
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        return None
    supplied = authorization[len(prefix) :]
    matched: str | None = None
    runtime_tokens = _runtime_tokens()
    catalog_token = config.get_settings().PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN.strip()
    if catalog_token:
        if len(catalog_token) < 32 or catalog_token in runtime_tokens.values():
            raise RuntimeError("Некорректная конфигурация Fleet catalog token")
        if hmac.compare_digest(supplied, catalog_token):
            matched = _CATALOG_ROLE
    for role, expected in runtime_tokens.items():
        if hmac.compare_digest(supplied, expected):
            matched = role
    return matched


def _namespace_id(uow: SAUnitOfWork, role: str) -> int:
    value = _resolve_namespace_id(uow, f"workflow-{role}")
    if value is None:
        raise ValueError("Namespace роли не найден")
    return value


def _assert_task_key_in_namespace(uow: SAUnitOfWork, namespace_id: int, task_key: str) -> None:
    """Role token may only touch tasks whose key prefix belongs to its namespace.

    Namespaces without configured prefixes impose no prefix policy (master
    treats key_prefixes as metadata, not routing rules); namespaces with
    prefixes restrict the bridge to their own keys.
    """
    project = uow.projects.get_by_id(namespace_id)
    if project is None:
        raise ValueError("Namespace роли не найден")
    prefixes = [prefix for prefix in (project.to_dict().get("key_prefixes") or []) if prefix]
    if not prefixes:
        return
    if not any(task_key == prefix or task_key.startswith(f"{prefix}-") for prefix in prefixes):
        raise ValueError(
            f"Ключ задачи {task_key!r} не соответствует префиксам неймспейса роли"
        )


def _history_rows(uow: SAUnitOfWork, task_key: str, namespace_id: int, limit: int | None) -> list[dict[str, Any]]:
    task = uow.tasks.get_by_key(task_key, project_id=namespace_id)
    task_id = task.id if task else None
    rows: list[dict[str, Any]] = []
    for entry in uow.step_history.list(
        task_id=task_id,
        task_key=task_key,
        project_id=namespace_id,
        limit=limit,
    ):
        item = entry.to_dict()
        supervisor_response = item.get("supervisor_response")
        if not isinstance(supervisor_response, dict):
            supervisor_response = {}
        phase = uow.phases.get_by_id(int(item.get("phase_id") or 0))
        next_id = item.get("next_phase_id")
        rollback_id = item.get("rollback_phase_id")
        next_phase = uow.phases.get_by_id(int(next_id)) if next_id is not None else None
        rollback = uow.phases.get_by_id(int(rollback_id)) if rollback_id is not None else None
        if phase is None:
            raise ValueError("История step ссылается на неизвестную фазу")
        rows.append(
            {
                "phase_code": phase.code,
                "verdict": item.get("verdict"),
                "worker_report": item.get("worker_report"),
                "supervisor_message": supervisor_response.get("message"),
                "retryable": supervisor_response.get("retryable") is True,
                "next_phase_code": next_phase.code if next_phase else None,
                "rollback_phase_code": rollback.code if rollback else None,
                "created_at": item.get("created_at"),
                "workflow_id": item.get("workflow_id"),
                "mode_id": item.get("mode_id"),
                "mode_key": item.get("mode_key"),
                "cycle_number": item.get("cycle_number"),
            }
        )
    return rows


def execute_namespace_step(
    uow: SAUnitOfWork,
    *,
    namespace_id: int,
    task: str,
    report: str | None,
) -> dict[str, Any]:
    """Execute one Supervisor step inside an already-authorized namespace."""
    task_key = _require_valid_key(task, uow, project_id=namespace_id)
    _assert_task_key_in_namespace(uow, namespace_id, task_key)
    engine = supervisor.SupervisorEngine(task_key, uow=uow, project_id=namespace_id)
    if report is None:
        if engine._get_current_phase_obj() is None:
            result = engine._blocked_result()
            return {
                "ok": False,
                "exit_code": 1,
                "output": format_result(result),
                "result": result,
            }
        result = {
            "ok": True,
            "task_key": task_key,
            "phase_code": engine.current_phase_code,
            "status": engine.task.get("status") if engine.task else None,
            "instructions": engine.format_current_phase_instructions(),
            "phase_contract": engine.get_phase_contract(),
            "workflow_id": engine.task.get("workflow_id") if engine.task else None,
            "mode_id": engine.task.get("mode_id") if engine.task else None,
            "mode_key": engine.task.get("mode_key") if engine.task else None,
            "cycle_number": engine.task.get("cycle_number") if engine.task else None,
        }
        return {"ok": True, "exit_code": 0, "output": result["instructions"], "result": result}
    result = engine.evaluate(report)
    exit_code = 1 if result["verdict"] == "BLOCKED" else 0
    return {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "output": format_result(result),
        "result": result,
    }


def runtime_step(
    payload: RuntimeStepRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Execute one role-scoped step in the trusted workflow service."""
    try:
        role = _authorized_role(authorization)
    except RuntimeError as exc:
        return _error(str(exc), 503)
    if role is None:
        return _error("Недействительный runtime token", 401)
    if role == _CATALOG_ROLE:
        return _error("Токен каталога не разрешает выполнение шагов", 403)
    try:
        with SAUnitOfWork() as uow:
            namespace_id = _namespace_id(uow, role)
            return execute_namespace_step(
                uow,
                namespace_id=namespace_id,
                task=payload.task,
                report=payload.report,
            )
    except (ConflictError, RuntimeError, ValueError) as exc:
        return _error(str(exc), 409)


def runtime_history(
    task: str = Query(...),
    n: int | None = Query(default=None, ge=1),
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Return history only from the namespace bound to the supplied role token."""
    try:
        role = _authorized_role(authorization)
    except RuntimeError as exc:
        return _error(str(exc), 503)
    if role is None:
        return _error("Недействительный runtime token", 401)
    if role == _CATALOG_ROLE:
        return _error("Токен каталога не разрешает чтение истории", 403)
    try:
        with SAUnitOfWork() as uow:
            namespace_id = _namespace_id(uow, role)
            task_key = _require_valid_key(task, uow, project_id=namespace_id)
            _assert_task_key_in_namespace(uow, namespace_id, task_key)
            rows = _history_rows(uow, task_key, namespace_id, n)
            return {
                "ok": True,
                "exit_code": 0,
                "output": json.dumps(rows, ensure_ascii=False),
                "result": {"task_key": task_key, "count": len(rows), "records": rows},
            }
    except (ConflictError, RuntimeError, ValueError) as exc:
        return _error(str(exc), 409)


async def runtime_catalog(
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Expose only the namespace/workflow directory to Fleet Control."""
    try:
        role = _authorized_role(authorization)
    except RuntimeError as exc:
        return _error(str(exc), 503)
    if role is None:
        return _error("Недействительный runtime token", 401)
    if role != _CATALOG_ROLE:
        return _error("Токен не разрешает чтение каталога", 403)
    from . import api

    namespaces = await api.api_namespaces()
    workflows = await api.api_workflows()
    if not isinstance(namespaces, dict) or not isinstance(workflows, dict):
        return _error("Каталог временно недоступен", 503)
    return {
        "ok": True,
        "namespaces": namespaces["namespaces"],
        "workflows": workflows["workflows"],
    }
