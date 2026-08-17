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

    from .checks import normalize_text

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

    verdict_key = llm.verdict.lower()
    next_phase = None
    next_phase_name = None
    if verdict_key == "pass":
        if len(group) > 1:
            next_phase, next_phase_name = builder._next_after_group(group)
        else:
            next_phase, next_phase_name = builder.get_next_phase(phase.code)
    rollback_target = phase.rollback_target if verdict_key == "rollback" else None
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
        "wizard": {"provider": "ollama", "model": client.model},
    }

    if len(group) > 1:
        engine._record_parallel_transition(
            group,
            verdict_key,
            next_phase if verdict_key == "pass" else rollback_target,
        )
    elif verdict_key == "pass":
        engine._record_transition(phase, "pass", next_phase, None)
    elif verdict_key == "rollback":
        engine._record_transition(phase, "rollback", None, rollback_target)
    else:
        engine._record_transition(phase, verdict_key, None, None)

    task_id = engine.task["id"]
    engine.task = engine.db.get_task(task_id) or engine.task
    engine.current_phase = engine._resolve_current_phase()

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
