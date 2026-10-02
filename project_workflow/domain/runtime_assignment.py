"""Shared invariants for backend-owned runtime assignments."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Annotated, Any

from pydantic import AfterValidator, Field, StringConstraints

ROLE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
CANONICAL_UNDERSCORE_ROLE_KEYS = frozenset({"project_manager"})
MAX_WORK_ITEM_REVISION = (1 << 63) - 1
FLEET_AGENT_REF_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
NIL_FLEET_AGENT_REF = "00000000-0000-0000-0000-000000000000"
MANAGED_ROLE_MODE_SCOPES: dict[str, dict[str, tuple[str, ...]]] = {
    "project_manager": {"draft": ("business",)},
    "analyst": {"analysis": ("business",)},
    "architect": {"decomposition": ("business",)},
    "developer": {
        "initial": ("delivery", "aggregate"),
        "rework": ("delivery", "aggregate"),
    },
    "reviewer": {"delivery": ("delivery",), "integration": ("aggregate",)},
    "tester": {"delivery": ("delivery",), "integration": ("aggregate",)},
    "devops": {"delivery": ("delivery",), "integration": ("aggregate",)},
}
MANAGED_WORKFLOW_KEYS = frozenset(
    f"hermes-sdlc:{role_key}" for role_key in MANAGED_ROLE_MODE_SCOPES
)


def phase_allowed_tools(role_key: str, phase_code: str) -> list[str]:
    """Capabilities of exact canonical phase codes; unknown catalogs fail closed."""
    prefixes = {
        "project_manager": {"PM-DRAFT"}, "analyst": {"AN-ANALYSIS"},
        "architect": {"AR-DECOMP"}, "developer": {"DV-INITIAL", "DV-REWORK"},
        "reviewer": {"RV-REVIEW", "RV-INT"}, "tester": {"TS-TEST", "TS-INT"},
        "devops": {"DO-DEPLOY", "DO-INT"},
    }
    prefix, _, number = phase_code.rpartition("-")
    if prefix not in prefixes.get(role_key, set()) or number not in {"01", "02", "03"}:
        return []
    tools = ["workflow", "history", "context", "skills", "question"]
    if role_key in {"developer", "reviewer", "tester"}:
        tools.append("workspace_read")
    if role_key == "developer":
        tools.append("checkpoint")
    if role_key == "project_manager":
        tools.append("draft_update")
    if number == "02":
        tools.extend({
            "developer": ["workspace_write"],
            "tester": ["tester", "tester_browser"], "devops": ["release"],
        }.get(role_key, []))
    if number == "03":
        tools.append("publish_draft" if role_key == "project_manager" else "terminal")
        if role_key == "developer":
            tools.append("candidate_publish")
    return tools


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
    pm_version: int | None = None
    pm_fence: int | None = None

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


def validate_concrete_agent_ref(value: Any) -> str:
    """Accept the canonical Fleet UUID without normalizing a different identity."""
    if (
        not isinstance(value, str) or re.fullmatch(FLEET_AGENT_REF_PATTERN, value) is None
        or value == NIL_FLEET_AGENT_REF
    ):
        raise ValueError("concrete_agent_ref must be a canonical non-nil lowercase Fleet agent UUID")
    return value


FleetAgentRef = Annotated[
    str, StringConstraints(strict=True, pattern=FLEET_AGENT_REF_PATTERN),
    AfterValidator(validate_concrete_agent_ref), Field(json_schema_extra={"not": {"const": NIL_FLEET_AGENT_REF}}),
]


def payload_sha256(value: Any) -> str:
    """Digest the canonical representation of a replay payload."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
