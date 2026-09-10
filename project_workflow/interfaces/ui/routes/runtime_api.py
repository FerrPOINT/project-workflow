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
    for role, expected in _runtime_tokens().items():
        if hmac.compare_digest(supplied, expected):
            matched = role
    return matched


def _namespace_id(uow: SAUnitOfWork, role: str) -> int:
    value = _resolve_namespace_id(uow, f"workflow-{role}")
    if value is None:
        raise ValueError("Namespace роли не найден")
    return value


def _namespace_is_visible(uow: SAUnitOfWork, namespace_id: int) -> bool:
    namespace = uow.projects.get_by_id(namespace_id)
    if namespace is None:
        return False
    allowed = config.get_settings().visible_namespace_codes
    return not allowed or str(namespace.code).upper() in allowed


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
            }
        )
    return rows


def execute_namespace_step(
    uow: SAUnitOfWork,
    *,
    namespace_id: int,
    task: str,
    report: str | None,
    title: str | None = None,
) -> dict[str, Any]:
    """Execute one Supervisor step inside an already-authorized namespace."""
    if not _namespace_is_visible(uow, namespace_id):
        raise ValueError("Namespace не найден")
    task_key = _require_valid_key(task, uow, project_id=namespace_id)
    engine = supervisor.SupervisorEngine(task_key, uow=uow, project_id=namespace_id)
    if title is not None and engine.task is not None:
        current_title = str(engine.task.get("title") or "")
        task_id = engine.task.get("id")
        if task_id is not None and current_title in {"", task_key}:
            uow.tasks.update(int(task_id), {"title": title})
            uow.commit()
            engine.task["title"] = title
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
    try:
        with SAUnitOfWork() as uow:
            namespace_id = _namespace_id(uow, role)
            if not _namespace_is_visible(uow, namespace_id):
                return _error("Namespace не найден", 404)
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
    try:
        with SAUnitOfWork() as uow:
            namespace_id = _namespace_id(uow, role)
            if not _namespace_is_visible(uow, namespace_id):
                return _error("Namespace не найден", 404)
            task_key = _require_valid_key(task, uow, project_id=namespace_id)
            rows = _history_rows(uow, task_key, namespace_id, n)
            return {
                "ok": True,
                "exit_code": 0,
                "output": json.dumps(rows, ensure_ascii=False),
                "result": {"task_key": task_key, "count": len(rows), "records": rows},
            }
    except (ConflictError, RuntimeError, ValueError) as exc:
        return _error(str(exc), 409)
