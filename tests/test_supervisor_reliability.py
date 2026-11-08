"""Reliability contract for the mandatory Supervisor evaluator."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import requests
from sqlalchemy import text

from project_workflow import config
from project_workflow.application.phase_service import PhaseService
from project_workflow.domain.exceptions import ConcurrentTransitionError
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder, ResponseParser
from project_workflow.supervisor import SupervisorEngine
from tests._db_helpers import phase_by_code
from tests._report_helpers import report_json
from tests.test_configured_cli import configured as configured
from tests.test_configured_cli import enroll, step

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


def _configured_state(fixture):
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key(fixture[1]["task"], project_id=fixture[1]["namespace_id"])
        assert task is not None
        return (task.to_dict(), uow.list_phase_events(task.id),
                uow.list_step_history(task_id=task.id, limit=None))


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
def test_valid_report_is_replayed_once(configured, verdict, supervisor_llm):
    enroll(configured)
    supervisor_llm(verdict)
    fixture_chat = OpenAICompatibleClient.respond
    with patch.object(OpenAICompatibleClient, "respond", side_effect=fixture_chat) as respond:
        first_response = step(configured, report=report_json(f"report {verdict}"),
                              operation_key="replayed-report", expected_version=1)
        assert first_response.status_code == 200, first_response.text
        first = first_response.json()["result"]
        history_after_first = _configured_state(configured)
        second_response = step(configured, report=report_json(f"report {verdict}"),
                               operation_key="replayed-report", expected_version=1)
        assert second_response.status_code == 200, second_response.text
        second = second_response.json()["result"]

    assert first["verdict"] == verdict
    assert first["replayed"] is False
    assert second["verdict"] == verdict
    assert second == first
    assert respond.call_count == 1
    assert len(history_after_first[2]) == 1
    assert _configured_state(configured) == history_after_first


def test_same_report_uses_provider_again_after_prompt_version_change(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("RUN-918")
    supervisor_llm("PARTIAL")
    fixture_chat = OpenAICompatibleClient.respond

    with patch.object(OpenAICompatibleClient, "respond", side_effect=fixture_chat) as respond:
        first = engine.evaluate(report_json("same report after evaluator update"))
        monkeypatch.setattr(PromptBuilder, "PROMPT_VERSION", "supervisor-evaluator-next")
        second = engine.evaluate(report_json("same report after evaluator update"))

    assert first["replayed"] is second["replayed"] is False
    assert respond.call_count == 2
    runs = engine.db.step_history.list(task_key=engine.task_key)
    assert len(runs) == 2
    assert len({run.replay_fingerprint for run in runs}) == 2


def test_replay_does_not_return_stale_result_for_deleted_task(supervisor_llm):
    engine = SupervisorEngine("RUN-902")
    supervisor_llm("PARTIAL")
    engine.evaluate(report_json("report before deletion"))

    with (
        patch.object(engine._task_service, "get_task", return_value=None),
        patch.object(OpenAICompatibleClient, "respond", wraps=OpenAICompatibleClient.respond) as respond,
    ):
        result = engine.evaluate(report_json("report before deletion"))

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["replayed"] is False
    assert engine.task is None
    assert respond.call_count == 0


def test_same_report_is_evaluated_again_after_phase_transition(supervisor_llm):
    engine = SupervisorEngine("RUN-900")
    supervisor_llm("PASS")
    fixture_chat = OpenAICompatibleClient.respond
    with patch.object(OpenAICompatibleClient, "respond", side_effect=fixture_chat) as respond:
        first = engine.evaluate(report_json("same completion report"))
        first_phase = first["phase_code"]
        second = engine.evaluate(report_json("same completion report"))

    assert first["verdict"] == second["verdict"] == "PASS"
    assert first["replayed"] is second["replayed"] is False
    assert second["phase_code"] != first_phase
    assert respond.call_count == 2
    runs = engine.db.list_step_history(task_key=engine.task_key, limit=10)
    assert len(runs) == 2
    assert len({run["phase_id"] for run in runs}) == 2


def test_same_report_uses_provider_again_after_instruction_contract_change(supervisor_llm):
    engine = SupervisorEngine("RUN-915")
    supervisor_llm("PARTIAL")
    fixture_chat = OpenAICompatibleClient.respond
    report = "Контракт пока выполнен частично"

    with patch.object(OpenAICompatibleClient, "respond", side_effect=fixture_chat) as respond:
        first = engine.evaluate(report_json(report))
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
        second = engine.evaluate(report_json(report))

    assert first["replayed"] is False
    assert second["replayed"] is False
    assert respond.call_count == 2


def test_same_report_uses_provider_again_after_accumulated_coverage_changes():
    engine = SupervisorEngine("RUN-917")
    calls = 0

    def partial_progress(*_args, **kwargs):
        nonlocal calls
        item_ids = [item["id"] for item in json.loads(kwargs["user"])["criteria"]]
        assert len(item_ids) >= 3
        covered = item_ids[: min(calls + 1, 2)]
        calls += 1
        return {"verdict": "PARTIAL", "assessments": {
            item_id: {"covered": item_id in covered, "reason": "Проверен текущий результат",
                      "required_change": None if item_id in covered else "Предоставьте недостающий результат"}
            for item_id in item_ids}, "blockers": [], "confidence": 0.5}

    with patch.object(OpenAICompatibleClient, "respond", side_effect=partial_progress) as respond:
        first = engine.evaluate(report_json("повторяемый отчёт"))
        second = engine.evaluate(report_json("другой отчёт"))
        retried = engine.evaluate(report_json("повторяемый отчёт"))

    assert first["verdict"] == second["verdict"] == retried["verdict"] == "PARTIAL"
    assert retried["replayed"] is False
    assert respond.call_count == 3
    assert len(retried["covered"]) >= 2


def test_catalog_change_during_provider_call_fails_closed_then_retries(supervisor_llm):
    engine = SupervisorEngine("RUN-916")
    supervisor_llm("PASS")
    fixture_chat = OpenAICompatibleClient.respond
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

    with patch.object(OpenAICompatibleClient, "respond", side_effect=mutate_then_answer) as respond:
        blocked = engine.evaluate(report_json("Всё выполнено"))
        blocked_task = engine.db.tasks.get_by_id(engine.task["id"]).to_dict()
        blocked_run = engine.db.list_step_history(task_key=engine.task_key, limit=1)[0]
        blocked_history = engine.db.list_phase_events(engine.task["id"])
        retry = engine.evaluate(report_json("Всё выполнено"))

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
    assert respond.call_count == 2


def test_missing_workflow_lock_fails_before_provider(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("RUN-930")
    phase = engine._get_current_phase_obj()
    assert phase is not None
    supervisor_llm("PASS")
    monkeypatch.setattr(engine.db.workflows, "lock", lambda _workflow_id: None)

    with patch.object(OpenAICompatibleClient, "respond", wraps=OpenAICompatibleClient.respond) as respond:
        with pytest.raises(ConcurrentTransitionError, match="Воркфлоу изменился"):
            engine.evaluate_llm(report_json("Отчёт не должен дойти до evaluator"), phase)

    respond.assert_not_called()


def test_lost_workflow_lock_after_provider_returns_retryable_blocked(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("RUN-931")
    supervisor_llm("PASS")
    fixture_chat = OpenAICompatibleClient.respond
    locks = iter([object(), None])
    monkeypatch.setattr(engine.db.workflows, "lock", lambda _workflow_id: next(locks))

    with patch.object(OpenAICompatibleClient, "respond", side_effect=fixture_chat) as respond:
        result = engine.evaluate(report_json("Отчёт прошёл, но lock потерян"))

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["replayed"] is False
    assert "параллельным запуском" in result["message"] or result["blockers"]
    assert respond.call_count == 1


def test_task_phase_changed_during_provider_call_returns_retryable_blocked(supervisor_llm):
    engine = SupervisorEngine("RUN-932")
    phase = engine._get_current_phase_obj()
    next_phase = phase_by_code(engine.db, "2.REQUIREMENTS")
    assert phase is not None and next_phase is not None and next_phase.id is not None
    supervisor_llm("PASS")
    fixture_chat = OpenAICompatibleClient.respond
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

    with patch.object(OpenAICompatibleClient, "respond", side_effect=move_task_then_answer) as respond:
        result = engine.evaluate(report_json("Отчёт для уже устаревшей фазы"))

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["phase_code"] == phase.code
    assert engine.current_phase_code == next_phase.code
    assert respond.call_count == 1


def test_successful_commit_returns_concurrent_result_if_task_disappears_after_refresh(supervisor_llm):
    engine = SupervisorEngine("RUN-933")
    supervisor_llm("PARTIAL")
    fixture_chat = OpenAICompatibleClient.respond

    def hide_task_after_commit() -> None:
        engine.task = None
        engine.current_phase_code = ""

    with (
        patch.object(OpenAICompatibleClient, "respond", side_effect=fixture_chat),
        patch.object(engine, "_refresh_task_state", side_effect=hide_task_after_commit),
    ):
        result = engine.evaluate(report_json("Частичный отчёт перед потерей snapshot"))

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

    with patch.object(OpenAICompatibleClient, "respond", wraps=OpenAICompatibleClient.respond) as respond:
        result = engine.evaluate(report_json("Отчёт при повреждённом routing catalog"))

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert "Supervisor не смог проверить отчёт" in result["message"]
    respond.assert_not_called()


def test_noop_phase_save_preserves_catalog_but_new_history_context_is_reevaluated(supervisor_llm):
    engine = SupervisorEngine("RUN-919")
    supervisor_llm("PARTIAL")
    fixture_chat = OpenAICompatibleClient.respond
    report = "Контракт сохранён без изменений"

    with patch.object(OpenAICompatibleClient, "respond", side_effect=fixture_chat) as respond:
        first = engine.evaluate(report_json(report))
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
        second = engine.evaluate(report_json(report))

    assert first["replayed"] is False
    assert second["replayed"] is False
    assert respond.call_count == 2
    history = engine.db.step_history.list(task_key=engine.task_key)
    states = [run.evaluation_snapshot["contract_fingerprint_state"] for run in history]
    assert states[0]["phase_context_fingerprint"] != states[1]["phase_context_fingerprint"]
    assert {key: value for key, value in states[0].items() if key != "phase_context_fingerprint"} == {
        key: value for key, value in states[1].items() if key != "phase_context_fingerprint"
    }
    assert json.loads(respond.call_args.kwargs["user"])["previous_reports"] == [json.loads(report_json(report))]


def test_legacy_parallel_targets_do_not_block_evaluation(supervisor_llm):
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

    supervisor_llm("PARTIAL")
    result = engine.evaluate(report_json("Отчёт параллельной группы"))

    latest_run = engine.db.list_step_history(task_key="RUN-918", limit=1)[0]
    events = engine.db.list_phase_events(int(engine.task["id"]))
    assert result["verdict"] == "PARTIAL"
    assert result["current_phase_code"] == "6.SOLUTION"
    assert latest_run["replay_fingerprint"] is not None
    assert latest_run["verdict"] == "partial"
    assert not any(event["event_type"] == "rolled_back" for event in events)


@pytest.mark.parametrize(
    ("task_number", "defect"),
    [
        (921, "lowercase-verdict"), (922, "extra-field"), (923, "missing-assessments"),
        (924, "non-string-reason"), (925, "invalid-confidence"),
    ],
)
def test_invalid_evaluator_contract_uses_fail_closed_audit(task_number, defect):
    engine = SupervisorEngine(f"RUN-{task_number}")
    phase_before = engine.current_phase_code

    def invalid_response(*_args, **kwargs):
        raw = {"verdict": "PASS", "assessments": {
            item["id"]: {"covered": True, "reason": "Actual result", "required_change": None}
            for item in json.loads(kwargs["user"])["criteria"]
        }, "blockers": [], "confidence": 0.5}
        if defect == "lowercase-verdict":
            raw["verdict"] = "pass"
        elif defect == "extra-field":
            raw["extra"] = True
        elif defect == "missing-assessments":
            raw.pop("assessments")
        elif defect == "non-string-reason":
            next(iter(raw["assessments"].values()))["reason"] = 1
        else:
            raw["confidence"] = "high"
        return raw

    with patch.object(OpenAICompatibleClient, "respond", side_effect=invalid_response) as respond:
        result = engine.evaluate(report_json("Отчёт"))

    task = engine.db.tasks.get_by_id(engine.task["id"]).to_dict()
    run = engine.db.list_step_history(task_key=engine.task_key, limit=1)[0]
    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert task["status"] == "blocked"
    assert task["current_phase_code"] == phase_before
    assert run["replay_fingerprint"] is None
    respond.assert_called_once()
    assert run["evaluation_snapshot"]["advisor_assessments"] == {}
    assert run["evaluation_snapshot"]["diagnostics"]["outcome"] == "technical_failure"


def test_invalid_evaluator_contract_is_not_repaired_inside_one_evaluation(supervisor_llm):
    engine = SupervisorEngine("RUN-926")
    supervisor_llm("PASS")
    valid_chat = OpenAICompatibleClient.respond
    calls: list[dict[str, str]] = []

    def invalid_then_valid(*args, **kwargs):
        calls.append({"system": kwargs["system"], "user": kwargs["user"]})
        if len(calls) == 1:
            return {
                "verdict": "pass",
                "assessments": {
                    item["id"]: {"covered": True, "reason": "Actual result", "required_change": None}
                    for item in json.loads(kwargs["user"])["criteria"]
                },
                "blockers": [],
                "confidence": 0.5,
            }
        return valid_chat(*args, **kwargs)

    with patch.object(OpenAICompatibleClient, "respond", side_effect=invalid_then_valid):
        result = engine.evaluate(report_json("Отчёт"))

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert len(calls) == 1
    assert json.loads(calls[0]["user"])["report"] == json.loads(report_json("Отчёт"))
    assert calls[0]["system"] == PromptBuilder.SYSTEM_PROMPT
    assert "PREVIOUS RESPONSE WAS INVALID" not in calls[0]["system"]
    runs = engine.db.list_step_history(task_key=engine.task_key, limit=10)
    assert len(runs) == 1 and runs[0]["replay_fingerprint"] is None
    assert runs[0]["evaluation_snapshot"]["diagnostics"]["outcome"] == "technical_failure"


def test_invalid_evaluator_contract_stays_fail_closed_after_one_attempt():
    engine = SupervisorEngine("RUN-927")
    def invalid(*_args, **kwargs):
        return {"verdict": "pass", "assessments": {
            item["id"]: {"covered": True, "reason": "Actual result", "required_change": None}
            for item in json.loads(kwargs["user"])["criteria"]
        }, "blockers": [], "confidence": 0.5}

    with patch.object(OpenAICompatibleClient, "respond", side_effect=invalid) as respond:
        result = engine.evaluate(report_json("Отчёт"))

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert respond.call_count == 1
    runs = engine.db.list_step_history(task_key=engine.task_key, limit=10)
    assert len(runs) == 1
    assert runs[0]["replay_fingerprint"] is None


def test_retryable_provider_error_has_no_fingerprint_and_blocks_current_phase():
    engine = SupervisorEngine("RUN-910")
    with patch.object(OpenAICompatibleClient, "respond", side_effect=requests.ConnectionError("down")) as respond:
        first = engine.evaluate(report_json("same report"))
        second = engine.evaluate(report_json("same report"))

    assert first["verdict"] == second["verdict"] == "BLOCKED"
    assert first["retryable"] is second["retryable"] is True
    assert respond.call_count == 2
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
        result = engine.evaluate(report_json("same report"))

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["blockers"] == [
        "Проверяющий LLM не настроен или настроен неверно."
    ]
    post.assert_not_called()
    run = engine.db.step_history.list(task_key=engine.task_key)[0]
    assert run.replay_fingerprint is None
    assert run.evaluation_snapshot["raw_evaluator"] == {"error": "LlmConfigurationError"}


def test_successful_retry_after_provider_error_unblocks_and_transitions(supervisor_llm):
    engine = SupervisorEngine("RUN-913")
    supervisor_llm("PASS")
    successful_chat = OpenAICompatibleClient.respond
    attempts = 0

    def flaky_chat(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise requests.Timeout("provider timeout")
        return successful_chat(*args, **kwargs)

    with patch.object(OpenAICompatibleClient, "respond", side_effect=flaky_chat):
        failed = engine.evaluate(report_json("same report"))
        succeeded = engine.evaluate(report_json("same report"))

    assert failed["verdict"] == "BLOCKED"
    assert failed["retryable"] is True
    assert succeeded["verdict"] == "PASS"
    assert succeeded["replayed"] is False
    assert engine.task["status"] == "active"
    assert engine.task["current_phase_code"] == "2.REQUIREMENTS"
    runs = engine.db.step_history.list(task_key=engine.task_key)
    assert sum(run.replay_fingerprint is None for run in runs) == 1
    assert sum(run.replay_fingerprint is not None for run in runs) == 1


def test_stale_partial_replay_does_not_restore_cursor_after_task_becomes_blocked(configured, supervisor_llm):
    enroll(configured)
    supervisor_llm("PARTIAL")
    first_response = step(configured, report=report_json("reusable partial report"),
                          operation_key="original-partial", expected_version=1)
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()["result"]
    with patch.object(OpenAICompatibleClient, "respond", side_effect=requests.Timeout("provider timeout")):
        failed_response = step(configured, report=report_json("different technical failure"),
                               operation_key="technical-failure", expected_version=2)
    assert failed_response.status_code == 200, failed_response.text
    failed = failed_response.json()["result"]
    before = _configured_state(configured)
    with patch.object(
        OpenAICompatibleClient, "respond", side_effect=AssertionError("Replay cannot reevaluate"),
    ) as respond:
        response = step(configured, report=report_json("reusable partial report"),
                        operation_key="original-partial", expected_version=1)
    assert response.status_code == 200, response.text
    retried = response.json()["result"]

    assert first["verdict"] == "PARTIAL"
    assert failed["verdict"] == "BLOCKED"
    assert before[0]["status"] == "blocked"
    assert retried["verdict"] == "PARTIAL"
    assert retried == first
    assert _configured_state(configured) == before
    respond.assert_not_called()


def test_stale_blocked_replay_does_not_restore_cursor_after_partial(configured, supervisor_llm):
    enroll(configured)
    supervisor_llm("BLOCKED")
    blocked_response = step(configured, report=report_json("reusable blocked report"),
                           operation_key="original-blocked", expected_version=1)
    assert blocked_response.status_code == 200, blocked_response.text
    blocked = blocked_response.json()["result"]
    supervisor_llm("PARTIAL")
    partial_response = step(configured, report=report_json("different partial report"),
                           operation_key="new-partial", expected_version=2)
    assert partial_response.status_code == 200, partial_response.text
    partial = partial_response.json()["result"]
    before = _configured_state(configured)

    with patch.object(
        OpenAICompatibleClient, "respond", side_effect=AssertionError("Replay cannot reevaluate"),
    ) as respond:
        response = step(configured, report=report_json("reusable blocked report"),
                        operation_key="original-blocked", expected_version=1)
    assert response.status_code == 200, response.text
    replayed = response.json()["result"]

    assert blocked["verdict"] == "BLOCKED"
    assert partial["verdict"] == "PARTIAL"
    assert replayed["verdict"] == "BLOCKED"
    assert replayed == blocked
    assert before[0]["status"] == "active"
    assert _configured_state(configured) == before
    respond.assert_not_called()


def test_concurrent_change_during_resubmission_returns_retryable_block(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("RUN-916")
    supervisor_llm("PARTIAL")
    engine.evaluate(report_json("cached partial report"))
    with patch.object(OpenAICompatibleClient, "respond", side_effect=requests.Timeout("provider timeout")):
        engine.evaluate(report_json("different technical failure"))
    history_before = engine.db.list_phase_events(engine.task["id"])
    monkeypatch.setattr(engine.db.tasks, "update_if_state", lambda *_args, **_kwargs: False)

    with patch.object(OpenAICompatibleClient, "respond", wraps=OpenAICompatibleClient.respond) as respond:
        result = engine.evaluate(report_json("cached partial report"))

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert result["replayed"] is False
    assert engine.task["status"] == "blocked"
    assert engine.db.list_phase_events(engine.task["id"]) == history_before
    assert respond.call_count == 1


def test_recorded_evaluation_invalidates_supervisor_context_cache(supervisor_llm):
    engine = SupervisorEngine("RUN-909")
    before = engine.get_full_context()
    assert engine.get_full_context() is before
    supervisor_llm("PARTIAL")

    engine.evaluate(report_json("cache invalidation report"))

    after = engine.get_full_context()
    assert after is not before


def test_concurrent_state_change_rolls_back_run_and_history(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("RUN-911")
    original_task = dict(engine.task)
    original_events = engine.db.list_phase_events(engine.task["id"])
    supervisor_llm("PASS")
    monkeypatch.setattr(engine.db.tasks, "update_if_state", lambda *_args, **_kwargs: False)

    result = engine.evaluate(report_json("concurrent report"))

    assert result["verdict"] == "BLOCKED"
    assert result["retryable"] is True
    assert engine.db.list_step_history(task_key=engine.task_key, limit=10) == []
    assert engine.db.list_phase_events(engine.task["id"]) == original_events
    assert engine.task == original_task


def test_audit_snapshot_contains_contract_and_provider_metadata(supervisor_llm):
    engine = SupervisorEngine("RUN-912")
    supervisor_llm("PARTIAL")
    engine.evaluate(report_json("audited report"))

    run = engine.db.step_history.list(task_key=engine.task_key)[0]
    snapshot = run.evaluation_snapshot
    assert snapshot["model"]
    assert snapshot["endpoint_mode"] == "openai-compatible"
    assert snapshot["prompt_version"] == PromptBuilder.PROMPT_VERSION
    assert snapshot["contract_snapshot"]["evaluation_items"]
    assert snapshot["raw_evaluator"]["verdict"] == "PARTIAL"
