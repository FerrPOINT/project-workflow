"""Reliability contract for the mandatory Supervisor evaluator."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests
from sqlalchemy import text

from project_workflow import config
from project_workflow.application.phase_service import PhaseService
from project_workflow.domain.exceptions import ConcurrentTransitionError
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder, ResponseParser
from project_workflow.supervisor import SupervisorEngine
from tests._db_helpers import phase_by_code

pytestmark = [pytest.mark.supervisor]


def _wire(verdict: str, covered: list[str], missing: list[str], blockers: list[str] | None = None):
    return {
        "verdict": verdict,
        "covered": covered,
        "missing": missing,
        "blockers": blockers or [],
        "message": "Результат проверки",
        "confidence": 0.5,
    }


class TestStrictEvaluatorContract:
    @pytest.mark.parametrize("field", ["verdict", "covered", "missing", "blockers", "message", "confidence"])
    def test_control_fields_are_required(self, field):
        raw = _wire("PASS", ["phase:check:1"], [], [])
        raw.pop(field)
        with pytest.raises(ValueError):
            ResponseParser.parse(raw, required_item_ids=["phase:check:1"])

    @pytest.mark.parametrize(
        "raw",
        [
            _wire("PASS", ["unknown"], []),
            _wire("PASS", ["phase:check:1", "phase:check:1"], []),
            _wire("PARTIAL", ["phase:check:1"], ["phase:check:1"]),
            _wire("PASS", [], ["phase:check:1"]),
        ],
    )
    def test_unknown_duplicate_overlap_and_incomplete_pass_are_rejected(self, raw):
        with pytest.raises(ValueError):
            ResponseParser.parse(raw, required_item_ids=["phase:check:1"])

    def test_pass_does_not_repair_previously_covered_ids_from_missing(self):
        with pytest.raises(ValueError, match="PASS requires full coverage"):
            ResponseParser.parse(
                _wire("PASS", ["phase:evidence:2"], ["phase:check:1"]),
                required_item_ids=["phase:check:1", "phase:evidence:2"],
            )

    def test_empty_checklist_pass_with_required_fields(self):
        verdict = ResponseParser.parse(_wire("PASS", [], []), required_item_ids=[])
        assert verdict.verdict == "PASS"
        assert verdict.message == "Результат проверки"
        assert verdict.confidence == 0.5


@pytest.mark.parametrize("verdict", ["PARTIAL", "BLOCKED"])
def test_valid_report_is_replayed_once(verdict, supervisor_llm):
    engine = SupervisorEngine(f"RUN-90{['PASS', 'PARTIAL', 'BLOCKED'].index(verdict)}")
    supervisor_llm(verdict)
    fixture_chat = OpenAICompatibleClient.chat
    with patch.object(OpenAICompatibleClient, "chat", side_effect=fixture_chat) as chat:
        first = engine.evaluate(f"report {verdict}")
        history_after_first = engine.db.list_phase_events(engine.task["id"])
        second = engine.evaluate(f"  REPORT   {verdict}! ")

    assert first["verdict"] == verdict
    assert first["replayed"] is False
    assert second["verdict"] == verdict
    assert second["replayed"] is True
    assert chat.call_count == 1
    assert len(engine.db.list_step_history(task_key=engine.task_key, limit=10)) == 1
    assert engine.db.list_phase_events(engine.task["id"]) == history_after_first


def test_same_report_uses_provider_again_after_prompt_version_change(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("RUN-918")
    supervisor_llm("PARTIAL")
    fixture_chat = OpenAICompatibleClient.chat

    with patch.object(OpenAICompatibleClient, "chat", side_effect=fixture_chat) as chat:
        first = engine.evaluate("same report after evaluator update")
        monkeypatch.setattr(PromptBuilder, "PROMPT_VERSION", "supervisor-evaluator-next")
        second = engine.evaluate("same report after evaluator update")

    assert first["replayed"] is second["replayed"] is False
    assert chat.call_count == 2
    runs = engine.db.step_history.list(task_key=engine.task_key)
    assert len(runs) == 2
    assert len({run.replay_fingerprint for run in runs}) == 2


def test_replay_does_not_return_stale_result_for_deleted_task(supervisor_llm):
    engine = SupervisorEngine("RUN-902")
    supervisor_llm("PARTIAL")
    engine.evaluate("report before deletion")

    def remove_task_from_state() -> None:
        engine.task = None
        engine.current_phase_code = ""

    with (
        patch.object(engine, "_reload_task_state", side_effect=remove_task_from_state),
        patch.object(OpenAICompatibleClient, "chat", wraps=OpenAICompatibleClient.chat) as chat,
    ):
        result = engine.evaluate("report before deletion")

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["replayed"] is False
    assert engine.task is None
    assert chat.call_count == 0


def test_same_report_is_evaluated_again_after_phase_transition(supervisor_llm):
    engine = SupervisorEngine("RUN-900")
    supervisor_llm("PASS")
    fixture_chat = OpenAICompatibleClient.chat
    with patch.object(OpenAICompatibleClient, "chat", side_effect=fixture_chat) as chat:
        first = engine.evaluate("same completion report")
        first_phase = first["phase_code"]
        second = engine.evaluate("same completion report")

    assert first["verdict"] == second["verdict"] == "PASS"
    assert first["replayed"] is second["replayed"] is False
    assert second["phase_code"] != first_phase
    assert chat.call_count == 2
    runs = engine.db.list_step_history(task_key=engine.task_key, limit=10)
    assert len(runs) == 2
    assert len({run["phase_id"] for run in runs}) == 2


def test_same_report_uses_provider_again_after_instruction_contract_change(supervisor_llm):
    engine = SupervisorEngine("RUN-915")
    supervisor_llm("PARTIAL")
    fixture_chat = OpenAICompatibleClient.chat
    report = "Контракт пока выполнен частично"

    with patch.object(OpenAICompatibleClient, "chat", side_effect=fixture_chat) as chat:
        first = engine.evaluate(report)
        phase = engine._get_current_phase_obj()
        assert phase is not None and phase.id is not None
        updated = [
            {
                "id": instruction.id,
                "description": instruction.step,
                "execution_type": instruction.execution_type,
                "skills": instruction.skills,
            }
            for instruction in phase.instructions
        ]
        updated.append(
            {"id": None, "description": "Новая обязательная инструкция", "execution_type": "sync", "skills": []}
        )
        PhaseService(engine.db).update_phase_detail(phase.id, {"instructions": updated})
        second = engine.evaluate(report)

    assert first["replayed"] is False
    assert second["replayed"] is False
    assert chat.call_count == 2


def test_same_report_uses_provider_again_after_accumulated_coverage_changes():
    engine = SupervisorEngine("RUN-917")
    calls = 0

    def partial_progress(*_args, **kwargs):
        nonlocal calls
        item_ids = [
            line.strip()[5:].split('" — ', 1)[0]
            for line in str(kwargs.get("user", "")).splitlines()
            if line.strip().startswith('ID: "') and '" — ' in line.strip()
        ]
        assert len(item_ids) >= 3
        covered = item_ids[: min(calls + 1, 2)]
        calls += 1
        return _wire(
            "PARTIAL",
            covered,
            [item_id for item_id in item_ids if item_id not in covered],
        )

    with patch.object(OpenAICompatibleClient, "chat", side_effect=partial_progress) as chat:
        first = engine.evaluate("повторяемый отчёт")
        second = engine.evaluate("другой отчёт")
        retried = engine.evaluate("повторяемый отчёт")

    assert first["verdict"] == second["verdict"] == retried["verdict"] == "PARTIAL"
    assert retried["replayed"] is False
    assert chat.call_count == 3
    assert len(retried["covered"]) >= 2


def test_catalog_change_during_provider_call_fails_closed_then_retries(supervisor_llm):
    engine = SupervisorEngine("RUN-916")
    supervisor_llm("PASS")
    fixture_chat = OpenAICompatibleClient.chat
    mutated = False

    def mutate_then_answer(*args, **kwargs):
        nonlocal mutated
        if not mutated:
            mutated = True
            phase = engine._get_current_phase_obj()
            assert phase is not None and phase.id is not None
            checks = [{"id": item.id, "description": item.description} for item in phase.checks]
            checks.append({"id": None, "description": "Проверка, добавленная конкурентно"})
            PhaseService(engine.db).update_phase_detail(phase.id, {"checks": checks})
        return fixture_chat(*args, **kwargs)

    with patch.object(OpenAICompatibleClient, "chat", side_effect=mutate_then_answer) as chat:
        blocked = engine.evaluate("Всё выполнено")
        blocked_task = engine.db.tasks.get_by_id(engine.task["id"]).to_dict()
        blocked_run = engine.db.list_step_history(task_key=engine.task_key, limit=1)[0]
        blocked_history = engine.db.list_phase_events(engine.task["id"])
        retry = engine.evaluate("Всё выполнено")

    assert blocked["verdict"] == "BLOCKED"
    assert blocked["retryable"] is True
    assert blocked["current_phase_code"] == blocked["phase_code"]
    assert blocked_task["status"] == "blocked"
    assert blocked_task["current_phase_code"] == blocked["phase_code"]
    assert blocked_run["verdict"] == "blocked"
    assert blocked_run["replay_fingerprint"] is None
    assert blocked_history[-1]["event_type"] == "blocked"
    assert retry["verdict"] == "PASS"
    assert retry["replayed"] is False
    assert chat.call_count == 2


def test_missing_workflow_lock_fails_before_provider(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("RUN-930")
    phase = engine._get_current_phase_obj()
    assert phase is not None
    supervisor_llm("PASS")
    monkeypatch.setattr(engine.db.workflows, "lock", lambda _workflow_id: None)

    with patch.object(OpenAICompatibleClient, "chat", wraps=OpenAICompatibleClient.chat) as chat:
        with pytest.raises(ConcurrentTransitionError, match="Воркфлоу изменился"):
            engine.evaluate_llm("Отчёт не должен дойти до evaluator", phase)

    chat.assert_not_called()


def test_lost_workflow_lock_after_provider_returns_retryable_blocked(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("RUN-931")
    supervisor_llm("PASS")
    fixture_chat = OpenAICompatibleClient.chat
    locks = iter([object(), None])
    monkeypatch.setattr(engine.db.workflows, "lock", lambda _workflow_id: next(locks))

    with patch.object(OpenAICompatibleClient, "chat", side_effect=fixture_chat) as chat:
        result = engine.evaluate("Отчёт прошёл, но lock потерян")

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["replayed"] is False
    assert "параллельным запуском" in result["message"] or result["blockers"]
    assert chat.call_count == 1


def test_task_phase_changed_during_provider_call_returns_retryable_blocked(supervisor_llm):
    engine = SupervisorEngine("RUN-932")
    phase = engine._get_current_phase_obj()
    next_phase = phase_by_code(engine.db, "2.REQUIREMENTS")
    assert phase is not None and next_phase is not None and next_phase.id is not None
    supervisor_llm("PASS")
    fixture_chat = OpenAICompatibleClient.chat
    moved = False

    def move_task_then_answer(*args, **kwargs):
        nonlocal moved
        if not moved:
            moved = True
            engine.db.tasks.update(
                engine.task["id"],
                {"current_phase_id": next_phase.id, "status": "active"},
            )
            engine.db.commit()
        return fixture_chat(*args, **kwargs)

    with patch.object(OpenAICompatibleClient, "chat", side_effect=move_task_then_answer) as chat:
        result = engine.evaluate("Отчёт для уже устаревшей фазы")

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["phase_code"] == phase.code
    assert engine.current_phase_code == next_phase.code
    assert chat.call_count == 1


def test_successful_commit_returns_concurrent_result_if_task_disappears_after_refresh(supervisor_llm):
    engine = SupervisorEngine("RUN-933")
    supervisor_llm("PARTIAL")
    fixture_chat = OpenAICompatibleClient.chat

    def hide_task_after_commit() -> None:
        engine.task = None
        engine.current_phase_code = ""

    with (
        patch.object(OpenAICompatibleClient, "chat", side_effect=fixture_chat),
        patch.object(engine, "_refresh_task_state", side_effect=hide_task_after_commit),
    ):
        result = engine.evaluate("Частичный отчёт перед потерей snapshot")

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["replayed"] is False


def test_transition_catalog_error_is_recorded_as_retryable_blocker(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("RUN-934")
    supervisor_llm("PASS")
    monkeypatch.setattr(
        engine,
        "_resolve_transition",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("broken transition graph")),
    )

    with patch.object(OpenAICompatibleClient, "chat", wraps=OpenAICompatibleClient.chat) as chat:
        result = engine.evaluate("Отчёт при повреждённом routing catalog")

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert "Supervisor не смог проверить отчёт" in result["message"]
    chat.assert_not_called()


def test_same_report_replays_after_noop_phase_aggregate_save(supervisor_llm):
    engine = SupervisorEngine("RUN-919")
    supervisor_llm("PARTIAL")
    fixture_chat = OpenAICompatibleClient.chat
    report = "Контракт сохранён без изменений"

    with patch.object(OpenAICompatibleClient, "chat", side_effect=fixture_chat) as chat:
        first = engine.evaluate(report)
        phase = engine._get_current_phase_obj()
        assert phase is not None and phase.id is not None
        PhaseService(engine.db).update_phase_detail(
            phase.id,
            {
                "instructions": [
                    {
                        "id": item.id,
                        "description": item.step,
                        "execution_type": item.execution_type,
                        "skills": item.skills,
                    }
                    for item in phase.instructions
                ],
                "checks": [
                    {"id": item.id, "description": item.description}
                    for item in phase.checks
                ],
                "evidence": [
                    {"id": item.id, "description": item.item}
                    for item in phase.evidence
                ],
            },
        )
        second = engine.evaluate(report)

    assert first["replayed"] is False
    assert second["replayed"] is True
    assert chat.call_count == 1


def test_inconsistent_parallel_rollback_targets_fail_closed_without_provider_call():
    engine = SupervisorEngine("RUN-918")
    solution = phase_by_code(engine.db, "6.SOLUTION")
    test_plan = phase_by_code(engine.db, "6.TEST_PLAN")
    different_target = phase_by_code(engine.db, "4.START")
    assert solution.id is not None and test_plan.id is not None and different_target.id is not None
    engine.db.tasks.update(
        int(engine.task["id"]),
        {"current_phase_id": solution.id, "status": "active"},
    )
    engine.db.session.execute(
        text("UPDATE phases SET rollback_target_phase_id = :target WHERE id = :phase_id"),
        {"target": different_target.id, "phase_id": test_plan.id},
    )
    engine.db.commit()
    engine._reload_evaluation_state()

    with patch.object(OpenAICompatibleClient, "chat") as chat:
        result = engine.evaluate("Отчёт не должен уйти провайдеру")

    latest_run = engine.db.list_step_history(task_key="RUN-918", limit=1)[0]
    events = engine.db.list_phase_events(int(engine.task["id"]))
    assert chat.call_count == 0
    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["current_phase_code"] == "6.SOLUTION"
    assert latest_run["replay_fingerprint"] is None
    assert latest_run["verdict"] == "blocked"
    assert events[-1]["event_type"] == "blocked"


@pytest.mark.parametrize(
    ("task_number", "invalid_response"),
    [
        (921, {"verdict": "pass", "covered": [], "missing": [], "blockers": [], "message": "ok", "confidence": 0.5}),
        (
            922,
            {
                "verdict": "PASS", "covered": [], "missing": [], "blockers": [],
                "message": "ok", "confidence": 0.5, "extra": True,
            },
        ),
        (923, {"verdict": "PASS", "covered": [], "missing": [], "blockers": [], "confidence": 0.5}),
        (924, {"verdict": "PASS", "covered": [], "missing": [], "blockers": [], "message": 1, "confidence": 0.5}),
        (925, {"verdict": "PASS", "covered": [], "missing": [], "blockers": [], "message": "ok", "confidence": "high"}),
    ],
)
def test_invalid_evaluator_contract_uses_fail_closed_audit(task_number, invalid_response):
    engine = SupervisorEngine(f"RUN-{task_number}")
    phase_before = engine.current_phase_code

    with patch.object(OpenAICompatibleClient, "chat", return_value=invalid_response):
        result = engine.evaluate("Отчёт")

    task = engine.db.tasks.get_by_id(engine.task["id"]).to_dict()
    run = engine.db.list_step_history(task_key=engine.task_key, limit=1)[0]
    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert task["status"] == "blocked"
    assert task["current_phase_code"] == phase_before
    assert run["replay_fingerprint"] is None


def test_retryable_provider_error_has_no_fingerprint_and_blocks_current_phase():
    engine = SupervisorEngine("RUN-910")
    with patch.object(OpenAICompatibleClient, "chat", side_effect=requests.ConnectionError("down")) as chat:
        first = engine.evaluate("same report")
        second = engine.evaluate("same report")

    assert first["verdict"] == second["verdict"] == "BLOCKED"
    assert first["retryable"] is second["retryable"] is True
    assert chat.call_count == 2
    runs = engine.db.step_history.list(task_key=engine.task_key)
    assert len(runs) == 2
    assert all(run.replay_fingerprint is None for run in runs)
    assert all(run.evaluation_snapshot["raw_evaluator"] == {"error": "ConnectionError"} for run in runs)
    assert [item["event_type"] for item in engine.db.list_phase_events(engine.task["id"])] == [
        "entered",
        "blocked",
        "blocked",
    ]
    assert engine.task["status"] == "blocked"


def test_missing_openrouter_key_blocks_locally_without_network(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    config.get_settings.cache_clear()
    engine = SupervisorEngine("RUN-911")

    with patch("project_workflow.infrastructure.llm.requests.post") as post:
        result = engine.evaluate("same report")

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["blockers"] == [
        "Проверяющий LLM не настроен: для OpenRouter требуется OPENAI_API_KEY."
    ]
    post.assert_not_called()
    run = engine.db.step_history.list(task_key=engine.task_key)[0]
    assert run.replay_fingerprint is None
    assert run.evaluation_snapshot["raw_evaluator"] == {"error": "LlmConfigurationError"}


def test_successful_retry_after_provider_error_unblocks_and_transitions(supervisor_llm):
    engine = SupervisorEngine("RUN-913")
    supervisor_llm("PASS")
    successful_chat = OpenAICompatibleClient.chat
    attempts = 0

    def flaky_chat(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise requests.Timeout("provider timeout")
        return successful_chat(*args, **kwargs)

    with patch.object(OpenAICompatibleClient, "chat", side_effect=flaky_chat):
        failed = engine.evaluate("same report")
        succeeded = engine.evaluate("same report")

    assert failed["verdict"] == "BLOCKED"
    assert failed["retryable"] is True
    assert succeeded["verdict"] == "PASS"
    assert succeeded["replayed"] is False
    assert engine.task["status"] == "active"
    assert engine.task["current_phase_code"] == "2.REQUIREMENTS"
    runs = engine.db.step_history.list(task_key=engine.task_key)
    assert sum(run.replay_fingerprint is None for run in runs) == 1
    assert sum(run.replay_fingerprint is not None for run in runs) == 1


def test_stale_partial_replay_restores_cached_success_after_task_becomes_blocked(supervisor_llm):
    engine = SupervisorEngine("RUN-914")
    supervisor_llm("PARTIAL")
    successful_chat = OpenAICompatibleClient.chat

    first = engine.evaluate("reusable partial report")
    with patch.object(OpenAICompatibleClient, "chat", side_effect=requests.Timeout("provider timeout")):
        failed = engine.evaluate("different technical failure")
    with patch.object(OpenAICompatibleClient, "chat", side_effect=successful_chat) as chat:
        retried = engine.evaluate("reusable partial report")

    assert first["verdict"] == "PARTIAL"
    assert failed["verdict"] == "BLOCKED"
    assert engine.task["status"] == "active"
    assert retried["verdict"] == "PARTIAL"
    assert retried["replayed"] is True
    assert chat.call_count == 0


def test_stale_blocked_replay_restores_cached_block_after_partial(supervisor_llm):
    engine = SupervisorEngine("RUN-915")
    supervisor_llm("BLOCKED")
    blocked = engine.evaluate("reusable blocked report")
    supervisor_llm("PARTIAL")
    partial = engine.evaluate("different partial report")

    with patch.object(OpenAICompatibleClient, "chat", wraps=OpenAICompatibleClient.chat) as chat:
        replayed = engine.evaluate("reusable blocked report")

    assert blocked["verdict"] == "BLOCKED"
    assert partial["verdict"] == "PARTIAL"
    assert replayed["verdict"] == "BLOCKED"
    assert replayed["replayed"] is True
    assert engine.task["status"] == "blocked"
    assert chat.call_count == 0


def test_concurrent_change_during_stale_replay_returns_retryable_block(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("RUN-916")
    supervisor_llm("PARTIAL")
    engine.evaluate("cached partial report")
    with patch.object(OpenAICompatibleClient, "chat", side_effect=requests.Timeout("provider timeout")):
        engine.evaluate("different technical failure")
    history_before = engine.db.list_phase_events(engine.task["id"])
    monkeypatch.setattr(engine.db.tasks, "update_if_state", lambda *_args, **_kwargs: False)

    with patch.object(OpenAICompatibleClient, "chat", wraps=OpenAICompatibleClient.chat) as chat:
        result = engine.evaluate("cached partial report")

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["replayed"] is False
    assert engine.task["status"] == "blocked"
    assert engine.db.list_phase_events(engine.task["id"]) == history_before
    assert chat.call_count == 0


def test_recorded_evaluation_invalidates_supervisor_context_cache(supervisor_llm):
    engine = SupervisorEngine("RUN-909")
    before = engine.get_full_context()
    assert engine.get_full_context() is before
    supervisor_llm("PARTIAL")

    engine.evaluate("cache invalidation report")

    after = engine.get_full_context()
    assert after is not before


def test_concurrent_state_change_rolls_back_run_and_history(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("RUN-911")
    original_task = dict(engine.task)
    original_events = engine.db.list_phase_events(engine.task["id"])
    supervisor_llm("PASS")
    monkeypatch.setattr(engine.db.tasks, "update_if_state", lambda *_args, **_kwargs: False)

    result = engine.evaluate("concurrent report")

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert engine.db.list_step_history(task_key=engine.task_key, limit=10) == []
    assert engine.db.list_phase_events(engine.task["id"]) == original_events
    assert engine.task == original_task


def test_audit_snapshot_contains_contract_and_provider_metadata(supervisor_llm):
    engine = SupervisorEngine("RUN-912")
    supervisor_llm("PARTIAL")
    engine.evaluate("audited report")

    run = engine.db.step_history.list(task_key=engine.task_key)[0]
    snapshot = run.evaluation_snapshot
    assert snapshot["model"]
    assert snapshot["endpoint_mode"] == "openai-compatible"
    assert snapshot["prompt_version"] == "supervisor-evaluator-v7"
    assert snapshot["contract_snapshot"]["evaluation_items"]
    assert snapshot["raw_evaluator"]["verdict"] == "PARTIAL"
