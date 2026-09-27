"""Shared invariants for backend-owned runtime assignments."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

ROLE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


@dataclass(frozen=True)
class RuntimeStepFence:
    """Exact owner-issued assignment/run snapshot allowed to mutate one task."""

    assignment_revision: int
    assignment_operation_key: str
    assignment_ref: str
    binding_ref: str
    hermes_run_ref: str
    mode_id: int
    mode_key: str
    cycle_number: int
    attempt_number: int
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


def normalize_role_key(value: Any) -> str:
    """Return one runtime-safe role key or reject it consistently."""
    if not isinstance(value, str):
        raise ValueError("role_key должен быть строкой")
    normalized = value.strip()
    if ROLE_KEY_PATTERN.fullmatch(normalized) is None:
        raise ValueError("role_key должен соответствовать [a-z][a-z0-9-]{1,31}")
    return normalized


def canonical_json(value: Any) -> str:
    """Serialize replay-significant data with one stable byte representation."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_sha256(value: Any) -> str:
    """Digest the canonical representation of a replay payload."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
