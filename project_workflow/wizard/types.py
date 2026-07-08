"""Structured types for Wizard — stable contract for CLI, UI, and tests.

Do NOT import heavy modules here; keep it lightweight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ArtifactSnapshot:
    """Snapshot of a task artifact file."""

    path: str
    exists: bool
    mtime: float = 0.0
    size: int = 0


@dataclass
class PhaseContract:
    """Expected deliverables for a single phase (or parallel group)."""

    phase_code: str
    phase_name: str
    description: str = ""
    instructions: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    execution_type: str = "sync"
    delegate_agent: str | None = None
    delegate_toolsets: list[str] = field(default_factory=list)
    parallel_with: str | None = None
    rollback_target: str | None = None
    group_phases: list[str] | None = None  # set for parallel blocks
    group_details: list[dict[str, Any]] = field(default_factory=list)  # per-phase details for parallel groups

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_code": self.phase_code,
            "phase_name": self.phase_name,
            "description": self.description,
            "instructions": self.instructions,
            "required_checks": self.required_checks,
            "required_evidence": self.required_evidence,
            "execution_type": self.execution_type,
            "delegate_agent": self.delegate_agent,
            "delegate_toolsets": self.delegate_toolsets,
            "parallel_with": self.parallel_with,
            "rollback_target": self.rollback_target,
            "group_phases": self.group_phases,
            "group_details": self.group_details,
        }


@dataclass
class WizardFinding:
    """A single issue discovered by deterministic checks."""

    severity: str  # "fatal", "error", "warning"
    source: str  # e.g. "missing_artifact", "stale_file", "contradiction"
    message: str
    remediation: str | None = None


@dataclass
class WizardAssessment:
    """Complete assessment for a phase evaluation."""

    task_key: str
    phase_code: str
    phase_name: str
    verdict: str  # pass, partial, blocked, rollback, delegate
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    findings: list[WizardFinding] = field(default_factory=list)
    next_phase: str | None = None
    next_phase_name: str | None = None
    rollback_target: str | None = None
    next_phase_contract: PhaseContract | None = None
    instructions: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    message: str = ""
    reasoning_mode: str = "deterministic"
    group_phases: list[str] | None = None  # set for parallel blocks

    def to_result_dict(self) -> dict[str, Any]:
        """Legacy-compatible result dict for CLI / UI consumers."""
        next_contract_dict = self.next_phase_contract.to_dict() if self.next_phase_contract else None
        result = {
            "verdict": self.verdict.upper() if self.verdict else "UNKNOWN",
            "task_key": self.task_key,
            "phase": self.phase_code,
            "phase_name": self.phase_name,
            "covered": self.covered,
            "missing": self.missing,
            "blockers": self.blockers,
            "current_phase": self.phase_code,
            "next_phase": self.next_phase,
            "next_phase_name": self.next_phase_name,
            "rollback_target": self.rollback_target,
            "required_evidence": self.required_evidence,
            "required_checks": self.required_checks,
            "instructions": self.instructions,
            "next_step": self.next_phase or self.rollback_target or self.phase_code,
            "next_phase_contract": next_contract_dict,
            "message": self.message,
        }
        if self.group_phases:
            result["group_phases"] = self.group_phases
            if next_contract_dict:
                result["group_details"] = next_contract_dict.get("group_details") or []
        return result


VERDICT_LABELS: dict[str, str] = {
    "pass": "PASS",
    "partial": "PARTIAL",
    "soft_fail": "SOFT_FAIL",
    "hard_fail": "HARD_FAIL",
    "blocked": "BLOCKED",
    "rollback": "ROLLBACK",
    "delegate": "DELEGATE",
}
