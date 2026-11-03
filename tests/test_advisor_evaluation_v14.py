"""The private assessment contract never replaces public receipts or authorization."""

import json
from unittest.mock import Mock

import pytest

from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder
from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.diagnostics import history_diagnostic
from tests._report_helpers import report_json

pytestmark = pytest.mark.supervisor


def test_private_assessments_are_saved_beside_canonical_public_response(supervisor_llm, monkeypatch):
    supervisor_llm("PARTIAL")
    provider = Mock(side_effect=OpenAICompatibleClient.chat)
    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)
    engine = SupervisorEngine("RUN-9411")
    result = engine.evaluate(report_json("The required result has not been prepared."))
    assert result["verdict"] == "PARTIAL" and not result["retryable"]
    assert "Test Supervisor criterion" in result["message"]
    entry = engine.db.step_history.list(task_key=engine.task_key)[0]
    snapshot = entry.evaluation_snapshot
    assert set(snapshot["raw_evaluator"]) == {
        "verdict", "covered", "missing", "blockers", "message", "confidence",
    }
    assert snapshot["advisor_assessments"]
    aliases = snapshot["evaluator_item_aliases"]
    assert set(aliases.values()) == set(snapshot["advisor_assessments"])
    assert all(value["covered"] is False and value["reason"]
               for value in snapshot["advisor_assessments"].values())
    assert snapshot["diagnostics"]["attempts"][0]["response"]["assessments"]
    assert all(internal_id not in provider.call_args.kwargs["user"] for internal_id in aliases.values())
    diagnostic = history_diagnostic(entry.worker_report, snapshot)
    assert all(item["reason"] for item in diagnostic["criteria"])
    assert diagnostic["decision"]["verdict"] == "PARTIAL"


@pytest.mark.parametrize("mode", ["json_object", "json_schema"])
def test_provider_format_is_explicit_and_frozen(supervisor_llm, monkeypatch, mode):
    from project_workflow import config

    monkeypatch.setenv("OPENAI_EVALUATOR_RESPONSE_FORMAT", mode)
    config.get_settings.cache_clear()
    supervisor_llm("PASS")
    provider = Mock(side_effect=OpenAICompatibleClient.chat)
    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)
    engine = SupervisorEngine("RUN-9412")
    result = engine.evaluate(report_json("Complete phase result"))
    assert result["verdict"] == "PASS", result
    snapshot = engine.db.step_history.list(task_key=engine.task_key)[0].evaluation_snapshot
    assert snapshot["contract_fingerprint_state"]["evaluator_response_format"] == mode
    if mode == "json_schema":
        wire_format = provider.call_args.kwargs["response_format"]
        assert wire_format["type"] == mode and wire_format["json_schema"]["strict"] is True
    else:
        assert "response_format" not in provider.call_args.kwargs


@pytest.mark.parametrize("policy", ["supervisor-evaluator-v13", "supervisor-evaluator-v14"])
def test_historical_frozen_history_does_not_require_new_assessments(policy):
    from project_workflow.supervisor.checks import normalize_text
    from project_workflow.supervisor.evaluate import _fingerprint_contract_state, _report_fingerprint
    from project_workflow.supervisor.evidence import validate_frozen_evaluation

    items = [{"id": "phase:check:7", "text": "Prepared result"}]
    contract = {"phase_code": "phase"}
    state = {"prompt_version": policy, "contract": contract,
             "evaluation_items": items, "previously_covered_ids": [], "delegation_allowed": False,
             "group": ["phase"], "transition_routes": {}, "phase_graph": []}
    if policy == "supervisor-evaluator-v14":
        state["evaluator_response_format"] = "json_object"
    fingerprint = _fingerprint_contract_state(state)
    step = {"task_id": 7, "worker_report": "Prepared result", "covered_item_ids": [items[0]["id"]],
            "replay_fingerprint": _report_fingerprint(7, normalize_text("Prepared result"), fingerprint)}
    snapshot = {"prompt_version": policy, "contract_snapshot": {
        **contract, "evaluation_items": items}, "contract_fingerprint": fingerprint,
        "evaluated_contract_fingerprint": fingerprint, "contract_fingerprint_state": state,
        "covered_item_ids": [items[0]["id"]], "raw_evaluator": {"verdict": "PASS",
        "covered": [items[0]["id"]], "missing": [], "blockers": [], "message": "Complete", "confidence": 1.0}}
    before = json.dumps(snapshot, sort_keys=True)
    assert validate_frozen_evaluation(step, snapshot) == [items[0]["id"]]
    assert json.dumps(snapshot, sort_keys=True) == before
    assert PromptBuilder.PROMPT_VERSION != snapshot["prompt_version"]


@pytest.mark.parametrize(("outcome", "reason"), [
    ("incomplete", "лимит токенов"), ("refusal", "отказался"), ("content_filter", "фильтром"),
])
def test_provider_stop_is_not_retried_as_a_format_repair(monkeypatch, outcome, reason):
    calls = []

    def stopped(client, **kwargs):
        calls.append(kwargs)
        client.last_call_diagnostics = {"outcome": outcome}
        raise ValueError("Provider stopped the response")

    monkeypatch.setattr(OpenAICompatibleClient, "chat", stopped)
    result = SupervisorEngine("RUN-9413").evaluate(report_json("Actual phase report"))
    assert result["verdict"] == "BLOCKED" and result["retryable"]
    assert reason in " ".join(result["blockers"])
    assert len(calls) == 1
