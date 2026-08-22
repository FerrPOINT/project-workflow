"""Reliability contract for the mandatory Supervisor evaluator."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from project_workflow.infrastructure.llm import OpenAICompatibleClient, ResponseParser
from project_workflow.supervisor import SupervisorEngine

pytestmark = [pytest.mark.supervisor]


def _wire(verdict: str, covered: list[str], missing: list[str], blockers: list[str] | None = None):
    return {
        "verdict": verdict,
        "covered": covered,
        "missing": missing,
        "blockers": blockers or [],
        "message": None,
        "confidence": None,
    }


class TestStrictEvaluatorContract:
    @pytest.mark.parametrize("field", ["verdict", "covered", "missing", "blockers"])
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

    def test_empty_checklist_pass_and_soft_fields(self):
        verdict = ResponseParser.parse(_wire("PASS", [], []), required_item_ids=[])
        assert verdict.verdict == "PASS"
        assert verdict.message == ""
        assert verdict.confidence == 0.5


@pytest.mark.parametrize("verdict", ["PASS", "PARTIAL", "BLOCKED"])
def test_valid_report_is_replayed_once(verdict, supervisor_llm):
    engine = SupervisorEngine(f"TASK-90{['PASS', 'PARTIAL', 'BLOCKED'].index(verdict)}")
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


def test_retryable_provider_error_has_no_fingerprint_or_transition():
    engine = SupervisorEngine("TASK-910")
    original_task = dict(engine.task)
    with patch.object(OpenAICompatibleClient, "chat", side_effect=requests.ConnectionError("down")) as chat:
        first = engine.evaluate("same report")
        second = engine.evaluate("same report")

    assert first["verdict"] == second["verdict"] == "BLOCKED"
    assert first["retryable"] is second["retryable"] is True
    assert chat.call_count == 2
    runs = engine.db.supervisor_runs.list(task_key=engine.task_key)
    assert len(runs) == 2
    assert all(run.report_fingerprint is None for run in runs)
    assert engine.db.get_task_history(engine.task["id"]) == []
    assert engine.task == original_task


def test_concurrent_state_change_rolls_back_run_and_history(supervisor_llm, monkeypatch):
    engine = SupervisorEngine("TASK-911")
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
    engine = SupervisorEngine("TASK-912")
    supervisor_llm("PARTIAL")
    engine.evaluate("audited report")

    run = engine.db.supervisor_runs.list(task_key=engine.task_key)[0]
    snapshot = run.context_snapshot
    assert snapshot["model"]
    assert snapshot["endpoint_mode"] == "openai-compatible"
    assert snapshot["prompt_version"] == "supervisor-evaluator-v5"
    assert snapshot["contract_snapshot"]["evaluation_items"]
    assert snapshot["raw_evaluator"]["verdict"] == "PARTIAL"
