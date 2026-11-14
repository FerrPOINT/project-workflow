"""The existing step/history surface for a Fleet-owned background run."""
from fastapi import Header, Query

from project_workflow.application import background
from project_workflow.domain.background import BackgroundStep
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.namespace_ownership import canonical_uuid
from project_workflow.infrastructure import background_admission, base_auth, namespace_auth
from project_workflow.infrastructure.db.uow import SAUnitOfWork

from .configured_cli_api import _REQUEST_ERRORS, error


def archived_history(run_id: str, authorization: str | None = Header(default=None),
                     n: int = Query(default=50, ge=1, le=200),
                     before_history_id: int | None = Query(default=None, gt=0)):
    try:
        run_id = canonical_uuid(run_id)
        principal, scopes = namespace_auth.introspect(authorization, require_service_account=True)
        if (scopes != ["project-workflow:background:history:read"]
                or base_auth.registered_subjects().get(principal.subject) != "catalog"):
            raise namespace_auth.NamespaceAuthError(403)
        with SAUnitOfWork() as uow:
            return background.archived_history(uow, run_id, n=n, before_history_id=before_history_id)
    except _REQUEST_ERRORS as exc:
        return error(exc)


def step(command: BackgroundStep, authorization: str | None):
    try:
        admission = background_admission.read(command.run_id, authorization, write=True,
                                               namespace_id=command.namespace_id)

        def check() -> None:
            current = background_admission.read(command.run_id, authorization, write=True,
                                                 namespace_id=command.namespace_id)
            if current.identity() != admission.identity():
                raise ConflictError("Fleet background launch changed")

        with SAUnitOfWork() as uow:
            return background.step(uow, command, admission, check)
    except _REQUEST_ERRORS as exc:
        return error(exc)


def history(run_id: str, namespace_id: int, authorization: str | None, *, n: int,
            operation_key: str | None, before_history_id: int | None):
    try:
        admission = background_admission.read(run_id, authorization, write=False,
                                               namespace_id=namespace_id, active=False)
        with SAUnitOfWork() as uow:
            return background.history(uow, admission, n=n, operation_key=operation_key,
                                       before_history_id=before_history_id)
    except _REQUEST_ERRORS as exc:
        return error(exc)
