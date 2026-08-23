"""Structured types for Supervisor — stable contract for CLI, UI, and tests.

Do NOT import heavy modules here; keep it lightweight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PhaseContract:
    """Expected deliverables for a single phase (or parallel group)."""

    phase_code: str
    phase_name: str
    workflow_revision: str = ""
    actor: str = "hermes"
    description: str = ""
    instructions: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    execution_type: str = "sync"
    delegate_agent: str | None = None
    hermes_profile: str | None = None
    delegate_toolsets: list[str] = field(default_factory=list)
    parallel_with: str | None = None
    rollback_target: str | None = None
    group_phases: list[str] | None = None  # set for parallel blocks
    group_details: list[dict[str, Any]] = field(default_factory=list)  # per-phase details for parallel groups

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_code": self.phase_code,
            "phase_name": self.phase_name,
            "workflow_revision": self.workflow_revision,
            "actor": self.actor,
            "description": self.description,
            "instructions": self.instructions,
            "required_checks": self.required_checks,
            "required_evidence": self.required_evidence,
            "skills": self.skills,
            "execution_type": self.execution_type,
            "delegate_agent": self.delegate_agent,
            "hermes_profile": self.hermes_profile,
            "delegate_toolsets": self.delegate_toolsets,
            "parallel_with": self.parallel_with,
            "rollback_target": self.rollback_target,
            "group_phases": self.group_phases,
            "group_details": self.group_details,
        }


VERDICT_LABELS: dict[str, str] = {
    "pass": "PASS",
    "partial": "PARTIAL",
    "blocked": "BLOCKED",
    "rollback": "ROLLBACK",
    "delegate": "DELEGATE",
}
