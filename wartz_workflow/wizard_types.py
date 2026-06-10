"""Structured types for Wizard — stable contract for CLI, UI, and tests.

Do NOT import heavy modules here; keep it lightweight.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


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
    instructions: List[str] = field(default_factory=list)
    required_checks: List[str] = field(default_factory=list)
    required_evidence: List[str] = field(default_factory=list)
    execution_type: str = "sync"
    delegate_agent: Optional[str] = None
    delegate_toolsets: List[str] = field(default_factory=list)
    next_recommendation: str = ""
    parallel_with: Optional[str] = None
    rollback_target: Optional[str] = None
    group_phases: Optional[List[str]] = None  # set for parallel blocks

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
            "next_recommendation": self.next_recommendation,
            "parallel_with": self.parallel_with,
            "rollback_target": self.rollback_target,
            "group_phases": self.group_phases,
        }


@dataclass
class WizardFinding:
    """A single issue discovered by deterministic checks."""
    severity: str  # "fatal", "error", "warning"
    source: str  # e.g. "missing_artifact", "stale_file", "contradiction"
    message: str
    remediation: Optional[str] = None


@dataclass
class WizardAssessment:
    """Complete assessment for a phase evaluation."""
    task_key: str
    phase_code: str
    phase_name: str
    verdict: str  # pass, partial, blocked, rollback, delegate
    covered: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    findings: List[WizardFinding] = field(default_factory=list)
    next_phase: Optional[str] = None
    next_phase_name: Optional[str] = None
    rollback_target: Optional[str] = None
    next_phase_contract: Optional[PhaseContract] = None
    instructions: List[str] = field(default_factory=list)
    required_checks: List[str] = field(default_factory=list)
    required_evidence: List[str] = field(default_factory=list)
    message: str = ""
    reasoning_mode: str = "deterministic"

    def to_result_dict(self) -> dict[str, Any]:
        """Legacy-compatible result dict for CLI / UI consumers."""
        return {
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
            "next_phase_contract": self.next_phase_contract.to_dict() if self.next_phase_contract else None,
            "message": self.message,
        }


@dataclass
class WizardVerdict:
    """Simple verdict wrapper."""
    status: str
    explanation: str
