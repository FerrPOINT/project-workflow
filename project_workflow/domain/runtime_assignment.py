"""Shared invariants for backend-owned runtime assignments."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

ROLE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
CANONICAL_UNDERSCORE_ROLE_KEYS = frozenset({"project_manager"})
MAX_WORK_ITEM_REVISION = (1 << 63) - 1
MANAGED_ROLE_MODE_SCOPES: dict[str, dict[str, str]] = {
    "project_manager": {"draft": "business"},
    "analyst": {"analysis": "business"},
    "architect": {"decomposition": "business"},
    "developer": {
        "initial": "delivery",
        "rework": "delivery",
        "integration": "aggregate",
        "integration_rework": "aggregate",
    },
    "reviewer": {"delivery": "delivery", "integration": "aggregate"},
    "tester": {"delivery": "delivery", "integration": "aggregate"},
    "devops": {"delivery": "delivery", "integration": "aggregate"},
}
MANAGED_WORKFLOW_KEYS = frozenset(
    f"hermes-sdlc:{role_key}" for role_key in MANAGED_ROLE_MODE_SCOPES
)


@dataclass(frozen=True)
class RuntimeStepFence:
    """Exact owner-issued assignment/run snapshot allowed to mutate one task."""

    step_operation_key: str
    request_sha256: str
    assignment_revision: int
    assignment_operation_key: str
    assignment_ref: str
    binding_ref: str
    hermes_run_ref: str
    mode_id: int
    mode_key: str
    cycle_number: int
    attempt_number: int
    role_key: str
    expected_phase_id: int
    expected_phase_code: str
    expected_status: str

    def assert_task(self, task: dict[str, Any] | None) -> None:
        """Reject a stale task projection before Supervisor can use or mutate it."""
        if task is None:
            raise ValueError("Runtime assignment задачи больше не существует")
        expected = {
            "assignment_revision": self.assignment_revision,
            "assignment_operation_key": self.assignment_operation_key,
            "mode_id": self.mode_id,
            "mode_key": self.mode_key,
            "cycle_number": self.cycle_number,
            "current_phase_id": self.expected_phase_id,
            "current_phase_code": self.expected_phase_code,
            "status": self.expected_status,
        }
        mismatched = [name for name, value in expected.items() if task.get(name) != value]
        if mismatched:
            raise ValueError(
                "Runtime step относится к устаревшему assignment/run: " + ", ".join(mismatched)
            )

    def assert_history(self, history: dict[str, Any]) -> None:
        """Reject an operation-key collision with another request or assignment."""
        expected = {
            "step_operation_key": self.step_operation_key,
            "request_sha256": self.request_sha256,
            "assignment_revision": self.assignment_revision,
            "assignment_operation_key": self.assignment_operation_key,
            "assignment_ref": self.assignment_ref,
            "binding_ref": self.binding_ref,
            "hermes_run_ref": self.hermes_run_ref,
            "mode_id": self.mode_id,
            "mode_key": self.mode_key,
            "cycle_number": self.cycle_number,
            "attempt_number": self.attempt_number,
            "role_key": self.role_key,
        }
        mismatched = [name for name, value in expected.items() if history.get(name) != value]
        if mismatched:
            raise ValueError(
                "step_operation_key уже использован для другого runtime step"
            )


def normalize_role_key(value: Any) -> str:
    """Return one runtime-safe role key or reject it consistently."""
    if not isinstance(value, str):
        raise ValueError("role_key должен быть строкой")
    normalized = value.strip()
    if ROLE_KEY_PATTERN.fullmatch(normalized) is None and normalized not in CANONICAL_UNDERSCORE_ROLE_KEYS:
        raise ValueError(
            "role_key должен соответствовать [a-z][a-z0-9-]{1,31} "
            "или быть каноническим project_manager"
        )
    return normalized


def canonical_json(value: Any) -> str:
    """Serialize replay-significant data with one stable byte representation."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_sha256(value: Any) -> str:
    """Digest the canonical representation of a replay payload."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
