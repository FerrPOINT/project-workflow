"""Explicit Base source and durable receipt surfaces on existing machine scopes."""

from typing import Any

from fastapi import Header
from fastapi.responses import JSONResponse
from sqlalchemy import select

from project_workflow.application.base_source import export_base_source, source_capability
from project_workflow.application.base_terminal import read_terminal_receipt
from project_workflow.domain.base_admission import BaseTerminalReadback
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.infrastructure.base_auth import authorize_read
from project_workflow.infrastructure.db.models import PMExecution
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.namespace_auth import NamespaceAuthError

from . import pm_api, runtime_api


def source_catalog(authorization: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    return _source(authorization, catalog=True)


def source_capabilities(authorization: str | None = Header(default=None)) -> dict[str, Any] | JSONResponse:
    return _source(authorization, catalog=False)


def _source(authorization: str | None, *, catalog: bool) -> dict[str, Any] | JSONResponse:
    try:
        credential = authorize_read(authorization)
        if catalog and credential.kind != "catalog":
            return runtime_api._error("Registered catalog reader required", 403)
        source = export_base_source()
        return {"ok": True, "catalog": source} if catalog else {
            "ok": True, "capability": source_capability(
                source, role_key=credential.role_key, credential_kind=credential.kind,
            ),
        }
    except NamespaceAuthError as exc:
        return runtime_api._error(str(exc), exc.status)
    except (RuntimeError, ValueError, KeyError, TypeError, OSError):
        return runtime_api._error("Pinned Base source export unavailable", 503)


def terminal_readback(
    payload: BaseTerminalReadback,
    authorization: str | None = Header(default=None),
    x_workflow_execution_token: str | None = Header(default=None),
) -> dict[str, Any] | JSONResponse:
    """Reconcile an exact owner operation; no writes or synthetic terminal ACK."""
    try:
        credential = authorize_read(authorization)
        if credential.kind == "catalog":
            return runtime_api._error("Registered role reader required", 403)
        with SAUnitOfWork() as uow:
            namespace_id = runtime_api._namespace_id(uow, credential.role_key)
            runtime_api._assert_task_key_in_namespace(uow, namespace_id, payload.task)
            task = uow.tasks.get_by_key(payload.task, project_id=namespace_id)
            history = uow.step_history.get_by_step_operation_key(payload.step_operation_key)
            if (
                task is None or history is None or task.id != history.task_id
                or history.role_key != credential.role_key
            ):
                raise NotFoundError("Accepted terminal step not found")
            if credential.role_key == "project_manager":
                from project_workflow.application.pm_execution import PMExecutionService

                execution = uow.session.scalar(select(PMExecution).where(PMExecution.task_id == task.id))
                if execution is not None:
                    snapshot = PMExecutionService(uow).snapshot(execution)
                    if payload.session_run_id != snapshot["session_run_id"]:
                        return runtime_api._error("Current Fleet session_run_id required", 409)
                    if not pm_api.scope_matches(
                        snapshot["identity"], snapshot["hermes_run_ref"], snapshot["binding_ref"],
                        snapshot["fence"], snapshot["session_run_id"], x_workflow_execution_token,
                    ):
                        return runtime_api._error("Current PM execution/run credential required", 403)
            expected = {
                "assignment_revision": payload.assignment_revision, "assignment_ref": payload.assignment_ref,
                "binding_ref": payload.binding_ref, "hermes_run_ref": payload.hermes_run_ref,
                "mode_key": payload.mode_key, "cycle_number": payload.cycle_number,
                "attempt_number": payload.attempt_number,
            }
            if any(history.to_dict().get(key) != value for key, value in expected.items()):
                raise ConflictError("Terminal receipt lookup fence mismatch")
            receipt = read_terminal_receipt(uow, payload.step_operation_key)
            admission = receipt["base_admission"]
            if (
                admission["config_ref"] != payload.base_config_ref
                or admission["config_sha256"] != payload.base_config_sha256
                or payload.receipt_sha256 is not None and receipt["receipt_sha256"] != payload.receipt_sha256
            ):
                raise ConflictError("Terminal receipt lookup config/hash mismatch")
            return {"ok": True, "complete": True, "receipt": receipt}
    except NamespaceAuthError as exc:
        return runtime_api._error(str(exc), exc.status)
    except NotFoundError:
        return runtime_api._error("Accepted terminal step not found", 404)
    except (ConflictError, ValueError):
        return runtime_api._error("Terminal receipt missing, stale or invalid", 409)
    except RuntimeError:
        return runtime_api._error("Terminal receipt dependency unavailable", 503)
