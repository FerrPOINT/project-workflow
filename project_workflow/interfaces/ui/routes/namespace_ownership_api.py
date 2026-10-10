"""Machine-only ownership provisioning; never runtime admission."""

from typing import Annotated

from fastapi import Header, Path
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from project_workflow.application.namespace_ownership import NamespaceOwnershipService
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest, NamespaceOwnershipResponse
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.namespace_auth import NamespaceAuthError, authorize


def _execute(namespace_id: int, authorization: str | None, payload: NamespaceOwnershipRequest | None) -> JSONResponse:
    try:
        principal = authorize(authorization, namespace_id, provision=payload is not None)
        with SAUnitOfWork() as uow:
            service = NamespaceOwnershipService(uow)
            result, created = service.provision(namespace_id, payload, principal) if payload is not None else (
                service.get(namespace_id), False,
            )
            if result.authority_issuer != principal.issuer or result.provisioner_subject != principal.subject:
                raise NamespaceAuthError(403)
        body = NamespaceOwnershipResponse(ok=True, result=result)
        return JSONResponse(body.model_dump(mode="json"), status_code=201 if created else 200,
                            headers={"Cache-Control": "no-store"})
    except NamespaceAuthError as exc:
        status, code = exc.status, "authorization-unavailable" if exc.status == 503 else "machine-access-denied"
    except NotFoundError:
        status, code = 404, "ownership-not-found"
    except (ConflictError, IntegrityError):
        status, code = 409, "ownership-conflict"
    except ValidationError:
        status, code = 503, "ownership-unavailable"
    return JSONResponse({"ok": False, "error_code": code, "error": "PM namespace ownership request rejected"},
                        status_code=status, headers={"Cache-Control": "no-store"})


def provision(
    namespace_id: Annotated[int, Path(gt=0)], payload: NamespaceOwnershipRequest,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    return _execute(namespace_id, authorization, payload)


def readback(
    namespace_id: Annotated[int, Path(gt=0)], authorization: str | None = Header(default=None),
) -> JSONResponse:
    return _execute(namespace_id, authorization, None)
