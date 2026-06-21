"""Domain exceptions."""
from __future__ import annotations


class WorkflowCliError(Exception):
    """Base domain error."""


class NotFoundError(WorkflowCliError):
    """Entity not found."""


class ValidationError(WorkflowCliError):
    """Domain validation failed."""


class ConflictError(WorkflowCliError):
    """Unique constraint or business conflict."""


class LastPhaseError(WorkflowCliError):
    """Attempt to delete the last phase of a workflow."""
