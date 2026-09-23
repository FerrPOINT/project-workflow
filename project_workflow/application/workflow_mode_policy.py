"""Application guard for workflow-mode mutations."""

from __future__ import annotations

from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.workflow_mode_policy import WorkflowModePolicy, require_dispatchable_workflow_mode


def require_workflow_mode_mutable_after_lock(
    uow: UnitOfWork,
    *,
    workflow_id: int,
    mode_id: int | None,
) -> WorkflowModePolicy:
    """Reject a write unless its mode is dispatchable.

    Callers must lock the owning workflow before invoking this helper so policy
    evaluation and the following mutation share the same workflow transaction.
    """
    if mode_id is None:
        raise ConflictError("Для фазы не найден владеющий режим воркфлоу")
    mode = uow.workflows.get_mode(mode_id, workflow_id)
    if mode is None:
        raise ConflictError("mode_id не принадлежит указанному воркфлоу")
    return require_dispatchable_workflow_mode(mode)


__all__ = ["require_workflow_mode_mutable_after_lock"]
