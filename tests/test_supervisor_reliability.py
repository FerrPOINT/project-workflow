"""Reliability contract for the mandatory Supervisor evaluator."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from project_workflow import config
from project_workflow.application.phase_service import PhaseService
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder, ResponseParser
from project_workflow.supervisor import SupervisorEngine

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

    def test_previous_coverage_completes_pass(self):
        verdict = ResponseParser.parse(
            _wire("PASS", ["phase:evidence:2"], ["phase:check:1"]),
            required_item_ids=["phase:check:1", "phase:evidence:2"],
            previously_covered_ids={"phase:check:1"},
        )
        assert verdict.covered == ["phase:check:1", "phase:evidence:2"]
        assert verdict.missing == []

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
        history_after_first = engine.db.get_task_history(engine.task["id"])
        second = engine.evaluate(f"  REPORT   {verdict}! ")

    assert first["verdict"] == verdict
    assert first["replayed"] is False
    assert second["verdict"] == verdict
    assert second["replayed"] is True
    assert chat.call_count == 1
    assert len(engine.db.get_supervisor_runs(task_key=engine.task_key, limit=10)) == 1
    assert engine.db.get_task_history(engine.task["id"]) == history_after_first


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
    runs = engine.db.supervisor_runs.list(task_key=engine.task_key)
    assert len(runs) == 2
    assert len({run.report_fingerprint for run in runs}) == 2


def test_replay_does_not_return_stale_result_for_deleted_task(supervisor_llm):
    engine = SupervisorEngine("RUN-902")
    supervisor_llm("PARTIAL")
    engine.evaluate("report before deletion")

    def remove_task_from_state() -> None:
        engine.task = None
        engine.current_phase = ""

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
        first_phase = first["phase"]
        second = engine.evaluate("same completion report")

    assert first["verdict"] == second["verdict"] == "PASS"
    assert first["replayed"] is second["replayed"] is False
    assert second["phase"] != first_phase
    assert chat.call_count == 2
    runs = engine.db.get_supervisor_runs(task_key=engine.task_key, limit=10)
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
                "description": instruction.step,
                "execution_type": instruction.execution_type,
                "skills": instruction.skills,
            }
            for instruction in phase.instructions
        ]
        updated.append({"description": "Новая обязательная инструкция", "execution_type": "sync", "skills": []})
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
        covered = [item_ids[calls]] if calls < 2 else []
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
            checks = [{"description": item.description} for item in phase.checks]
            checks.append({"description": "Проверка, добавленная конкурентно"})
            PhaseService(engine.db).update_phase_detail(phase.id, {"checks": checks})
        return fixture_chat(*args, **kwargs)

    with patch.object(OpenAICompatibleClient, "chat", side_effect=mutate_then_answer) as chat:
        blocked = engine.evaluate("Всё выполнено")
        blocked_task = engine.db.tasks.get_by_id(engine.task["id"]).to_dict()
        blocked_run = engine.db.get_supervisor_runs(task_key=engine.task_key, limit=1)[0]
        blocked_history = engine.db.get_task_history(engine.task["id"])
        retry = engine.evaluate("Всё выполнено")

    assert blocked["verdict"] == "BLOCKED"
    assert blocked["retryable"] is True
    assert blocked["current_phase"] == blocked["phase"]
    assert blocked_task["status"] == "blocked"
    assert blocked_task["current_phase"] == blocked["phase"]
    assert blocked_run["verdict"] == "blocked"
    assert blocked_run["report_fingerprint"] is None
    assert blocked_history[-1]["status"] == "blocked"
    assert retry["verdict"] == "PASS"
    assert retry["replayed"] is False
    assert chat.call_count == 2


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
    phase_before = engine.current_phase

    with patch.object(OpenAICompatibleClient, "chat", return_value=invalid_response):
        result = engine.evaluate("Отчёт")

    task = engine.db.tasks.get_by_id(engine.task["id"]).to_dict()
    run = engine.db.get_supervisor_runs(task_key=engine.task_key, limit=1)[0]
    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert task["status"] == "blocked"
    assert task["current_phase"] == phase_before
    assert run["report_fingerprint"] is None


def test_retryable_provider_error_has_no_fingerprint_and_blocks_current_phase():
    engine = SupervisorEngine("RUN-910")
    with patch.object(OpenAICompatibleClient, "chat", side_effect=requests.ConnectionError("down")) as chat:
        first = engine.evaluate("same report")
        second = engine.evaluate("same report")

    assert first["verdict"] == second["verdict"] == "BLOCKED"
    assert first["retryable"] is second["retryable"] is True
    assert chat.call_count == 2
    runs = engine.db.supervisor_runs.list(task_key=engine.task_key)
    assert len(runs) == 2
    assert all(run.report_fingerprint is None for run in runs)
    assert all(run.context_snapshot["raw_evaluator"] == {"error": "ConnectionError"} for run in runs)
    assert [item["status"] for item in engine.db.get_task_history(engine.task["id"])] == ["blocked"]
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
    run = engine.db.supervisor_runs.list(task_key=engine.task_key)[0]
    assert run.report_fingerprint is None
    assert run.context_snapshot["raw_evaluator"] == {"error": "LlmConfigurationError"}


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
    assert engine.task["current_phase"] == "2.REQUIREMENTS"
    runs = engine.db.supervisor_runs.list(task_key=engine.task_key)
    assert sum(run.report_fingerprint is None for run in runs) == 1
    assert sum(run.report_fingerprint is not None for run in runs) == 1


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
    history_before = engine.db.get_task_history(engine.task["id"])
    monkeypatch.setattr(engine.db.tasks, "update_if_state", lambda *_args, **_kwargs: False)

    with patch.object(OpenAICompatibleClient, "chat", wraps=OpenAICompatibleClient.chat) as chat:
        result = engine.evaluate("cached partial report")

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["replayed"] is False
    assert engine.task["status"] == "blocked"
    assert engine.db.get_task_history(engine.task["id"]) == history_before
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
    supervisor_llm("PASS")
    monkeypatch.setattr(engine.db.tasks, "update_if_state", lambda *_args, **_kwargs: False)

    result = engine.evaluate("concurrent report")

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert engine.db.get_supervisor_runs(task_key=engine.task_key, limit=10) == []
    assert engine.db.get_task_history(engine.task["id"]) == []
    assert engine.task == original_task


def test_audit_snapshot_contains_contract_and_provider_metadata(supervisor_llm):
    engine = SupervisorEngine("RUN-912")
    supervisor_llm("PARTIAL")
    engine.evaluate("audited report")

    run = engine.db.supervisor_runs.list(task_key=engine.task_key)[0]
    snapshot = run.context_snapshot
    assert snapshot["model"]
    assert snapshot["endpoint_mode"] == "openai-compatible"
    assert snapshot["prompt_version"] == "supervisor-evaluator-v7"
    assert snapshot["contract_snapshot"]["evaluation_items"]
    assert snapshot["raw_evaluator"]["verdict"] == "PARTIAL"
