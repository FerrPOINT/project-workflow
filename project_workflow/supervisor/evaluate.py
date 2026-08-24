"""Fail-closed LLM evaluation for one workflow phase report."""

from __future__ import annotations

import hashlib
from typing import Any

import requests
from sqlalchemy.exc import IntegrityError

from ..domain.exceptions import ConcurrentTransitionError
from ..infrastructure.llm import LlmVerdict, OpenAICompatibleClient, PromptBuilder, ResponseParser
from .checks import normalize_text
from .models import Phase
from .types import VERDICT_LABELS


def _report_fingerprint(task_id: int, report: str) -> str:
    normalized = normalize_text(report)
    return hashlib.sha256(f"{task_id}\0{normalized}".encode()).hexdigest()


def _blocked(exc: Exception) -> LlmVerdict:
    return LlmVerdict(
        verdict="BLOCKED",
        covered=[],
        missing=[],
        blockers=[f"Supervisor LLM unavailable: {type(exc).__name__}"],
        message="Supervisor не смог проверить отчёт; переход заблокирован.",
        next_phase=None,
        next_phase_name=None,
        confidence=0.0,
        raw={"error": type(exc).__name__},
    )


def _replay(engine: Any, task_id: int, phase_id: int, fingerprint: str) -> dict[str, Any] | None:
    run = engine.db.supervisor_runs.get_by_fingerprint(task_id, phase_id, fingerprint)
    response = getattr(run, "response", None) if run is not None else None
    if not isinstance(response, dict):
        return None
    result = dict(response)
    result["replayed"] = True
    task = engine.db.tasks.get_by_id(task_id)
    verdict = str(response.get("verdict") or "").lower()
    evaluated_phase = str(response.get("phase") or "")
    next_phase = str(response.get("next_phase") or "") or None
    rollback_target = str(response.get("rollback_target") or "") or None
    expected_phase = evaluated_phase
    expected_status = "active"
    if verdict == "pass":
        expected_phase = next_phase or evaluated_phase
        expected_status = "active" if next_phase else "done"
    elif verdict == "rollback":
        expected_phase = rollback_target or evaluated_phase
    elif verdict == "blocked":
        expected_status = "blocked"

    current_phase = str(getattr(task, "current_phase", "") or "")
    current_status = str(getattr(task, "status", "") or "")
    if (current_phase, current_status) != (expected_phase, expected_status):
        if current_phase != evaluated_phase or verdict not in {"pass", "partial", "blocked", "rollback", "delegate"}:
            return None
        engine._refresh_task_state()
        refreshed_phase = str(engine.task.get("current_phase") or "")
        refreshed_status = str(engine.task.get("status") or "")
        if (refreshed_phase, refreshed_status) == (expected_phase, expected_status):
            return result
        if refreshed_phase != evaluated_phase:
            return None
        phase = engine.phase_map.get(evaluated_phase)
        if phase is None:
            return None
        try:
            engine._record_evaluation(phase, verdict, next_phase if verdict == "pass" else None, rollback_target)
        except ConcurrentTransitionError:
            engine.db.rollback()
            return _concurrent_result(result)
    return result


def _concurrent_result(result: dict[str, Any]) -> dict[str, Any]:
    blocked = dict(result)
    blocked.update(
        {
            "verdict": "BLOCKED",
            "next_phase": None,
            "next_phase_name": None,
            "rollback_target": None,
            "blockers": ["Задача была изменена другим параллельным запуском Supervisor."],
            "message": "Повторите отчёт для актуальной фазы задачи.",
            "retryable": True,
            "replayed": False,
        }
    )
    blocked.pop("next_phase_contract", None)
    return blocked


