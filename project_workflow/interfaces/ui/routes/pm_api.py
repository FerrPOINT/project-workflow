"""PM v1 machine endpoints on the existing role/namespace runtime bridge."""

import hmac
from typing import Any

from fastapi import Header
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from project_workflow import config
from project_workflow.application.namespace_ownership import NamespaceOwnershipService
from project_workflow.application.pm_execution import PMExecutionService
from project_workflow.application.task import TaskService
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.pm_execution import (
    PMBind,
    PMCheckpoint,
    PMCommand,
    PMDraftAssignment,
    PMReadback,
    PMRebind,
    PMResume,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.pm_readback import ReadbackUnavailable, readback_configured

from . import runtime_api


def configured() -> bool:
    settings = config.get_settings()
    runtime, assignment, catalog = runtime_api._token_configuration()
    shared_secrets = {*runtime.values(), *assignment.values(), catalog, settings.PROJECT_WORKFLOW_PM_READBACK_TOKEN}
    return (
        readback_configured() and len(settings.PROJECT_WORKFLOW_PM_SCOPE_SECRET) >= 32
        and settings.PROJECT_WORKFLOW_PM_SCOPE_SECRET not in shared_secrets
    )


def error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error_code": code, "error": message}, status_code=status)


def scope_matches(
    identity: dict[str, Any], run_ref: str, binding_ref: str, fence: int,
    session_run_id: str, token: str | None,
) -> bool:
    secret = config.get_settings().PROJECT_WORKFLOW_PM_SCOPE_SECRET
    if len(secret) < 32 or not isinstance(token, str):
        return False
    expected = PMExecutionService.scoped_token({
        "identity": identity, "hermes_run_ref": run_ref, "binding_ref": binding_ref, "fence": fence,
        "session_run_id": session_run_id,
    }, secret)
    return hmac.compare_digest(token.encode(), expected.encode())


def _execute(
    payload: PMBind | PMCommand | PMReadback, kind: str,
    authorization: str | None, scope_token: str | None = None,
) -> dict[str, Any] | JSONResponse:
    try:
        credential = runtime_api._authorized_service_credential(authorization)
        if credential is None:
            return error("unauthorized", "Invalid machine credential", 401)
        if credential.role_key != "project_manager" or credential.kind == "catalog":
            return error("forbidden", "PM machine role required", 403)
        if kind == "checkpoint" and credential.kind != "runtime":
            return error("forbidden", "Checkpoint requires scoped runtime identity", 403)
        if kind in {"bind", "resume", "rebind"} and credential.kind != "assignment":
            return error("forbidden", "Adapter assignment credential required", 403)
        if kind != "readback" and not configured():
            return error("capability-unavailable", "PM runtime readback/scope configuration unavailable", 503)
        identity = PMExecutionService.identity(payload)
        if isinstance(payload, PMCommand) and kind == "checkpoint":
            if not scope_matches(
                identity.model_dump(), payload.hermes_run_ref, payload.binding_ref,
                payload.expected_fence, payload.session_run_id, scope_token,
            ):
                return error("forbidden", "Execution/run scoped credential required", 403)
        with SAUnitOfWork() as uow:
            project_id = runtime_api._namespace_id(uow, credential.role_key)
            service = PMExecutionService(uow)
            if isinstance(payload, PMReadback):
                result = service.readback(identity, project_id, payload.operation_key)
                if credential.kind == "runtime" and not scope_matches(
                    result["identity"], result["hermes_run_ref"], result["binding_ref"], result["fence"],
                    result["session_run_id"], scope_token,
                ):
                    return error("forbidden", "Current execution/run scoped credential required", 403)
            elif isinstance(payload, PMBind):
                result = service.bind(payload, project_id)
            elif isinstance(payload, PMRebind):
                result = service.rebind(payload, project_id)
            elif isinstance(payload, PMResume):
                result = service.resume(payload, project_id)
            elif isinstance(payload, PMCheckpoint):
                result = service.checkpoint(payload, project_id)
            else:
                raise ValueError("Unsupported PM command")
        response: dict[str, Any] = {"ok": True, "result": result}
        if credential.kind == "assignment" and result["state"] == "active" and configured():
            response["execution_token"] = service.scoped_token(
                result, config.get_settings().PROJECT_WORKFLOW_PM_SCOPE_SECRET,
            )
        return response
    except NotFoundError as exc:
        return error("not-found", str(exc), 404)
    except (ConflictError, IntegrityError):
        return error("conflict", "Stale identity/version/fence or idempotency payload conflict", 409)
    except ReadbackUnavailable as exc:
        return error("runtime-acceptance-unknown", str(exc), 503)
    except RuntimeError:
        return error("dependency-unavailable", "PM namespace or credential configuration unavailable", 503)
    except ValueError as exc:
        return error("validation-error", str(exc), 422)


def bind(payload: PMBind, authorization: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    return _execute(payload, "bind", authorization)


def assign(
    payload: PMDraftAssignment, authorization: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """The trusted Fleet adapter projects an initial Tracker Draft reservation."""
    try:
        credential = runtime_api._authorized_service_credential(authorization)
        if credential is None:
            return error("unauthorized", "Invalid machine credential", 401)
        if credential.role_key != "project_manager" or credential.kind != "assignment":
            return error("forbidden", "PM adapter assignment credential required", 403)
        if payload.runtime_compatibility != runtime_api.runtime_compatibility_descriptor():
            return error("conflict", "Runtime compatibility mismatch", 409)
        with SAUnitOfWork() as uow:
            project_id = runtime_api._namespace_id(uow, credential.role_key)
            ownership = NamespaceOwnershipService(uow)
            ownership.lock_namespace(project_id)
            owner = ownership.get(project_id)
            if (
                owner.tracker_instance_ref != payload.tracker_instance_ref
                or owner.tracker_project_ref != payload.tracker_project_ref
            ):
                raise ConflictError("PM Draft reservation belongs to another namespace owner")
            runtime_api._assert_task_key_in_namespace(uow, project_id, payload.task)
            return runtime_api._assignment_response(TaskService(uow).assign_pm_draft(project_id, payload))
    except (ConflictError, IntegrityError, ValueError):
        return error("conflict", "PM Draft reservation or original command conflict", 409)
    except NotFoundError:
        return error("capability-unavailable", "PM namespace owner is not provisioned", 503)
    except RuntimeError:
        return error("capability-unavailable", "PM namespace or credential configuration unavailable", 503)


def checkpoint(
    payload: PMCheckpoint, authorization: str | None = Header(default=None),
    x_workflow_execution_token: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    return _execute(payload, "checkpoint", authorization, x_workflow_execution_token)


def resume(payload: PMResume, authorization: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    return _execute(payload, "resume", authorization)


def rebind(payload: PMRebind, authorization: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    return _execute(payload, "rebind", authorization)


def readback(
    payload: PMReadback, authorization: str | None = Header(default=None),
    x_workflow_execution_token: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    return _execute(payload, "readback", authorization, x_workflow_execution_token)
