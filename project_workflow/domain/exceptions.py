"""Domain exceptions."""

from __future__ import annotations


class WorkflowCliError(Exception):
    """Base domain error."""


class NotFoundError(WorkflowCliError):
    """Entity not found."""


class ConflictError(WorkflowCliError):
    """Unique constraint or business conflict."""


class ConcurrentTransitionError(ConflictError):
    """Task state changed while a Supervisor transition was being committed."""


class LastPhaseError(WorkflowCliError):
    """Attempt to delete the last phase of a workflow."""
