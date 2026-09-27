"""Private role-scoped runtime bridge for isolated Hermes wrappers."""

from __future__ import annotations

import hmac
import json
from typing import Any

from fastapi import Header, Query
from fastapi.responses import JSONResponse

from project_workflow import config, supervisor
from project_workflow.application.task import TaskService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import (
    RuntimeStepFence,
    normalize_role_key,
    payload_sha256,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import _require_valid_key, _resolve_namespace_id
from project_workflow.interfaces.ui.schemas import RuntimeAssignmentRequest, RuntimeStepRequest
from project_workflow.supervisor import format_result

_CATALOG_ROLE = "fleet-control"


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _configured_tokens(setting_name: str) -> dict[str, str]:
    raw = str(getattr(config.get_settings(), setting_name)).strip()
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
        try:
            normalized_role = normalize_role_key(role)
        except ValueError as exc:
            raise RuntimeError("Некорректная конфигурация runtime tokens") from exc
        if not isinstance(token, str) or len(token) < 32 or normalized_role in result:
            raise RuntimeError("Некорректная конфигурация runtime tokens")
        result[normalized_role] = token
    if len(result.values()) != len(set(result.values())):
        raise RuntimeError("Runtime tokens должны быть уникальными")
    return result


def _token_configuration() -> tuple[dict[str, str], dict[str, str], str]:
    runtime_tokens = _configured_tokens("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON")
    assignment_tokens = _configured_tokens("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON")
    catalog_token = config.get_settings().PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN.strip()
    if catalog_token and len(catalog_token) < 32:
        raise RuntimeError("Некорректная конфигурация Fleet catalog token")
    runtime_values = set(runtime_tokens.values())
    assignment_values = set(assignment_tokens.values())
    if runtime_values & assignment_values:
        raise RuntimeError("Assignment tokens должны отличаться от runtime и catalog tokens")
    if catalog_token and catalog_token in runtime_values | assignment_values:
        raise RuntimeError("Service tokens разных ролей должны быть уникальными")
    return runtime_tokens, assignment_tokens, catalog_token


def _authorized_role(authorization: str | None) -> str | None:
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        return None
    supplied = authorization[len(prefix) :]
    matched: str | None = None
    runtime_tokens, _, catalog_token = _token_configuration()
    if catalog_token:
        if hmac.compare_digest(supplied, catalog_token):
            matched = _CATALOG_ROLE
    for role, expected in runtime_tokens.items():
        if hmac.compare_digest(supplied, expected):
            matched = role
    return matched


def _authorized_assignment_role(authorization: str | None) -> str | None:
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        return None
    supplied = authorization[len(prefix) :]
    runtime_tokens, assignment_tokens, catalog_token = _token_configuration()
    if supplied in runtime_tokens.values() or supplied == catalog_token:
        return None
    for role, expected in assignment_tokens.items():
        if hmac.compare_digest(supplied, expected):
            return role
    return None


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


def _step_response(result: dict[str, Any]) -> dict[str, Any]:
    exit_code = 1 if result.get("verdict") == "BLOCKED" else 0
    return {
        "ok": exit_code == 0,
        "exit_code": exit_code,
        "output": format_result(result),
        "result": result,
    }


def _runtime_step_replay(
    uow: SAUnitOfWork,
    *,
    payload: RuntimeStepRequest,
    request_sha256: str,
    role_key: str,
    namespace_id: int,
    task_key: str,
) -> dict[str, Any] | None:
    """Return one exact committed response or reject an operation-key collision."""
    entry = uow.step_history.get_by_step_operation_key(payload.step_operation_key)
    if entry is None:
        return None
    history = entry.to_dict()
    task = uow.tasks.get_by_id(entry.task_id)
    assignment_operation_key = history.get("assignment_operation_key")
    assignment = (
        uow.tasks.get_assignment_by_operation_key(assignment_operation_key)
        if isinstance(assignment_operation_key, str)
        else None
    )
    assignment_data = assignment.to_dict() if assignment is not None else {}
    expected_history = {
        "step_operation_key": payload.step_operation_key,
        "request_sha256": request_sha256,
        "assignment_revision": payload.assignment_revision,
        "assignment_ref": payload.assignment_ref,
        "binding_ref": payload.binding_ref,
        "hermes_run_ref": payload.hermes_run_ref,
        "mode_key": payload.mode_key,
        "cycle_number": payload.cycle_number,
        "attempt_number": payload.attempt_number,
        "role_key": role_key,
    }
    mismatched = [
        name for name, value in expected_history.items() if history.get(name) != value
    ]
    invalid_task = (
        task is None
        or task.project_id != namespace_id
        or task.task_key != task_key
        or task.assignment_revision != history.get("assignment_revision")
        or task.assignment_operation_key != assignment_operation_key
        or task.mode_id != history.get("mode_id")
        or task.mode_key != history.get("mode_key")
        or task.cycle_number != history.get("cycle_number")
    )
    immutable_fields = (
        "task_id",
        "workflow_id",
        "assignment_revision",
        "assignment_ref",
        "binding_ref",
        "hermes_run_ref",
        "mode_id",
        "mode_key",
        "cycle_number",
        "attempt_number",
        "role_key",
    )
    invalid_assignment = (
        assignment is None
        or assignment_data.get("project_id") != namespace_id
        or assignment_data.get("operation_key") != assignment_operation_key
        or any(assignment_data.get(name) != history.get(name) for name in immutable_fields)
    )
    if mismatched or invalid_task or invalid_assignment:
        raise ConflictError("step_operation_key уже использован для другого runtime step")
    response = history.get("supervisor_response")
    if not isinstance(response, dict):
        raise ConflictError("Сохранённый runtime step не содержит корректный ответ")
    result = dict(response)
    result["replayed"] = True
    return _step_response(result)


def execute_namespace_step(
    uow: SAUnitOfWork,
    *,
    namespace_id: int,
    task: str,
    report: str | None,
    create_if_missing: bool,
    runtime_fence: RuntimeStepFence | None = None,
) -> dict[str, Any]:
    """Execute one Supervisor step inside an already-authorized namespace."""
    task_key = _require_valid_key(task, uow, project_id=namespace_id)
    _assert_task_key_in_namespace(uow, namespace_id, task_key)
    engine = supervisor.SupervisorEngine(
        task_key,
        uow=uow,
        create_if_missing=create_if_missing,
        project_id=namespace_id,
        runtime_fence=runtime_fence,
    )
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
    return _step_response(result)


def runtime_assign(
    payload: RuntimeAssignmentRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Accept one authorized Business assignment and persist its technical cursor."""
    try:
        role = _authorized_assignment_role(authorization)
    except RuntimeError as exc:
        return _error(str(exc), 503)
    if role is None:
        try:
            # A valid execution/catalog credential is deliberately distinguishable
            # from an unknown credential: only the adapter credential may assign.
            if _authorized_role(authorization) is not None:
                return _error("Runtime token не разрешает назначение задач", 403)
        except RuntimeError as exc:
            return _error(str(exc), 503)
        return _error("Недействительный runtime token", 401)
    if payload.role_key != role:
        return _error("role_key не совпадает с ролью assignment token", 403)
    try:
        with SAUnitOfWork() as uow:
            namespace_id = _namespace_id(uow, role)
            task_key = _require_valid_key(payload.task, uow, project_id=namespace_id)
            _assert_task_key_in_namespace(uow, namespace_id, task_key)
            task = TaskService(uow).assign_runtime_task(
                project_id=namespace_id,
                task_key=task_key,
                role_key=payload.role_key,
                workflow_key=payload.workflow_key,
                mode_key=payload.mode_key,
                execution_scope=payload.execution_scope,
                stage_key=payload.stage_key,
                cycle_number=payload.cycle_number,
                attempt_number=payload.attempt_number,
                operation_key=payload.operation_key,
                business_task_ref=payload.business_task_ref,
                root_task_ref=payload.root_task_ref,
                work_item_ref=payload.work_item_ref,
                work_item_revision=payload.work_item_revision,
                queue_item_ref=payload.queue_item_ref,
                task_workspace_ref=payload.task_workspace_ref,
                workspace_revision=payload.workspace_revision,
                tech_execution_workspace_ref=payload.tech_execution_workspace_ref,
                tech_execution_attempt_ref=payload.tech_execution_attempt_ref,
                decomposition_revision_ref=payload.decomposition_revision_ref,
                stage_revision=payload.stage_revision,
                assignment_ref=payload.assignment_ref,
                binding_ref=payload.binding_ref,
                hermes_run_ref=payload.hermes_run_ref,
                workspace_generation=payload.workspace_generation,
                lease_generation=payload.lease_generation,
                exact_input_refs=[item.model_dump() for item in payload.exact_input_refs],
                expected_revision=payload.expected_revision,
                expected_status=payload.expected_status,
                expected_mode_key=payload.expected_mode_key,
                expected_cycle_number=payload.expected_cycle_number,
            )
            return {
                "ok": True,
                "exit_code": 0,
                "result": {
                    "task_key": task_key,
                    "workflow_id": task["workflow_id"],
                    "workflow_key": task["workflow_key"],
                    "mode_id": task["mode_id"],
                    "mode_key": task["mode_key"],
                    "cycle_number": task["cycle_number"],
                    "attempt_number": task["attempt_number"],
                    "assignment_operation_key": task["assignment_operation_key"],
                    "assignment_revision": task["assignment_revision"],
                    "role_key": task["role_key"],
                    "execution_scope": task["execution_scope"],
                    "stage_key": task["stage_key"],
                    "business_task_ref": task["business_task_ref"],
                    "root_task_ref": task["root_task_ref"],
                    "work_item_ref": task["work_item_ref"],
                    "work_item_revision": task["work_item_revision"],
                    "queue_item_ref": task["queue_item_ref"],
                    "task_workspace_ref": task["task_workspace_ref"],
                    "workspace_revision": task["workspace_revision"],
                    "tech_execution_workspace_ref": task["tech_execution_workspace_ref"],
                    "tech_execution_attempt_ref": task["tech_execution_attempt_ref"],
                    "decomposition_revision_ref": task["decomposition_revision_ref"],
                    "stage_revision": task["stage_revision"],
                    "assignment_ref": task["assignment_ref"],
                    "binding_ref": task["binding_ref"],
                    "hermes_run_ref": task["hermes_run_ref"],
                    "workspace_generation": task["workspace_generation"],
                    "lease_generation": task["lease_generation"],
                    "exact_input_refs": task["exact_input_refs"],
                    "status": task["status"],
                    "current_phase_id": task["current_phase_id"],
                    "current_phase_code": task["current_phase_code"],
                    "current_phase_name": task["current_phase_name"],
                },
            }
    except (ConflictError, RuntimeError, ValueError) as exc:
        return _error(str(exc), 409)


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
    request_digest = payload_sha256(payload.model_dump(mode="json"))
    try:
        with SAUnitOfWork() as uow:
            namespace_id = _namespace_id(uow, role)
            task_key = _require_valid_key(payload.task, uow, project_id=namespace_id)
            _assert_task_key_in_namespace(uow, namespace_id, task_key)
            replay = _runtime_step_replay(
                uow,
                payload=payload,
                request_sha256=request_digest,
                role_key=role,
                namespace_id=namespace_id,
                task_key=task_key,
            )
            if replay is not None:
                return replay
            fence = TaskService(uow).validate_runtime_step(
                project_id=namespace_id,
                task_key=task_key,
                role_key=role,
                step_operation_key=payload.step_operation_key,
                request_sha256=request_digest,
                assignment_revision=payload.assignment_revision,
                assignment_ref=payload.assignment_ref,
                binding_ref=payload.binding_ref,
                hermes_run_ref=payload.hermes_run_ref,
                mode_key=payload.mode_key,
                cycle_number=payload.cycle_number,
                attempt_number=payload.attempt_number,
                expected_phase_code=payload.expected_phase_code,
                expected_status=payload.expected_status,
            )
            try:
                return execute_namespace_step(
                    uow,
                    namespace_id=namespace_id,
                    task=task_key,
                    report=payload.report,
                    create_if_missing=False,
                    runtime_fence=fence,
                )
            except (ConflictError, RuntimeError, ValueError):
                uow.rollback()
                replay = _runtime_step_replay(
                    uow,
                    payload=payload,
                    request_sha256=request_digest,
                    role_key=role,
                    namespace_id=namespace_id,
                    task_key=task_key,
                )
                if replay is not None:
                    return replay
                raise
    except (ConflictError, RuntimeError, ValueError) as exc:
        return _error(str(exc), 409)


def runtime_history(
    task: str = Query(...),
    n: int = Query(default=200, ge=1, le=200),
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
