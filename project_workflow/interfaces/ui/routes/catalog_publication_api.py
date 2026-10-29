"""Administrator-only JSON catalog editing/publication, without UI coupling."""

from typing import Annotated

from fastapi import HTTPException, Path, Request
from fastapi.responses import JSONResponse

from project_workflow.application import catalog_publication
from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.infrastructure.db.uow import SAUnitOfWork

PositiveId = Annotated[int, Path(gt=0)]


def _call(function, *args, **kwargs) -> JSONResponse:
    try:
        with SAUnitOfWork() as uow:
            result = function(uow, *args, **kwargs)
        return JSONResponse({"ok": True, "revision": result}, headers={"Cache-Control": "no-store"})
    except NotFoundError as exc:
        status, message = 404, str(exc)
    except (ConflictError, ValueError) as exc:
        status, message = 409, str(exc)
    return JSONResponse({"ok": False, "error": message}, status_code=status, headers={"Cache-Control": "no-store"})


def active(workflow_id: PositiveId) -> JSONResponse:
    return _call(catalog_publication.read_active, workflow_id)


def operation(
    workflow_id: PositiveId, operation_key: Annotated[str, Path(min_length=1, max_length=128)],
) -> JSONResponse:
    return _call(catalog_publication.read_operation, workflow_id, operation_key)


def save(workflow_id: PositiveId, payload: CatalogDraft) -> JSONResponse:
    return _call(catalog_publication.save_draft, workflow_id, payload)


def draft(workflow_id: PositiveId, version: PositiveId) -> JSONResponse:
    return _call(catalog_publication.read_draft, workflow_id, version)


def pending(workflow_id: PositiveId) -> JSONResponse:
    return _call(catalog_publication.read_pending_draft, workflow_id)


def publish(workflow_id: PositiveId, version: PositiveId, payload: CatalogPublish, request: Request) -> JSONResponse:
    subject = getattr(request.state, "central_subject", None)
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(401, "Verified central human identity required")
    return _call(catalog_publication.publish, workflow_id, version, payload, publisher_subject=subject)
