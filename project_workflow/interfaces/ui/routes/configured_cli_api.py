"""Configured CLI branches of the existing private runtime endpoints."""

from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from project_workflow.application import configured_cli
from project_workflow.domain.configured_cli import ConfiguredAssignment, ConfiguredStep, ConfiguredTerminalReadback
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.infrastructure.db.single_task_catalog import runtime_catalog_read
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.namespace_auth import NamespaceAuthError


def error(exc: Exception) -> JSONResponse:
    if isinstance(exc, NamespaceAuthError):
        status = exc.status
    elif isinstance(exc, NotFoundError):
        status = 404
    elif isinstance(exc, (ConflictError, ValueError, IntegrityError)):
        status = 409
    else:
        status = 503
    return JSONResponse({"ok": False, "exit_code": 1, "error_code": f"configured-cli-{status}",
                         "error": "Configured CLI request refused; retain the exact operation for readback"},
                        status_code=status, headers={"Cache-Control": "no-store"})


def assign(command: ConfiguredAssignment, authorization: str | None):
    from .runtime_api import _authorized_assignment_role

    try:
        if _authorized_assignment_role(authorization, single_task=True) != "project_manager":
            raise NamespaceAuthError(403)
        with SAUnitOfWork() as uow, runtime_catalog_read(uow):
            return {"ok": True, "exit_code": 0, "result": configured_cli.enroll(uow, command)}
    except (NamespaceAuthError, NotFoundError, ConflictError, ValueError, RuntimeError, SQLAlchemyError) as exc:
        return error(exc)


def step(command: ConfiguredStep, authorization: str | None):
    try:
        with SAUnitOfWork() as uow, runtime_catalog_read(uow):
            return configured_cli.step(uow, command, authorization)
    except (NamespaceAuthError, NotFoundError, ConflictError, ValueError, RuntimeError, SQLAlchemyError) as exc:
        return error(exc)


def history(task: str, namespace_id: int | None, authorization: str | None, *, n: int,
            execution_ref: str | None, operation_key: str | None):
    from .runtime_api import _authorized_assignment_role

    try:
        if type(namespace_id) is not int or namespace_id <= 0:
            raise ValueError("Explicit namespace required")
        trusted = _authorized_assignment_role(authorization, single_task=True) == "project_manager"
        with SAUnitOfWork() as uow, runtime_catalog_read(uow):
            return configured_cli.history(uow, task, namespace_id, authorization, n=n,
                execution_ref=execution_ref, operation_key=operation_key, trusted=trusted)
    except (NamespaceAuthError, NotFoundError, ConflictError, ValueError, RuntimeError, SQLAlchemyError) as exc:
        return error(exc)


def terminal_readback(command: ConfiguredTerminalReadback, authorization: str | None):
    from .runtime_api import _authorized_assignment_role

    try:
        if _authorized_assignment_role(authorization, single_task=True) != "project_manager":
            raise NamespaceAuthError(403)
        with SAUnitOfWork() as uow, runtime_catalog_read(uow):
            return JSONResponse(configured_cli.terminal_readback(uow, command),
                                headers={"Cache-Control": "no-store"})
    except (NamespaceAuthError, NotFoundError, ConflictError, ValueError, RuntimeError, SQLAlchemyError) as exc:
        return error(exc)
