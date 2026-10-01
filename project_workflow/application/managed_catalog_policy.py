"""Application policy for the versioned managed workflow catalog."""

from __future__ import annotations

from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.runtime_assignment import MANAGED_WORKFLOW_KEYS

MANAGED_CATALOG_IMMUTABLE_ERROR = (
    "Managed workflow catalog is immutable; change the versioned catalog and reconcile it"
)


def assert_catalog_mutation_allowed(uow: UnitOfWork) -> None:
    """Fence bootstrap and reject public mutations after managed install.

    The transaction lock is shared with managed bootstrap.  Consequently a
    mutation either completes while the database is still wholly unmanaged, or
    observes the installed marker and fails before its first write.
    Independent unmanaged writers retain their entity-level concurrency.
    """

    uow.lock_catalog_state(shared=True)
    if any(
        getattr(workflow, "key", None) in MANAGED_WORKFLOW_KEYS
        for workflow in uow.workflows.list()
    ):
        uow.rollback()
        raise ConflictError(MANAGED_CATALOG_IMMUTABLE_ERROR)


__all__ = ["MANAGED_CATALOG_IMMUTABLE_ERROR", "assert_catalog_mutation_allowed"]
