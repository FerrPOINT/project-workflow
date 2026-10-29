"""Read-only Base source and namespace observations on registered machine scopes."""

from typing import Any, Literal

from fastapi import Header
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from project_workflow.application.base_binding import observe_base_namespace_binding
from project_workflow.application.base_source import export_base_source, source_capability
from project_workflow.domain.base_binding import BaseNamespaceBindingError, BaseNamespaceBindingResponse, DatabaseId
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.base_auth import authorize_read
from project_workflow.infrastructure.db.session import DatabaseUnavailable
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.namespace_auth import NamespaceAuthError

from . import runtime_api


def _binding_error(code: str, message: str, status: int) -> JSONResponse:
    error = BaseNamespaceBindingError.model_validate({"ok": False, "error_code": code, "error": message})
    return JSONResponse(error.model_dump(), status_code=status, headers={"Cache-Control": "no-store"})


def namespace_binding(
    namespace_id: DatabaseId,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Fresh registered catalog authority, then a non-mutating owner DB observation."""
    try:
        credential = authorize_read(authorization)
        if credential.kind != "catalog":
            return _binding_error("machine-access-denied", "Registered catalog reader required", 403)
    except NamespaceAuthError as exc:
        code = "authorization-unavailable" if exc.status == 503 else "machine-access-denied"
        return _binding_error(code, "Base catalog reader authorization failed", exc.status)
    try:
        uow = SAUnitOfWork()
        try:
            binding = observe_base_namespace_binding(uow, int(namespace_id))
            result = BaseNamespaceBindingResponse(ok=True, binding=binding)
            return JSONResponse(result.model_dump(by_alias=True), headers={"Cache-Control": "no-store"})
        finally:
            try:
                uow.rollback()
            finally:
                uow.close()
    except ConflictError:
        return _binding_error(
            "binding-conflict", "Installed Base namespace/candidate missing, stale or mismatched", 409,
        )
    except (DatabaseUnavailable, SQLAlchemyError, RuntimeError, ValueError, KeyError, TypeError, OSError):
        return _binding_error("binding-unavailable", "Pinned Base namespace observation unavailable", 503)


def source_catalog(
    authorization: str | None = Header(default=None), catalog_version: Literal[3, 4] | None = None,
) -> dict[str, Any] | JSONResponse:
    return _source(authorization, catalog=True, catalog_version=catalog_version)


def source_capabilities(
    authorization: str | None = Header(default=None), catalog_version: Literal[3, 4] | None = None,
) -> dict[str, Any] | JSONResponse:
    return _source(authorization, catalog=False, catalog_version=catalog_version)


def _source(
    authorization: str | None, *, catalog: bool, catalog_version: int | None = None,
) -> dict[str, Any] | JSONResponse:
    try:
        credential = authorize_read(authorization)
        if catalog and credential.kind != "catalog":
            return runtime_api._error("Registered catalog reader required", 403)
        source = export_base_source(catalog_version)
        return {"ok": True, "catalog": source} if catalog else {
            "ok": True, "capability": source_capability(
                source, role_key=credential.role_key, credential_kind=credential.kind,
            ),
        }
    except NamespaceAuthError as exc:
        return runtime_api._error(str(exc), exc.status)
    except (RuntimeError, ValueError, KeyError, TypeError, OSError):
        return runtime_api._error("Pinned Base source export unavailable", 503)
