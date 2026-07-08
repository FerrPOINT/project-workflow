"""Result builders for wizard phase evaluation.

Centralizes construction of dict results from WizardAssessment and Phase objects.
"""

from __future__ import annotations

from typing import Any

from .checks import build_verdict_message
from .contracts import (
    PhaseContractBuilder,
    text_from_check,
    text_from_evidence,
    text_from_instruction,
)
from .models import Phase
from .types import WizardAssessment

VERDICT_LABELS = {
    "pass": "PASS",
    "partial": "PARTIAL",
    "soft_fail": "SOFT_FAIL",
    "hard_fail": "HARD_FAIL",
    "blocked": "BLOCKED",
    "rollback": "ROLLBACK",
    "delegate": "DELEGATE",
}


def build_result(
    *,
    task_key: str,
    phase: Phase,
    verdict: str,
    covered: list[str],
    missing: list[str],
    blockers: list[str],
    next_phase: str | None,
    next_phase_name: str | None,
    rollback_target: str | None,
) -> dict[str, Any]:
    """Build a single-phase evaluation result dict."""
    result: dict[str, Any] = {
        "verdict": VERDICT_LABELS[verdict],
        "task_key": task_key,
        "phase": phase.code,
        "phase_name": phase.name,
        "covered": covered,
        "missing": missing,
        "blockers": blockers,
        "current_phase": phase.code,
        "next_phase": next_phase,
        "next_phase_name": next_phase_name,
        "rollback_target": rollback_target,
        "required_evidence": [text_from_evidence(item) for item in phase.evidence],
        "required_checks": [text_from_check(item) for item in phase.checks],
        "instructions": [text_from_instruction(item) for item in phase.instructions],
        "next_step": next_phase or rollback_target or phase.code,
    }
    if verdict == "pass":
        result["message"] = "Phase accepted."
    elif verdict == "rollback":
        result["message"] = f"Roll back and fix: {rollback_target}."
    else:
        result["message"] = build_verdict_message(
            verdict, phase.name, phase.code, blockers, missing, next_phase, rollback_target
        )
    return result


def build_parallel_result(
    *,
    task_key: str,
    group: list[Phase],
    phase_map: dict[str, Phase],
    all_phases: list[Phase],
    verdict: str,
    covered: list[str],
    missing: list[str],
    blockers: list[str],
    next_phase: str | None,
    next_phase_name: str | None,
    rollback_target: str | None,
) -> dict[str, Any]:
    """Build a parallel-group evaluation result dict."""
    first = group[0]
    phase_codes = [p.code for p in group]
    rollback_phase_obj = phase_map.get(rollback_target) if rollback_target else None
    cb = PhaseContractBuilder(all_phases)
    parallel_contract = cb.build_parallel(group).to_dict()
    result: dict[str, Any] = {
        "verdict": VERDICT_LABELS[verdict],
        "task_key": task_key,
        "phase": first.code,
        "phase_name": f"Parallel group: {', '.join(phase_codes)}",
        "covered": covered,
        "missing": missing,
        "blockers": blockers,
        "current_phase": first.code,
        "next_phase": next_phase if verdict == "pass" else rollback_target if verdict == "rollback" else None,
        "next_phase_name": next_phase_name
        if verdict == "pass"
        else (rollback_phase_obj.name if rollback_phase_obj else None),
        "rollback_target": rollback_target,
        "required_evidence": list({text_from_evidence(ev) for p in group for ev in p.evidence}),
        "required_checks": list({text_from_check(chk) for p in group for chk in p.checks}),
        "instructions": [text_from_instruction(inst) for p in group for inst in p.instructions],
        "next_step": next_phase or rollback_target or first.code,
        "group_phases": phase_codes,
        "group_details": parallel_contract.get("group_details") or [],
    }
    if verdict == "pass":
        result["message"] = "Phase accepted."
    elif verdict == "rollback":
        result["message"] = f"Roll back and fix: {rollback_target}."
    elif verdict == "blocked":
        issues = blockers or missing or phase_codes
        result["message"] = f"Blocked: {'; '.join(issues)}. Fix and resubmit."
    elif verdict == "delegate":
        result["message"] = "Delegate the work before continuing."
    elif verdict == "soft_fail":
        issues = missing or ["unspecified items"]
        result["message"] = f"Incomplete: {'; '.join(issues)}. Complete before continuing."
    else:
        issues = missing or ["unspecified items"]
        result["message"] = f"Cannot proceed: {'; '.join(issues)}."
    return result


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
