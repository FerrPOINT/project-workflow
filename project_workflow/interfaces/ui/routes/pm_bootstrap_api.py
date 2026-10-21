"""Unregistered PM predecessor reader; app route registration is integrator-owned."""

from fastapi import Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from project_workflow.application.pm_bootstrap import PMBootstrapService
from project_workflow.domain.exceptions import ConflictError, NotFoundError
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
        with SAUnitOfWork() as uow:
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
