"""Compatibility shim: task_validator moved to project_workflow.domain.validation."""
from __future__ import annotations

from project_workflow.domain.validation import *
from project_workflow.domain.validation import (
    TaskKeyValidator,
    ValidatedTaskKey,
    ValidationResult,
    validate,
    validate_or_die,
)

__all__ = [
    "TaskKeyValidator",
    "TaskKeyValidationError",
    "ValidatedTaskKey",
    "ValidationResult",
    "validate",
    "validate_or_die",
]
