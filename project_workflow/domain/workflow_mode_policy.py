"""Backend-owned workflow-mode policy state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .exceptions import ConflictError
from .runtime_assignment import normalize_role_key


class WorkflowModePolicyStatus(str, Enum):
    """Stable policy states shared by application validation and presentation."""

    LEGACY = "legacy"
    INCOMPLETE = "incomplete"
    INCONSISTENT = "inconsistent"
    DISPATCHABLE = "dispatchable"


@dataclass(frozen=True)
class WorkflowModePolicy:
    """Normalized policy evaluation for one persisted workflow mode."""

    status: WorkflowModePolicyStatus
    key: str
    role_key: str | None
    execution_scope: str | None
    tech_workspace_policy: str | None

    @property
    def is_dispatchable(self) -> bool:
        return self.status is WorkflowModePolicyStatus.DISPATCHABLE

    @property
    def is_read_only(self) -> bool:
        return not self.is_dispatchable


def _value(mode: Any, field: str) -> Any:
    if isinstance(mode, Mapping):
        return mode.get(field)
    return getattr(mode, field, None)


def evaluate_workflow_mode_policy(mode: Any) -> WorkflowModePolicy:
    """Classify one mode without trusting UI-derived flags."""
    raw_key = _value(mode, "key")
    key = raw_key if isinstance(raw_key, str) else ""
    raw_role_key = _value(mode, "role_key")
    execution_scope = _value(mode, "execution_scope")
    tech_workspace_policy = _value(mode, "tech_workspace_policy")

    role_key: str | None = None
    try:
        role_key = normalize_role_key(raw_role_key)
    except ValueError:
        pass

    if key == "default":
        status = WorkflowModePolicyStatus.LEGACY
    elif (
        role_key is None
        or execution_scope not in {"business", "delivery", "aggregate"}
        or tech_workspace_policy not in {"forbidden", "required"}
    ):
        status = WorkflowModePolicyStatus.INCOMPLETE
    elif not (
        (execution_scope == "business" and tech_workspace_policy == "forbidden")
        or (
            execution_scope in {"delivery", "aggregate"}
            and tech_workspace_policy == "required"
        )
    ):
        status = WorkflowModePolicyStatus.INCONSISTENT
    else:
        status = WorkflowModePolicyStatus.DISPATCHABLE

    return WorkflowModePolicy(
        status=status,
        key=key,
        role_key=role_key,
        execution_scope=execution_scope if isinstance(execution_scope, str) else None,
        tech_workspace_policy=(
            tech_workspace_policy if isinstance(tech_workspace_policy, str) else None
        ),
    )


def require_dispatchable_workflow_mode(mode: Any) -> WorkflowModePolicy:
    """Return normalized policy or raise the stable conflict used by mutation APIs."""
    policy = evaluate_workflow_mode_policy(mode)
    if policy.status is WorkflowModePolicyStatus.LEGACY:
        raise ConflictError(
            "Режим 'default' предназначен только для совместимости и доступен только для чтения"
        )
    if policy.status is WorkflowModePolicyStatus.INCOMPLETE:
        raise ConflictError(
            f"Режим {policy.key!r} доступен только для чтения: серверная политика неполна"
        )
    if policy.status is WorkflowModePolicyStatus.INCONSISTENT:
        raise ConflictError(
            f"Режим {policy.key!r} доступен только для чтения: серверная политика противоречива"
        )
    return policy


__all__ = [
    "WorkflowModePolicy",
    "WorkflowModePolicyStatus",
    "evaluate_workflow_mode_policy",
    "require_dispatchable_workflow_mode",
]
