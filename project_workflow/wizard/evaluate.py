"""LLM evaluate logic — extracted from wizard.py.

Public API: evaluate_llm_report(report, phase, engine).
"""
from __future__ import annotations

from typing import Any

from .models import Phase
from .types import VERDICT_LABELS
from .contracts import PhaseContractBuilder
from ..infrastructure.llm import OllamaClient, PromptBuilder, ResponseParser


def evaluate_llm_report(report: str, phase: Phase, engine: Any) -> dict:
    """LLM-based evaluate via Ollama + Kimi K2.5."""
    from .checks import normalize_text

    previously = engine._get_previously_covered(phase.code)
    checklist = PhaseContractBuilder(engine.all_phases).build_checklist(phase)
    previously_items = [
        item for item in checklist
        if normalize_text(item) in previously
    ]

    system = PromptBuilder.SYSTEM_PROMPT
    user = PromptBuilder.build_user_prompt(
        engine.task_key, phase, report, previously_covered=previously_items or None
    )

    client = OllamaClient()
    raw = client.chat(system=system, user=user, temperature=0.1)
    llm = ResponseParser.parse(raw)

    next_phase = llm.next_phase
    next_phase_name = llm.next_phase_name
    if llm.verdict == "PASS" and not next_phase:
        cb = PhaseContractBuilder(engine.all_phases)
        next_phase, next_phase_name = cb.get_next_phase(phase.code)

    blockers = llm.blockers if llm.blockers else []
    if llm.verdict == "BLOCKED":
        blockers = llm.blockers if llm.blockers else ["LLM identified blocker"]

    result = {
        "verdict": VERDICT_LABELS.get(llm.verdict.lower(), llm.verdict),
        "task_key": engine.task_key,
        "phase": phase.code,
        "phase_name": phase.name,
        "covered": llm.covered,
        "missing": llm.missing,
        "blockers": blockers,
        "current_phase": phase.code,
        "next_phase": next_phase,
        "next_phase_name": next_phase_name,
        "rollback_target": phase.rollback_target if llm.verdict == "ROLLBACK" else None,
        "message": llm.message,
        "confidence": llm.confidence,
    }

    verdict_key = llm.verdict.lower()
    if verdict_key == "pass":
        engine._record_transition(phase, "pass", next_phase, None)
    elif verdict_key == "rollback":
        engine._record_transition(phase, "rollback", None, phase.rollback_target)
    else:
        engine._record_transition(phase, verdict_key, None, None)

    engine.task = engine.db.get_task(engine.task["id"]) or engine.task
    engine.current_phase = engine._resolve_current_phase()

    context_snapshot = {
        "phase": phase.code,
        "phase_name": phase.name,
        "current_contract": {"phase_code": phase.code},
    }

    next_phase_int = None
    if next_phase:
        npo = engine.phase_map.get(next_phase)
        next_phase_int = npo.id if npo else None
    rollback_int = None
    if phase.rollback_target:
        rpo = engine.phase_map.get(phase.rollback_target)
        rollback_int = rpo.id if rpo else None

    engine.db.create_supervisor_run(
        {
            "task_id": engine.task["id"],
            "phase_id": phase.id,
            "verdict": verdict_key,
            "report": report,
            "covered": llm.covered,
            "missing": llm.missing,
            "blockers": blockers,
            "next_phase_id": next_phase_int if verdict_key == "pass" else None,
            "rollback_phase_id": rollback_int if verdict_key == "rollback" else None,
            "context_snapshot": context_snapshot,
            "response": result,
        }
    )
    return result
