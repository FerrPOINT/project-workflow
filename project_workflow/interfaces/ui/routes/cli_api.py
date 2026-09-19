"""Human CLI HTTP endpoints; authentication is enforced by SSO middleware."""

from __future__ import annotations

from fastapi import Query
from fastapi.responses import JSONResponse
from pydantic import Field

from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import _require_valid_key, _resolve_namespace_id_from_env
from project_workflow.interfaces.ui.routes.runtime_api import _history_rows, execute_namespace_step
from project_workflow.interfaces.ui.schemas import RuntimeStepRequest


class CliStepRequest(RuntimeStepRequest):
    namespace_id: int | None = Field(default=None, gt=0)


def _cli_namespace_id(uow: SAUnitOfWork, task: str, requested: int | None) -> int:
    namespace_id = requested if requested is not None else _resolve_namespace_id_from_env(uow)
    if namespace_id is not None:
        if uow.projects.get_by_id(namespace_id) is None:
            raise ValueError(f"Неймспейс {namespace_id} не найден")
        return namespace_id
    task_key = _require_valid_key(task, uow)
    existing = uow.tasks.get_by_key(task_key)
    if existing is not None:
        return existing.project_id
    namespaces = uow.projects.list()
    if len(namespaces) == 1 and namespaces[0].id is not None:
        return namespaces[0].id
    raise ValueError("Укажите PROJECT_WORKFLOW_NAMESPACE_ID для выбора неймспейса")


def cli_step(payload: CliStepRequest) -> dict | JSONResponse:
    try:
        with SAUnitOfWork() as uow:
            namespace_id = _cli_namespace_id(uow, payload.task, payload.namespace_id)
            return execute_namespace_step(uow, namespace_id=namespace_id, task=payload.task, report=payload.report)
    except (ConflictError, RuntimeError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)


def cli_history(
    task: str = Query(...),
    n: int | None = Query(default=None, ge=1),
    namespace_id: int | None = Query(default=None, gt=0),
) -> dict | JSONResponse:
    try:
        with SAUnitOfWork() as uow:
            namespace_id = _cli_namespace_id(uow, task, namespace_id)
            task_key = _require_valid_key(task, uow, project_id=namespace_id)
            rows = _history_rows(uow, task_key, namespace_id, n)
            return {"ok": True, "exit_code": 0, "result": {"task_key": task_key, "count": len(rows), "records": rows}}
    except (ConflictError, RuntimeError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)
