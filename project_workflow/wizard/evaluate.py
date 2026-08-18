"""Fail-closed LLM evaluation for one workflow phase report."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import requests

from ..infrastructure.llm import LlmVerdict, OllamaClient, PromptBuilder, ResponseParser
from .contracts import PhaseContractBuilder
from .models import Phase
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


def evaluate_llm_report(report: str, phase: Phase, engine: Any) -> dict[str, Any]:
    """Evaluate a report once; workflow order remains authoritative."""

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
    previously_items = [item for item in checklist if item.strip() in previously]
    user = PromptBuilder.build_user_prompt(
        engine.task_key,
        evaluation_phase,
        report,
        previously_covered=previously_items or None,
    )

    client = OllamaClient()
    try:
        raw = client.chat(system=PromptBuilder.SYSTEM_PROMPT, user=user, temperature=0.1)
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
    next_phase, next_phase_name, rollback_target = engine._resolve_transition(
        phase, verdict_key, group
    )
    if verdict_key != "pass":
        next_phase = None
        next_phase_name = None
    blockers = llm.blockers
    if verdict_key == "blocked" and not blockers:
        blockers = ["Wizard identified a blocker"]

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

    engine._record_evaluation(phase, verdict_key, next_phase, rollback_target)
    task_id = engine.task["id"]

    next_phase_obj = engine.phase_map.get(next_phase) if next_phase else None
    rollback_phase_obj = engine.phase_map.get(rollback_target) if rollback_target else None
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
    return result
