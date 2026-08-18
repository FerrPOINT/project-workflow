"""Fail-closed LLM evaluation for one workflow phase report."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import requests

from ..infrastructure.llm import LlmVerdict, OllamaClient, PromptBuilder, ResponseParser
from .checks import normalize_text
from .contracts import PhaseContractBuilder
from .models import Phase
from .reasoning import ReasoningResult
from .types import VERDICT_LABELS


def _blocked(exc: Exception) -> LlmVerdict:
    return LlmVerdict(
        verdict="BLOCKED",
        covered=[],
        missing=[],
        blockers=[f"Wizard LLM unavailable: {type(exc).__name__}"],
        message="Wizard не смог проверить отчёт; переход заблокирован.",
        next_phase=None,
        next_phase_name=None,
        confidence=0.0,
        raw={"error": type(exc).__name__},
    )


def _result_from_reasoning(
    reasoning: ReasoningResult,
    report: str,
    phase: Phase,
    engine: Any,
) -> dict[str, Any]:
    """Preserve the legacy result adapter; the runtime evaluator does not select it."""
    verdict_label = VERDICT_LABELS.get(reasoning.verdict.lower(), reasoning.verdict)
    verdict_key = reasoning.verdict.lower()

    builder = PhaseContractBuilder(engine.all_phases)
    next_phase = None
    next_phase_name = None
    if reasoning.verdict == "PASS":
        next_phase, next_phase_name = builder.get_next_phase(phase.code)

    rollback_target = phase.rollback_target if verdict_key == "rollback" else None
    blockers = (
        ["Reasoning identified blocker"]
        if verdict_key == "blocked" and not reasoning.blockers
        else reasoning.blockers
    )
    covered = [claim.get("item") for claim in reasoning.claims if claim.get("valid")]
    result: dict[str, Any] = {
        "verdict": verdict_label,
        "task_key": engine.task_key,
        "phase": phase.code,
        "phase_name": phase.name,
        "covered": covered,
        "missing": reasoning.missing,
        "blockers": blockers,
        "current_phase": phase.code,
        "next_phase": next_phase,
        "next_phase_name": next_phase_name,
        "rollback_target": rollback_target,
        "message": reasoning.analysis or "",
        "confidence": reasoning.confidence,
        "next_steps": reasoning.next_steps,
        "reasoning": reasoning.raw,
    }

    engine._record_evaluation(phase, verdict_key, next_phase, rollback_target, commit=False)
    next_phase_obj = engine.phase_map.get(next_phase) if next_phase else None
    rollback_phase_obj = engine.phase_map.get(rollback_target) if rollback_target else None
    try:
        engine.db.create_supervisor_run(
            {
                "task_id": engine.task["id"],
                "phase_id": phase.id,
                "verdict": verdict_key,
                "report": report,
                "covered": covered,
                "missing": reasoning.missing,
                "blockers": blockers,
                "next_phase_id": next_phase_obj.id if next_phase_obj else None,
                "rollback_phase_id": rollback_phase_obj.id if rollback_phase_obj else None,
                "context_snapshot": {
                    "phase": phase.code,
                    "phase_name": phase.name,
                    "current_contract": {"phase_code": phase.code},
                },
                "response": result,
            }
        )
        engine.db.commit()
    except Exception:
        engine.db.rollback()
        raise
    return result


def evaluate_llm_report(report: str, phase: Phase, engine: Any) -> dict[str, Any]:
    """Evaluate once; the workflow remains the only owner of routing."""
    builder = PhaseContractBuilder(engine.all_phases)
    group = builder.get_parallel_group(phase) if phase.execution_type == "parallel" else [phase]
    evaluation_phase = phase
    if len(group) > 1:
        contract = builder.build_parallel(group)
        evaluation_phase = Phase(
            id=phase.id,
            code=phase.code,
            name=contract.phase_name,
            description=contract.description,
            instructions=[item for member in group for item in member.instructions],
            checks=[item for member in group for item in member.checks],
            evidence=[item for member in group for item in member.evidence],
            execution_type="parallel",
            rollback_target=phase.rollback_target,
        )

    previously = engine._get_previously_covered(phase.code)
    checklist = builder.build_parallel_checklist(group) if len(group) > 1 else builder.build_checklist(phase)
    previously_items = [item for item in checklist if normalize_text(item) in previously]
    user = PromptBuilder.build_user_prompt(
        engine.task_key,
        evaluation_phase,
        report,
        previously_covered=previously_items or None,
    )

    try:
        raw = OllamaClient().chat(system=PromptBuilder.SYSTEM_PROMPT, user=user, temperature=0.1)
        llm = ResponseParser.parse(raw)
    except (
        requests.RequestException,
        OSError,
        TypeError,
        ValueError,
        KeyError,
        IndexError,
        AttributeError,
    ) as exc:
        llm = _blocked(exc)

    if llm.verdict == "ROLLBACK" and not phase.rollback_target:
        llm = replace(
            llm,
            verdict="BLOCKED",
            blockers=["rollback target is not configured for the current phase"],
        )
    if llm.verdict == "DELEGATE" and not (phase.is_delegated or phase.delegate):
        llm = replace(
            llm,
            verdict="BLOCKED",
            blockers=["delegation is not configured for the current phase"],
        )

    verdict_key = llm.verdict.lower()
    next_phase, next_phase_name, rollback_target = engine._resolve_transition(phase, verdict_key, group)
    if verdict_key != "pass":
        next_phase = None
        next_phase_name = None
    blockers = llm.blockers or (["LLM identified blocker"] if verdict_key == "blocked" else [])

    result: dict[str, Any] = {
        "verdict": VERDICT_LABELS.get(verdict_key, llm.verdict),
        "task_key": engine.task_key,
        "phase": phase.code,
        "phase_name": evaluation_phase.name,
        "covered": llm.covered,
        "missing": llm.missing,
        "blockers": blockers,
        "current_phase": phase.code,
        "next_phase": rollback_target if verdict_key == "rollback" else next_phase,
        "next_phase_name": next_phase_name,
        "rollback_target": rollback_target,
        "message": llm.message,
        "confidence": llm.confidence,
    }

    task_id = engine.task["id"]
    next_phase_obj = engine.phase_map.get(next_phase) if next_phase else None
    rollback_phase_obj = engine.phase_map.get(rollback_target) if rollback_target else None
    try:
        engine._record_evaluation(phase, verdict_key, next_phase, rollback_target, commit=False)
        engine.db.create_supervisor_run(
            {
                "task_id": task_id,
                "phase_id": phase.id,
                "verdict": verdict_key,
                "report": report,
                "covered": llm.covered,
                "missing": llm.missing,
                "blockers": blockers,
                "next_phase_id": next_phase_obj.id if next_phase_obj else None,
                "rollback_phase_id": rollback_phase_obj.id if rollback_phase_obj else None,
                "context_snapshot": {
                    "phase": phase.code,
                    "phase_name": evaluation_phase.name,
                    "current_contract": {"phase_code": phase.code},
                },
                "response": result,
            }
        )
        engine.db.commit()
    except Exception:
        engine.db.rollback()
        raise
    return result
