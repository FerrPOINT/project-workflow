"""Fail-closed LLM evaluation for one workflow phase report."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import requests
from sqlalchemy.exc import IntegrityError

from .. import config
from ..domain.configured_cli import ConfiguredCliFence
from ..domain.exceptions import ConcurrentTransitionError
from ..domain.phase_report import PhaseReport, PhaseReportFormatError
from ..domain.standalone import StandaloneFence
from ..infrastructure.llm import (
    LlmConfigurationError,
    LlmVerdict,
    OpenAICompatibleClient,
    PromptBuilder,
    ResponseParser,
)
from .diagnostics import capture_attempt, evaluation_diagnostic
from .models import Phase
from .types import VERDICT_LABELS


class PhaseCriteriaConfigurationError(LlmConfigurationError):
    """An evaluated phase/group has no configured criteria."""


def _contract_fingerprint_state(
    *,
    builder: Any,
    phase: Phase,
    group: list[Phase],
    contract: Any,
    evaluation_items: list[tuple[str, str]],
    previously_covered_ids: set[str],
    transition_routes: dict[str, tuple[str | None, str | None, str | None]],
    prompt_version: str | None = None,
    delegation_allowed: bool | None = None,
    phase_context_fingerprint: str | None = None,
) -> dict[str, Any]:
    contract_data = contract.to_dict()
    state = {
        "prompt_version": PromptBuilder.PROMPT_VERSION if prompt_version is None else prompt_version,
        "evaluator_response_format": config.get_settings().OPENAI_EVALUATOR_RESPONSE_FORMAT,
        "contract": contract_data,
        "evaluation_items": [{"id": item_id, "text": text} for item_id, text in evaluation_items],
        "previously_covered_ids": sorted(previously_covered_ids),
        "delegation_allowed": phase.delegate is not None if delegation_allowed is None else delegation_allowed,
        "group": [member.code for member in group],
        "transition_routes": transition_routes,
        "phase_graph": [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "description": item.description,
                "execution_type": item.execution_type,
                "delegate": {
                    "agent": item.delegate.agent,
                    "hermes_profile": item.delegate.hermes_profile,
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
    if phase_context_fingerprint is not None:
        state["phase_context_fingerprint"] = phase_context_fingerprint
    return state


def _fingerprint_contract_state(state: dict[str, Any]) -> str:
    serialized = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def _contract_fingerprint(
    *, builder: Any, phase: Phase, group: list[Phase], contract: Any,
    evaluation_items: list[tuple[str, str]], previously_covered_ids: set[str],
    transition_routes: dict[str, tuple[str | None, str | None, str | None]],
    prompt_version: str | None = None,
    delegation_allowed: bool | None = None,
    phase_context_fingerprint: str | None = None,
) -> str:
    return _fingerprint_contract_state(_contract_fingerprint_state(
        builder=builder, phase=phase, group=group, contract=contract, evaluation_items=evaluation_items,
        previously_covered_ids=previously_covered_ids, transition_routes=transition_routes,
        prompt_version=prompt_version,
        delegation_allowed=delegation_allowed,
        phase_context_fingerprint=phase_context_fingerprint,
    ))


def _report_fingerprint(task_id: int, report: str, contract_fingerprint: str) -> str:
    return hashlib.sha256(f"{task_id}\0{contract_fingerprint}\0{report}".encode()).hexdigest()


def _blocked(exc: Exception, *, provider_outcome: str | None = None) -> LlmVerdict:
    provider_blockers = {
        "incomplete": "Ответ проверяющего LLM не завершён: достигнут лимит токенов.",
        "refusal": "Провайдер проверяющего LLM отказался формировать ответ.",
        "content_filter": "Ответ проверяющего LLM остановлен фильтром провайдера.",
    }
    if provider_outcome is not None and provider_outcome in provider_blockers:
        blocker = provider_blockers[provider_outcome]
    elif isinstance(exc, PhaseCriteriaConfigurationError):
        blocker = "У фазы или параллельной группы не настроены критерии проверки. Настройте checks или evidence."
    elif isinstance(exc, PhaseReportFormatError):
        blocker = ("История текущей фазы содержит несовместимый отчёт. Оценка не выполнена; "
                   "требуется явный переход данных на текущий контракт.")
    elif isinstance(exc, LlmConfigurationError):
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
    run = engine.db.step_history.get_by_fingerprint(
        task_id, phase_id, fingerprint, mode_id=int(engine.task.get("mode_id") or 0),
        cycle_number=int(engine.task.get("cycle_number") or 0),
    )
    run_id = getattr(run, "id", None) if run is not None else None
    if after_run_id is not None and (run_id is None or int(run_id) <= after_run_id):
        return None
    response = getattr(run, "supervisor_response", None) if run is not None else None
    if not isinstance(response, dict):
        return None
    result = dict(response)
    result["replayed"] = True
    task = engine.db.tasks.get_by_id(task_id)
    verdict = str(response.get("verdict") or "").lower()
    if verdict not in VERDICT_LABELS:
        return None
    evaluated_phase = str(response.get("phase_code") or "")
    next_phase_code = str(response.get("next_phase_code") or "") or None
    expected_phase = evaluated_phase
    expected_status = "active"
    if verdict == "pass":
        expected_phase = next_phase_code or evaluated_phase
        expected_status = "active" if next_phase_code else "done"
    elif verdict == "blocked":
        expected_status = "blocked"

    current_phase_code = str(getattr(task, "current_phase_code", "") or "")
    current_status = str(getattr(task, "status", "") or "")
    if (current_phase_code, current_status) == (expected_phase, expected_status):
        return result
    raise ConcurrentTransitionError(
        "Сохранённый step не совпадает с текущим cursor задачи; replay не изменяет состояние"
    )


def _latest_run_id(engine: Any, task_id: int) -> int | None:
    runs = engine.db.step_history.list(task_id=task_id, limit=1)
    if not runs:
        return None
    run_id = getattr(runs[0], "id", None)
    return int(run_id) if run_id is not None else None


def _concurrent_result(result: dict[str, Any]) -> dict[str, Any]:
    blocked = dict(result)
    blocked.update(
        {
            "verdict": "BLOCKED",
            "next_phase_code": None,
            "next_phase_name": None,
            "rollback_phase_code": None,
            "blockers": ["Задача была изменена другим параллельным запуском Supervisor."],
            "message": "Повторите отчёт для актуальной фазы задачи.",
            "retryable": True,
            "replayed": False,
        }
    )
    blocked.pop("next_phase_contract", None)
    return blocked


def _evaluate_strict_response(
    client: OpenAICompatibleClient,
    *,
    user: str,
    evaluation_items: list[tuple[str, str]],
    phase: Phase,
    attempts: list[dict[str, Any]] | None = None,
    system: str = PromptBuilder.SYSTEM_PROMPT,
    response_format: dict[str, Any] | None = None,
    delegation_allowed: bool | None = None,
) -> tuple[dict[str, Any], LlmVerdict]:
    """Evaluate exactly once; malformed output is a technical failure."""
    allowed = PromptBuilder.allowed_verdicts(
        phase.delegate is not None if delegation_allowed is None else delegation_allowed,
    )
    raw: dict[str, Any] | None = None
    error: Exception | None = None
    try:
        format_options = {"response_format": response_format} if response_format is not None else {}
        raw = client.chat(system=system, user=user, temperature=0.1, **format_options)
        llm = ResponseParser.parse_assessments(raw, evaluation_items=evaluation_items)
        if llm.verdict not in allowed:
            raise ValueError("Для текущей фазы не настроено делегирование")
        return raw, llm
    except (TypeError, ValueError, KeyError, IndexError, AttributeError, requests.RequestException, OSError) as exc:
        error = exc
        raise
    finally:
        if attempts is not None:
            try:
                attempts.append(capture_attempt(client, number=1, prompt=user, raw=raw, error=error, system=system))
            except Exception as diagnostic_error:
                attempts.append({"number": 1, "capture_error": type(diagnostic_error).__name__})


def evaluate_llm_report(report: str, phase: Phase, engine: Any) -> dict[str, Any]:
    """Evaluate once; the workflow remains the only owner of routing."""
    evaluated_phase_code = phase.code
    workflow_id = engine.workflow_id
    if workflow_id is None or engine.db.workflows.lock(workflow_id) is None:
        raise ConcurrentTransitionError("Воркфлоу изменился во время оценки Supervisor")
    engine._reload_evaluation_state()
    engine._lock_runtime_fence()
    if engine.current_phase_code != evaluated_phase_code:
        engine.db.rollback()
        return _concurrent_result({"task_key": engine.task_key, "phase_code": evaluated_phase_code})
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
    configured = (engine.runtime_fence
                  if isinstance(engine.runtime_fence, (ConfiguredCliFence, StandaloneFence)) else None)
    delegation_allowed = configured is None and current_contract.delegate_agent is not None
    system = PromptBuilder.SYSTEM_PROMPT
    prompt_version = PromptBuilder.PROMPT_VERSION
    context_error: PhaseReportFormatError | None = None
    try:
        phase_context = engine._get_phase_evaluation_history(phase.code)
    except PhaseReportFormatError as exc:
        context_error = exc
        phase_context = {"reports": [], "assessments": {}}
    initial_phase_context_fingerprint = _fingerprint_contract_state(phase_context)
    previously_ids = {item_id for item_id, assessment in phase_context["assessments"].items()
                      if item_id in item_ids and assessment["covered"]}
    initial_previously_ids = set(previously_ids)
    catalog_error: ValueError | None = None
    try:
        transition_routes = {
            verdict: engine._resolve_transition(phase, verdict, group)
            for verdict in ("pass", "delegate")
        }
    except ValueError as exc:
        catalog_error = exc
        transition_routes = {}
    initial_contract_fingerprint = _contract_fingerprint(
        builder=builder,
        phase=phase,
        group=group,
        contract=current_contract,
        evaluation_items=evaluation_items,
        previously_covered_ids=previously_ids,
        transition_routes=transition_routes,
        prompt_version=prompt_version,
        delegation_allowed=delegation_allowed,
        phase_context_fingerprint=initial_phase_context_fingerprint,
    )
    fingerprint = _report_fingerprint(task_id, report, initial_contract_fingerprint)
    if configured is not None:
        fingerprint = configured.operation_fingerprint
    replayed = _replay(engine, task_id, phase_id, fingerprint)
    if replayed is not None:
        engine.db.commit()
        engine._reload_task_state()
        if not engine.task:
            return _concurrent_result(replayed)
        return replayed

    parsed_report = PhaseReport.parse(report)
    user = PromptBuilder.build_user_prompt(
        engine.task_key,
        evaluation_phase,
        parsed_report.model_dump(mode="json"),
        previous_reports=phase_context["reports"],
        previous_assessments=phase_context["assessments"],
        evaluation_items=evaluation_items,
        delegation_allowed=delegation_allowed,
    )
    evaluated_items = list(evaluation_items)

    # Do not keep a database transaction or workflow row lock open across the provider call.
    engine.db.commit()

    client: OpenAICompatibleClient | None = None
    raw: dict[str, Any] | None = None
    technical_error = False
    attempts: list[dict[str, Any]] = []
    try:
        if context_error is not None:
            raise context_error
        if catalog_error is not None:
            raise catalog_error
        if not evaluation_items:
            raise PhaseCriteriaConfigurationError()
        client = OpenAICompatibleClient()
        raw, llm = _evaluate_strict_response(
            client,
            user=user,
            evaluation_items=evaluation_items,
            phase=phase,
            attempts=attempts,
            system=system,
            response_format=(PromptBuilder.response_schema(evaluation_items, delegation_allowed=delegation_allowed)
                             if config.get_settings().OPENAI_EVALUATOR_RESPONSE_FORMAT == "json_schema" else None),
            delegation_allowed=delegation_allowed,
        )
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
        provider_diagnostic = getattr(client, "last_call_diagnostics", {})
        llm = _blocked(exc, provider_outcome=(provider_diagnostic.get("outcome")
                      if isinstance(provider_diagnostic, dict) else None))

    if engine.db.workflows.lock(workflow_id) is None:
        engine.db.rollback()
        return _concurrent_result({"task_key": engine.task_key, "phase_code": evaluated_phase_code})
    engine._reload_evaluation_state()
    engine._lock_runtime_fence()
    fresh_phase = engine.phase_map.get(evaluated_phase_code)
    if fresh_phase is None:
        engine.db.rollback()
        if engine.current_phase_code != evaluated_phase_code:
            engine._reload_task_state()
            return _concurrent_result({"task_key": engine.task_key, "phase_code": evaluated_phase_code})
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
        )
    evaluation_items = (
        builder.build_parallel_evaluation_items(group) if len(group) > 1 else builder.build_evaluation_items(phase)
    )
    item_ids = [item_id for item_id, _ in evaluation_items]
    item_text = dict(evaluation_items)
    current_delegation_allowed = configured is None and current_contract.delegate_agent is not None
    try:
        phase_context = engine._get_phase_evaluation_history(phase.code)
    except PhaseReportFormatError as exc:
        technical_error = True
        llm = _blocked(exc)
        phase_context = {"reports": [], "assessments": {}}
    phase_context_fingerprint = _fingerprint_contract_state(phase_context)
    previously_ids = {item_id for item_id, assessment in phase_context["assessments"].items()
                      if item_id in item_ids and assessment["covered"]}
    try:
        transition_routes = {
            verdict: engine._resolve_transition(phase, verdict, group)
            for verdict in ("pass", "delegate")
        }
    except ValueError as exc:
        technical_error = True
        llm = _blocked(exc)
        transition_routes = {}
    current_contract_state = _contract_fingerprint_state(
        builder=builder,
        phase=phase,
        group=group,
        contract=current_contract,
        evaluation_items=evaluation_items,
        previously_covered_ids=previously_ids,
        transition_routes=transition_routes,
        prompt_version=prompt_version,
        delegation_allowed=current_delegation_allowed,
        phase_context_fingerprint=phase_context_fingerprint,
    )
    current_contract_fingerprint = _fingerprint_contract_state(current_contract_state)
    current_snapshot_fingerprint = _contract_fingerprint(
        builder=builder,
        phase=phase,
        group=group,
        contract=current_contract,
        evaluation_items=evaluation_items,
        previously_covered_ids=initial_previously_ids,
        transition_routes=transition_routes,
        prompt_version=prompt_version,
        delegation_allowed=current_delegation_allowed,
        phase_context_fingerprint=initial_phase_context_fingerprint,
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
        return _concurrent_result({"task_key": engine.task_key, "phase_code": evaluated_phase_code})
    if engine.current_phase_code != evaluated_phase_code:
        engine.db.rollback()
        engine._reload_task_state()
        return _concurrent_result({"task_key": engine.task_key, "phase_code": evaluated_phase_code})
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
    if technical_error:
        next_phase_code = None
        next_phase_name = None
        rollback_phase_code = None
    else:
        next_phase_code, next_phase_name, rollback_phase_code = engine._resolve_transition(
            phase, verdict_key, group
        )
    if verdict_key != "pass" or technical_error:
        next_phase_code = None
        next_phase_name = None
        rollback_phase_code = None if technical_error else rollback_phase_code

    result: dict[str, Any] = {
        "verdict": VERDICT_LABELS.get(verdict_key, llm.verdict),
        "task_key": engine.task_key,
        "phase_code": phase.code,
        "phase_name": evaluation_phase.name,
        "covered": covered,
        "missing": missing,
        "blockers": blockers,
        "current_phase_code": phase.code,
        "next_phase_code": next_phase_code,
        "next_phase_name": next_phase_name,
        "rollback_phase_code": rollback_phase_code,
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
    next_phase_contract = (
        builder.build_next_contract(next_phase_code) if verdict_key == "pass" else None
    )
    if next_phase_contract is not None:
        result["next_phase_contract"] = next_phase_contract.to_dict()

    next_phase_obj = engine.phase_map.get(next_phase_code) if next_phase_code else None
    raw_evaluator = llm.raw
    try:
        diagnostic = evaluation_diagnostic(
            system=system, user=user, report=report,
            prompt_version=prompt_version, items=evaluated_items,
            attempts=attempts, client=client, technical_error=technical_error, decision=raw_evaluator,
            assessments=llm.assessments if not technical_error else {},
            aliases=PromptBuilder.item_aliases(evaluated_items),
        )
    except Exception as diagnostic_error:
        diagnostic = {"schema": "evaluator-diagnostics-v1", "availability": "capture_failed",
                      "error_type": type(diagnostic_error).__name__}
    run_data: dict[str, Any] = {
        "task_id": task_id,
        "mode_id": int(engine.task.get("mode_id") or 0),
        "cycle_number": int(engine.task.get("cycle_number") or 0),
        "phase_id": phase.id,
        "verdict": verdict_key,
        "worker_report": report,
        "covered_item_ids": covered_ids,
        "missing_item_ids": missing_ids,
        "blocker_messages": blockers,
        "next_phase_id": next_phase_obj.id if next_phase_obj else None,
        "rollback_phase_id": None,
        "replay_fingerprint": None if technical_error else fingerprint,
        "evaluation_snapshot": {
            "phase_code": phase.code,
            "phase_name": evaluation_phase.name,
            "model": client.model if client is not None else None,
            "endpoint_mode": "openai-compatible",
            "prompt_version": prompt_version,
            "contract_fingerprint": current_contract_fingerprint,
            "evaluated_contract_fingerprint": initial_contract_fingerprint,
            "contract_fingerprint_state": current_contract_state,
            "contract_snapshot": {
                **current_contract.to_dict(),
                "evaluation_items": [{"id": item_id, "text": text} for item_id, text in evaluation_items],
            },
            "covered_item_ids": covered_ids,
            "raw_evaluator": raw_evaluator,
            "advisor_assessments": llm.assessments if not technical_error else {},
            "evaluator_item_aliases": PromptBuilder.item_aliases(evaluated_items),
            "diagnostics": diagnostic,
        },
        "supervisor_response": result,
    }
    runtime_fence = getattr(engine, "runtime_fence", None)
    if isinstance(runtime_fence, ConfiguredCliFence):
        from ..application.configured_cli import prepare_history

        prepare_history(runtime_fence, run_data)
    elif isinstance(runtime_fence, StandaloneFence):
        from ..application.standalone import prepare_history as prepare_local_history

        prepare_local_history(runtime_fence, run_data)

    try:
        step_history_id = engine.db.record_step(**run_data)
        engine._record_evaluation(
            phase,
            verdict_key,
            next_phase_code,
            rollback_phase_code,
            step_history_id,
            commit=False,
        )
        if isinstance(runtime_fence, ConfiguredCliFence):
            from ..application.configured_cli import finish_history

            finish_history(engine.db, runtime_fence, step_history_id, result)
        elif isinstance(runtime_fence, StandaloneFence):
            from ..application.standalone import finish_history as finish_local_history

            finish_local_history(engine.db, runtime_fence, step_history_id, result)
        engine.db.commit()
    except IntegrityError:
        engine.db.rollback()
        if isinstance(getattr(engine, "runtime_fence", None), (ConfiguredCliFence, StandaloneFence)):
            raise
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