def evaluate_llm_report(report: str, phase: Phase, engine: Any) -> dict[str, Any]:
    """Evaluate once; the workflow remains the only owner of routing."""
    builder = engine.contract_builder
    group = builder.get_parallel_group(phase) if phase.execution_type == "parallel" else [phase]
    current_contract = builder.build_parallel(group) if len(group) > 1 else builder.build(phase)
    evaluation_phase = phase
    if len(group) > 1:
        evaluation_phase = Phase(
            id=phase.id,
            code=phase.code,
            name=current_contract.phase_name,
            description=current_contract.description,
            instructions=[item for member in group for item in member.instructions],
            checks=[item for member in group for item in member.checks],
            evidence=[item for member in group for item in member.evidence],
            execution_type="parallel",
            rollback_target=phase.rollback_target,
        )

    task_id = int(engine.task["id"])
    if phase.id is None:
        raise ValueError("Current phase is not persisted")
    phase_id = phase.id
    fingerprint = _report_fingerprint(task_id, report)
    replayed = _replay(engine, task_id, phase_id, fingerprint)
    if replayed is not None:
        return replayed

    evaluation_items = (
        builder.build_parallel_evaluation_items(group) if len(group) > 1 else builder.build_evaluation_items(phase)
    )
    item_ids = [item_id for item_id, _ in evaluation_items]
    item_text = dict(evaluation_items)
    previously = engine._get_previously_covered(phase.code)
    previously_ids = {
        item_id for item_id, text in evaluation_items if item_id in previously or normalize_text(text) in previously
    }
    user = PromptBuilder.build_user_prompt(
        engine.task_key,
        evaluation_phase,
        report,
        previously_covered=sorted(previously_ids) or None,
        evaluation_items=evaluation_items,
    )

    client = OpenAICompatibleClient()
    raw: dict[str, Any] | None = None
    technical_error = False
    try:
        raw = client.chat(system=PromptBuilder.SYSTEM_PROMPT, user=user, temperature=0.1)
        llm = ResponseParser.parse(
            raw,
            required_item_ids=item_ids,
            previously_covered_ids=previously_ids,
        )
        if llm.verdict == "ROLLBACK" and not phase.rollback_target:
            raise ValueError("rollback target is not configured for the current phase")
        if llm.verdict == "DELEGATE" and not (phase.is_delegated or phase.delegate):
            raise ValueError("delegation is not configured for the current phase")
    except (
        requests.RequestException,
        OSError,
        TypeError,
        ValueError,
        KeyError,
        IndexError,
        AttributeError,
    ) as exc:
        technical_error = True
        llm = _blocked(exc)

    covered_ids = llm.covered if not technical_error else [item_id for item_id in item_ids if item_id in previously_ids]
    missing_ids = (
        llm.missing if not technical_error else [item_id for item_id in item_ids if item_id not in previously_ids]
    )
    covered = [item_text[item_id] for item_id in covered_ids]
    missing = [item_text[item_id] for item_id in missing_ids]

    verdict_key = llm.verdict.lower()
    blockers = llm.blockers or (["LLM identified blocker"] if verdict_key == "blocked" else [])
    next_phase, next_phase_name, rollback_target = engine._resolve_transition(phase, verdict_key, group)
    if verdict_key != "pass" or technical_error:
        next_phase = None
        next_phase_name = None
        rollback_target = None if technical_error else rollback_target

    result: dict[str, Any] = {
        "verdict": VERDICT_LABELS.get(verdict_key, llm.verdict),
        "task_key": engine.task_key,
        "phase": phase.code,
        "phase_name": evaluation_phase.name,
        "covered": covered,
        "missing": missing,
        "blockers": blockers,
        "current_phase": phase.code,
        "next_phase": rollback_target if verdict_key == "rollback" else next_phase,
        "next_phase_name": next_phase_name,
        "rollback_target": rollback_target,
        "message": llm.message,
        "confidence": llm.confidence,
        "instructions": current_contract.instructions,
        "required_checks": current_contract.required_checks,
        "required_evidence": current_contract.required_evidence,
        "group_phases": current_contract.group_phases,
        "group_details": current_contract.group_details,
        "replayed": False,
        "retryable": technical_error,
    }
    next_phase_contract = builder.build_next_contract(next_phase) if verdict_key == "pass" else None
    if next_phase_contract is not None:
        result["next_phase_contract"] = next_phase_contract.to_dict()

    next_phase_obj = engine.phase_map.get(next_phase) if next_phase else None
    rollback_phase_obj = engine.phase_map.get(rollback_target) if rollback_target else None
    raw_evaluator = llm.raw if technical_error else (raw if raw is not None else llm.raw)
    run_data = {
        "task_id": task_id,
        "phase_id": phase.id,
        "verdict": verdict_key,
        "report": report,
        "covered": covered,
        "missing": missing,
        "blockers": blockers,
        "next_phase_id": next_phase_obj.id if next_phase_obj else None,
        "rollback_phase_id": rollback_phase_obj.id if rollback_phase_obj else None,
        "report_fingerprint": None if technical_error else fingerprint,
        "context_snapshot": {
            "phase": phase.code,
            "phase_name": evaluation_phase.name,
            "model": client.model,
            "endpoint_mode": "openai-compatible",
            "prompt_version": PromptBuilder.PROMPT_VERSION,
            "contract_snapshot": {
                **current_contract.to_dict(),
                "evaluation_items": [{"id": item_id, "text": text} for item_id, text in evaluation_items],
            },
            "covered_item_ids": covered_ids,
            "raw_evaluator": raw_evaluator,
        },
        "response": result,
    }

    try:
        engine.db.create_supervisor_run(run_data)
        engine._record_evaluation(phase, verdict_key, next_phase, rollback_target, commit=False)
        engine.db.commit()
    except IntegrityError:
        engine.db.rollback()
        replayed = _replay(engine, task_id, phase_id, fingerprint)
        if replayed is not None:
            return replayed
        raise
    except ConcurrentTransitionError:
        engine.db.rollback()
        return _concurrent_result(result)
    except Exception:
        engine.db.rollback()
        raise

    engine._refresh_task_state()
    return result
