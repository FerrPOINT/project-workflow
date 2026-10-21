"""PM bootstrap endpoints using the existing PM assignment credential."""

from fastapi import Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from project_workflow.application.pm_bootstrap import BootstrapRetry, PMBootstrapService
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db.single_task_catalog import runtime_catalog_read
from project_workflow.infrastructure.db.uow import SAUnitOfWork

from . import runtime_api


def predecessor(
    task: str = Query(min_length=1, max_length=128),
    assignment_operation_key: str = Query(min_length=1, max_length=128),
    assignment_revision: int = Query(gt=0),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    def response(value: dict, status: int) -> JSONResponse:
        return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})

    try:
        credential = runtime_api._authorized_service_credential(authorization, single_task=True)
        if credential is None:
            return response({"ok": False, "error": "Invalid machine credential"}, 401)
        if credential.kind != "assignment" or credential.role_key != "project_manager":
            return response({"ok": False, "error": "PM assignment credential required"}, 403)
        with SAUnitOfWork() as uow, runtime_catalog_read(uow):
            project_id = runtime_api._namespace_id(uow, "project_manager", single_task=True)
            key = runtime_api._require_valid_key(task, uow, project_id=project_id)
            result = PMBootstrapService(uow).predecessor(
                project_id, key, assignment_operation_key, assignment_revision,
            )
        return response({"ok": True, "result": result}, 200)
    except NotFoundError:
        return response({"ok": False, "error": "Predecessor not found"}, 404)
    except (ConflictError, ValueError):
        return response({"ok": False, "error": "Stale or foreign predecessor"}, 409)
    except (RuntimeError, SQLAlchemyError):
        # A timeout/unavailable DB is never an authoritative negative observation.
        return response({"ok": False, "error": "Predecessor state unknown"}, 503)


def retry(payload: BootstrapRetry, authorization: str | None = Header(default=None)) -> JSONResponse:
    def response(value: dict, status: int) -> JSONResponse:
        return JSONResponse(value, status_code=status, headers={"Cache-Control": "no-store"})

    try:
        credential = runtime_api._authorized_service_credential(authorization, single_task=True)
        if credential is None:
            return response({"ok": False, "error": "Invalid machine credential"}, 401)
        if credential.kind != "assignment" or credential.role_key != "project_manager":
            return response({"ok": False, "error": "PM assignment credential required"}, 403)
        with SAUnitOfWork() as uow, runtime_catalog_read(uow):
            project_id = runtime_api._namespace_id(
                uow, "project_manager", single_task=True, assignment_operation_key=payload.predecessor_operation_key,
            )
            previous = uow.tasks.get_assignment_by_operation_key(payload.predecessor_operation_key)
            task = uow.tasks.get_by_id(previous.task_id) if previous is not None else None
            if task is None or task.project_id != project_id:
                raise NotFoundError("Bootstrap task missing")
            result = PMBootstrapService(uow).retry(project_id, task.task_key, payload, pm_readback.bootstrap_proof)
        return response({"ok": True, "result": result}, 200)
    except NotFoundError:
        return response({"ok": False, "error": "Predecessor not found"}, 404)
    except (ConflictError, ValueError):
        return response({"ok": False, "error": "Stale or foreign bootstrap request"}, 409)
    except (RuntimeError, SQLAlchemyError):
        return response({"ok": False, "error": "Bootstrap authority or outcome unknown; read back original key"}, 503)
