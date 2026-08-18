"""Result builder for wizard phase evaluation."""

from __future__ import annotations

from .checks import build_verdict_message
from .contracts import (
    text_from_check,
    text_from_evidence,
    text_from_instruction,
)
from .models import Phase
from .types import WizardAssessment


def build_assessment(
    *,
    task_key: str,
    phase: Phase,
    group: list[Phase],
    verdict: str,
    covered: list[str],
    missing: list[str],
    blockers: list[str],
    next_phase: str | None,
    next_phase_name: str | None,
    rollback_target: str | None,
    next_phase_contract,
) -> WizardAssessment:
    """Build a WizardAssessment from raw evaluation results."""
    is_parallel = len(group) > 1
    phase_name = phase.name
    if is_parallel:
        phase_name = f"Parallel group: {', '.join(p.code for p in group)}"
    return WizardAssessment(
        task_key=task_key,
        phase_code=phase.code,
        phase_name=phase_name,
        verdict=verdict,
        covered=covered,
        missing=missing,
        blockers=blockers,
        next_phase=next_phase if verdict == "pass" else (rollback_target if verdict == "rollback" else None),
        next_phase_name=next_phase_name if verdict == "pass" else None,
        rollback_target=rollback_target,
        next_phase_contract=next_phase_contract,
        instructions=[text_from_instruction(i) for i in phase.instructions],
        required_checks=[text_from_check(c) for c in phase.checks],
        required_evidence=[text_from_evidence(e) for e in phase.evidence],
        message=build_verdict_message(
            verdict=verdict,
            phase_name=phase_name,
            phase_code=phase.code,
            blockers=blockers,
            missing=missing,
            next_phase=next_phase,
            rollback_target=rollback_target,
        ),
        group_phases=[p.code for p in group] if is_parallel else None,
    )
