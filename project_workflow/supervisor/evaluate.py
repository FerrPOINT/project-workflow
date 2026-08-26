"""Fail-closed LLM evaluation for one workflow phase report."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import requests
from sqlalchemy.exc import IntegrityError

from ..domain.exceptions import ConcurrentTransitionError
from ..infrastructure.llm import (
    LlmConfigurationError,
    LlmVerdict,
    OpenAICompatibleClient,
    PromptBuilder,
    ResponseParser,
)
from .checks import normalize_text
from .models import Phase
from .types import VERDICT_LABELS


def _contract_fingerprint(
    *,
    builder: Any,
    phase: Phase,
    group: list[Phase],
    contract: Any,
    evaluation_items: list[tuple[str, str]],
    previously_covered_ids: set[str],
    transition_routes: dict[str, tuple[str | None, str | None, str | None]],
) -> str:
    contract_data = contract.to_dict()
    state = {
        "contract": contract_data,
        "evaluation_items": [{"id": item_id, "text": text} for item_id, text in evaluation_items],
        "previously_covered_ids": sorted(previously_covered_ids),
        "delegation_allowed": bool(phase.is_delegated or phase.delegate),
        "group": [member.code for member in group],
        "transition_routes": transition_routes,
        "phase_graph": [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "description": item.description,
                "execution_type": item.execution_type,
                "parallel_with": item.parallel_with,
                "rollback_target": item.rollback_target,
                "is_delegated": item.is_delegated,
                "delegate": {
                    "agent": item.delegate.agent,
                    "hermes_profile": item.delegate.hermes_profile,
                    "toolsets": item.delegate.toolsets,
                    "timeout_min": item.delegate.timeout_min,
                    "max_cycles": item.delegate.max_cycles,
                }
                if item.delegate
                else None,
                "instructions": [
                    {
                        "id": instruction.id,
                        "step_num": instruction.step_num,
                        "step": instruction.step,
                        "execution_type": instruction.execution_type,
                        "skills": instruction.skills,
                    }
                    for instruction in item.instructions
                ],
                "checks": [
                    {"id": check.id, "description": check.description} for check in item.checks
                ],
                "evidence": [
                    {"id": evidence.id, "item": evidence.item} for evidence in item.evidence
                ],
            }
            for item in builder.all_phases
        ],
    }
    serialized = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def _report_fingerprint(task_id: int, report: str, contract_fingerprint: str) -> str:
    normalized = normalize_text(report)
    return hashlib.sha256(f"{task_id}\0{contract_fingerprint}\0{normalized}".encode()).hexdigest()


def _blocked(exc: Exception) -> LlmVerdict:
    if isinstance(exc, LlmConfigurationError):
        blocker = "Проверяющий LLM не настроен: для OpenRouter требуется OPENAI_API_KEY."
    elif isinstance(exc, (requests.Timeout, TimeoutError)):
        blocker = "Проверяющий LLM не ответил за отведённое время."
    elif isinstance(exc, requests.HTTPError):
        blocker = "Проверяющий LLM отклонил запрос."
    elif isinstance(exc, requests.ConnectionError):
        blocker = "Не удалось установить соединение с проверяющим LLM."
    elif isinstance(exc, requests.RequestException):
        blocker = "Ошибка обмена данными с проверяющим LLM."
    elif isinstance(exc, (ConnectionError, OSError)):
        blocker = "Не удалось установить соединение с проверяющим LLM."
    else:
        blocker = "Проверяющий LLM вернул некорректный ответ."
    return LlmVerdict(
        verdict="BLOCKED",
        covered=[],
        missing=[],
        blockers=[blocker],
        message="Supervisor не смог проверить отчёт; переход заблокирован.",
        next_phase=None,
        next_phase_name=None,
        confidence=0.0,
        raw={"error": type(exc).__name__},
    )


def _contract_changed() -> LlmVerdict:
    return LlmVerdict(
        verdict="BLOCKED",
        covered=[],
        missing=[],
        blockers=["Контракт фазы изменился во время проверки отчёта."],
        message="Повторите отчёт для актуального контракта фазы.",
        next_phase=None,
        next_phase_name=None,
        confidence=0.0,
        raw={"error": "PhaseContractChanged"},
    )


def _replay(
    engine: Any,
    task_id: int,
    phase_id: int,
    fingerprint: str,
    *,
    after_run_id: int | None = None,
) -> dict[str, Any] | None:
    run = engine.db.supervisor_runs.get_by_fingerprint(task_id, phase_id, fingerprint)
    run_id = getattr(run, "id", None) if run is not None else None
    if after_run_id is not None and (run_id is None or int(run_id) <= after_run_id):
        return None
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
        engine._reload_task_state()
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


def _latest_run_id(engine: Any, task_id: int) -> int | None:
    runs = engine.db.supervisor_runs.list(task_id=task_id, limit=1)
    if not runs:
        return None
    run_id = getattr(runs[0], "id", None)
    return int(run_id) if run_id is not None else None


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
    evaluated_phase_code = phase.code
    workflow_id = engine.workflow_id
    if workflow_id is None or engine.db.workflows.lock(workflow_id) is None:
        raise ConcurrentTransitionError("Воркфлоу изменился во время оценки Supervisor")
    engine._reload_evaluation_state()
    if engine.current_phase != evaluated_phase_code:
        engine.db.rollback()
        return _concurrent_result({"task_key": engine.task_key, "phase": evaluated_phase_code})
    phase = engine.phase_map.get(evaluated_phase_code)
    if phase is None:
        engine.db.rollback()
        return engine._blocked_result()

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
    initial_run_id = _latest_run_id(engine, task_id)
    if phase.id is None:
        raise ValueError("Текущая фаза не сохранена в базе данных")
    phase_id = phase.id
    evaluation_items = (
        builder.build_parallel_evaluation_items(group) if len(group) > 1 else builder.build_evaluation_items(phase)
    )
    item_ids = [item_id for item_id, _ in evaluation_items]
    item_text = dict(evaluation_items)
    previously = engine._get_previously_covered(phase.code)
    previously_ids = {
        item_id for item_id, text in evaluation_items if item_id in previously or normalize_text(text) in previously
    }
    initial_previously_ids = set(previously_ids)
    transition_routes = {
        verdict: engine._resolve_transition(phase, verdict, group)
        for verdict in ("pass", "rollback", "delegate")
    }
    initial_contract_fingerprint = _contract_fingerprint(
        builder=builder,
        phase=phase,
        group=group,
        contract=current_contract,
        evaluation_items=evaluation_items,
        previously_covered_ids=previously_ids,
        transition_routes=transition_routes,
    )
    fingerprint = _report_fingerprint(task_id, report, initial_contract_fingerprint)
    replayed = _replay(engine, task_id, phase_id, fingerprint)
    if replayed is not None:
        engine.db.commit()
        engine._reload_task_state()
        if not engine.task:
            return _concurrent_result(replayed)
        return replayed

    user = PromptBuilder.build_user_prompt(
        engine.task_key,
        evaluation_phase,
        report,
        previously_covered=sorted(previously_ids) or None,
        evaluation_items=evaluation_items,
    )

    # Do not keep a database transaction or workflow row lock open across the provider call.
    engine.db.commit()

    client: OpenAICompatibleClient | None = None
    raw: dict[str, Any] | None = None
    technical_error = False
    try:
        client = OpenAICompatibleClient()
        raw = client.chat(system=PromptBuilder.SYSTEM_PROMPT, user=user, temperature=0.1)
        llm = ResponseParser.parse(
            raw,
            required_item_ids=item_ids,
            previously_covered_ids=previously_ids,
        )
        if llm.verdict == "ROLLBACK" and not phase.rollback_target:
            raise ValueError("Для текущей фазы не настроена цель отката")
        if llm.verdict == "DELEGATE" and not (phase.is_delegated or phase.delegate):
            raise ValueError("Для текущей фазы не настроено делегирование")
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

    if engine.db.workflows.lock(workflow_id) is None:
        engine.db.rollback()
        return _concurrent_result({"task_key": engine.task_key, "phase": evaluated_phase_code})
    engine._reload_evaluation_state()
    fresh_phase = engine.phase_map.get(evaluated_phase_code)
    if fresh_phase is None:
        engine.db.rollback()
        if engine.current_phase != evaluated_phase_code:
            engine._reload_task_state()
            return _concurrent_result({"task_key": engine.task_key, "phase": evaluated_phase_code})
        return engine._blocked_result()
    phase = fresh_phase
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
    evaluation_items = (
        builder.build_parallel_evaluation_items(group) if len(group) > 1 else builder.build_evaluation_items(phase)
    )
    item_ids = [item_id for item_id, _ in evaluation_items]
    item_text = dict(evaluation_items)
    previously = engine._get_previously_covered(phase.code)
    previously_ids = {
        item_id for item_id, text in evaluation_items if item_id in previously or normalize_text(text) in previously
    }
    transition_routes = {
        verdict: engine._resolve_transition(phase, verdict, group)
        for verdict in ("pass", "rollback", "delegate")
    }
    current_contract_fingerprint = _contract_fingerprint(
        builder=builder,
        phase=phase,
        group=group,
        contract=current_contract,
        evaluation_items=evaluation_items,
        previously_covered_ids=previously_ids,
        transition_routes=transition_routes,
    )
    current_snapshot_fingerprint = _contract_fingerprint(
        builder=builder,
        phase=phase,
        group=group,
        contract=current_contract,
        evaluation_items=evaluation_items,
        previously_covered_ids=initial_previously_ids,
        transition_routes=transition_routes,
    )
    if current_snapshot_fingerprint == initial_contract_fingerprint:
        # Another identical evaluation may have committed while this provider
        # call was in flight.  Replay it only after proving the catalog still
        # matches the provider snapshot.
        replayed = _replay(
            engine,
            task_id,
            phase_id,
            fingerprint,
            after_run_id=initial_run_id or 0,
        )
        if replayed is not None:
            engine.db.commit()
            engine._refresh_task_state()
            if not engine.task:
                return _concurrent_result(replayed)
            return replayed
    if _latest_run_id(engine, task_id) != initial_run_id:
        engine.db.rollback()
        engine._reload_task_state()
        return _concurrent_result({"task_key": engine.task_key, "phase": evaluated_phase_code})
    if engine.current_phase != evaluated_phase_code:
        engine.db.rollback()
        engine._reload_task_state()
        return _concurrent_result({"task_key": engine.task_key, "phase": evaluated_phase_code})
    if current_contract_fingerprint != initial_contract_fingerprint:
        technical_error = True
        llm = _contract_changed()

    covered_ids = llm.covered if not technical_error else [item_id for item_id in item_ids if item_id in previously_ids]
    missing_ids = (
        llm.missing if not technical_error else [item_id for item_id in item_ids if item_id not in previously_ids]
    )
    covered = [item_text[item_id] for item_id in covered_ids]
    missing = [item_text[item_id] for item_id in missing_ids]

    verdict_key = llm.verdict.lower()
    blockers = llm.blockers
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
            "model": client.model if client is not None else None,
            "endpoint_mode": "openai-compatible",
            "prompt_version": PromptBuilder.PROMPT_VERSION,
            "contract_fingerprint": current_contract_fingerprint,
            "evaluated_contract_fingerprint": initial_contract_fingerprint,
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
    if not engine.task:
        return _concurrent_result(result)
    return result
