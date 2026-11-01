"""Saved diagnostics explain attempts without changing evaluator decisions."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from pydantic import BaseModel, ValidationError

from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder, ResponseParser
from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.diagnostics import (
    capture_attempt,
    evaluation_diagnostic,
    history_diagnostic,
    text_snapshot,
)

pytestmark = pytest.mark.supervisor


def test_saved_diagnostic_is_read_only_and_does_not_repair_partial(supervisor_llm):
    engine = SupervisorEngine("RUN-940")
    supervisor_llm("PARTIAL")
    result = engine.evaluate("Prepared document; not yet confirmed")
    entry = engine.db.step_history.list(task_key=engine.task_key)[0]
    before = json.dumps(entry.evaluation_snapshot, sort_keys=True)
    with patch.object(OpenAICompatibleClient, "chat", side_effect=AssertionError("read cannot call model")):
        diagnostic = history_diagnostic(entry.worker_report, entry.evaluation_snapshot)
    assert diagnostic["availability"] == "captured"
    assert diagnostic["prompt_version"] == PromptBuilder.PROMPT_VERSION
    assert diagnostic["user"]["text"].endswith("Evaluate this report and return strict JSON.")
    assert diagnostic["decision"]["verdict"] == result["verdict"] == "PARTIAL"
    assert any(item["classification"] == "missing" for item in diagnostic["criteria"])
    assert diagnostic["attempts"][0]["error"] is None
    assert "unavailable" in diagnostic["limitation"]
    assert json.dumps(entry.evaluation_snapshot, sort_keys=True) == before


def test_invalid_attempts_and_repair_prompts_are_preserved(supervisor_llm):
    engine = SupervisorEngine("RUN-941")
    supervisor_llm("PASS")
    valid = OpenAICompatibleClient.chat
    calls = 0

    def chat(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {"verdict": "PASS"} if calls == 1 else valid(*args, **kwargs)

    with patch.object(OpenAICompatibleClient, "chat", side_effect=chat):
        engine.evaluate("Complete phase report")
    entry = engine.db.step_history.list(task_key=engine.task_key)[0]
    attempts = entry.evaluation_snapshot["diagnostics"]["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["response"] == {"verdict": "PASS"}
    assert attempts[0]["error"]["category"] == "response_contract"
    assert attempts[0]["error"]["fields"]
    assert attempts[0]["prompt"]["reference"] == "user"
    assert "PREVIOUS RESPONSE WAS INVALID" in attempts[1]["prompt"]["text"]
    assert attempts[1]["error"] is None


def test_transport_failure_is_not_a_business_rejection():
    engine = SupervisorEngine("RUN-942")
    with patch.object(OpenAICompatibleClient, "chat", side_effect=requests.Timeout("private credential")):
        result = engine.evaluate("Actual document")
    entry = engine.db.step_history.list(task_key=engine.task_key)[0]
    diagnostic = entry.evaluation_snapshot["diagnostics"]
    assert result["retryable"] is True
    assert diagnostic["outcome"] == "technical_failure"
    assert len(diagnostic["attempts"]) == 1
    assert diagnostic["attempts"][0]["error"] == {"category": "timeout", "type": "Timeout"}
    assert "private credential" not in json.dumps(diagnostic)


def test_secret_redaction_and_unknown_response_fields():
    client = SimpleNamespace(api_key="active-secret-value", last_call_diagnostics={"model": "app-test"},
                             last_response_content="invalid private content")
    raw = {"message": "active-secret-value Bearer abcdef api_key=another-token sk-abcdefgh123",
           "reasoning_content": "never store hidden reasoning", "unexpected": "private value"}
    diagnostic = capture_attempt(client, number=1, prompt=raw["message"], raw=raw, error=None)
    serialized = json.dumps(diagnostic)
    for forbidden in ("active-secret-value", "abcdef", "another-token", "sk-abcdefgh123",
                      "never store hidden reasoning", "invalid private content", "private value"):
        assert forbidden not in serialized
    assert diagnostic["prompt"]["redacted"] is True
    assert len(diagnostic["response_content"]["sha256"]) == 64


def test_validation_errors_do_not_echo_input_or_exception_messages():
    class Schema(BaseModel):
        confidence: float

    try:
        Schema.model_validate({"confidence": "secret-value"})
    except ValidationError as exc:
        attempt = capture_attempt(SimpleNamespace(), number=1, prompt="report", raw=None, error=exc)
    assert "secret-value" not in json.dumps(attempt)
    assert attempt["error"]["fields"] == [{"location": ["confidence"], "type": "float_parsing"}]


def test_legacy_snapshot_is_not_misrepresented_as_captured():
    original = {"prompt_version": "supervisor-evaluator-v12", "raw_evaluator": {
        "verdict": "PARTIAL", "covered": [], "missing": ["1"], "message": "Missing document"},
        "contract_snapshot": {"evaluation_items": [{"id": "1", "text": "FULL document"}]}}
    diagnostic = history_diagnostic("old report", original)
    assert diagnostic["availability"] == "legacy"
    assert diagnostic["attempts"] is None
    assert diagnostic["criteria"][0] == {"id": "1", "text": "FULL document", "classification": "missing",
                                         "reason": None, "quote": None, "quote_status": "not_supplied",
                                         "text_truncated": False}
    assert "diagnostics" not in original


def test_large_text_is_bounded_and_explicitly_not_exact():
    text = "x" * 100_000
    snapshot = text_snapshot(text)
    assert snapshot["truncated"] is True and snapshot["characters"] == len(text)
    assert len(snapshot["text"]) == 64_000
    assert snapshot["sha256"] != text_snapshot(snapshot["text"])["sha256"]


@pytest.mark.parametrize(("quote", "expected"), [("FULL document", "found_in_captured_text"),
                                                  ("invented evidence", "not_found"), (None, "not_supplied")])
def test_reason_and_exact_quote_are_inspectable_not_an_automatic_verdict(quote, expected):
    raw = {"verdict": "PARTIAL", "covered": [], "missing": ["1"], "blockers": [],
           "message": "Check the missing evidence", "confidence": 0.5,
           "item_explanations": [{"id": "1", "reason": "Document evidence is incomplete", "quote": quote}]}
    diagnostic = history_diagnostic("FULL document", {"raw_evaluator": raw,
        "contract_snapshot": {"evaluation_items": [{"id": "1", "text": "FULL document required"}]}})
    # Optional annotations may exist in historical traces, but baseline v12 does
    # not admit new wire fields merely because diagnostics can display them.
    with pytest.raises(ValidationError):
        ResponseParser.parse(raw, required_item_ids=["1"])
    assert diagnostic["criteria"][0]["reason"] == "Document evidence is incomplete"
    assert diagnostic["criteria"][0]["quote_status"] == expected


@pytest.mark.parametrize("explanations", [
    [{"id": "unknown", "reason": "not a criterion"}],
    [{"id": "1", "reason": "one"}, {"id": "1", "reason": "duplicate"}],
])
def test_invalid_annotations_are_flagged_without_changing_business_decision(explanations):
    raw = {"verdict": "PARTIAL", "covered": [], "missing": ["1"], "blockers": [],
           "message": "Missing", "confidence": 0.5, "item_explanations": explanations}
    with pytest.raises(ValidationError):
        ResponseParser.parse(raw, required_item_ids=["1"])
    diagnostic = history_diagnostic("report", {"raw_evaluator": raw,
        "contract_snapshot": {"evaluation_items": [{"id": "1", "text": "actual criterion"}]}})
    assert diagnostic["invalid_annotations"] == 1
    assert len(diagnostic["criteria"]) == 1


def test_diagnostics_preserve_baseline_prompt_without_requesting_new_explanations():
    assert PromptBuilder.PROMPT_VERSION == "supervisor-evaluator-v12"
    assert "item_explanations" not in PromptBuilder.SYSTEM_PROMPT
    assert set(ResponseParser.parse({
        "verdict": "PARTIAL", "covered": [], "missing": ["1"], "blockers": [],
        "message": "Missing evidence", "confidence": 0.5,
    }, required_item_ids=["1"]).raw) == {
        "verdict", "covered", "missing", "blockers", "message", "confidence",
    }


def test_captured_criteria_do_not_reintroduce_secret_from_frozen_contract():
    client = SimpleNamespace(api_key="bare-credential")
    diagnostic = evaluation_diagnostic(system="system", user="user", report="report", prompt_version="v16",
        items=[("1", "bare-credential")], attempts=[], client=client, technical_error=False)
    exported = history_diagnostic("report", {"diagnostics": diagnostic,
        "contract_snapshot": {"evaluation_items": [{"id": "1", "text": "bare-credential"}]}})
    assert "bare-credential" not in json.dumps(exported)
    assert exported["criteria"][0]["text"] == "[REDACTED]"


@pytest.mark.parametrize("target", ["capture_attempt", "evaluation_diagnostic"])
def test_capture_error_never_changes_a_business_verdict_or_persistence(target, supervisor_llm):
    engine = SupervisorEngine("RUN-943")
    supervisor_llm("PASS")
    with patch("project_workflow.supervisor.evaluate." + target, side_effect=RuntimeError("private failure")):
        assert engine.evaluate("actual completed report")["verdict"] == "PASS"
    entry = engine.db.step_history.list(task_key=engine.task_key)[0]
    diagnostic = entry.evaluation_snapshot["diagnostics"]
    assert "private failure" not in json.dumps(diagnostic)
    if target == "capture_attempt":
        assert diagnostic["attempts"][0]["capture_error"] == "RuntimeError"
    else:
        assert diagnostic["availability"] == "capture_failed"


def test_rejected_provider_pass_cannot_be_exported_as_the_effective_decision():
    attempt = capture_attempt(SimpleNamespace(), number=1, prompt="prompt", raw={"verdict": "PASS"},
                              error=ValueError("PASS requires full coverage"))
    diagnostic = evaluation_diagnostic(system="system", user="prompt", report="report", prompt_version="v16",
        items=[("1", "criterion")], attempts=[attempt], client=None, technical_error=True)
    exported = history_diagnostic("report", {"diagnostics": diagnostic, "raw_evaluator": {"error": "ValueError"}})
    assert exported["decision"]["verdict"] == "BLOCKED"
    assert exported["attempts"][0]["response"]["verdict"] == "PASS"


def test_aggregate_budget_and_omissions_are_explicit():
    diagnostic = evaluation_diagnostic(system="я" * 100_000, user="я" * 100_000, report="я" * 100_000,
        prompt_version="v16", items=[(str(i), "я" * 10_000) for i in range(250)],
        attempts=[], client=None, technical_error=False)
    assert len(json.dumps(diagnostic, ensure_ascii=False).encode()) <= 750_000
    assert diagnostic["items_omitted"] == 50
    assert diagnostic["budget_omissions"]


def test_capture_failure_cannot_fall_back_to_unredacted_model_message():
    raw = {"verdict": "PASS", "covered": ["1"], "missing": [], "message": "bare-credential"}
    diagnostic = evaluation_diagnostic(system="system", user="user", report="report", prompt_version="v16",
        items=[("1", "criterion")], attempts=[{"number": 1, "capture_error": "RuntimeError"}],
        client=SimpleNamespace(api_key="bare-credential"), technical_error=False, decision=raw)
    exported = history_diagnostic("report", {"diagnostics": diagnostic, "raw_evaluator": raw})
    assert exported["decision"]["message"] == "[REDACTED]"
    assert "bare-credential" not in json.dumps(exported)


def test_many_schema_errors_are_bounded_with_an_omitted_count():
    class Schema(BaseModel):
        covered: list[int]

    try:
        Schema.model_validate({"covered": ["invalid"] * 1000})
    except ValidationError as exc:
        attempt = capture_attempt(SimpleNamespace(), number=1, prompt="report", raw=None, error=exc)
    assert len(attempt["error"]["fields"]) == 200
    assert attempt["error"]["fields_omitted"] == 800


def test_budget_last_resort_is_bounded_even_with_unexpected_error_metadata():
    diagnostic = evaluation_diagnostic(system="system", user="user", report="report", prompt_version="v16",
        items=[], attempts=[{"number": 1, "error": {"unexpected": "x" * 1_000_000}}],
        client=None, technical_error=True)
    assert diagnostic == {"schema": "evaluator-diagnostics-v1", "availability": "capture_failed",
                          "error_type": "DiagnosticBudgetExceeded", "budget_bytes": 750_000}
