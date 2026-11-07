"""Safe actionable errors without repair, transport, or loss of the saved artifact."""

import json
import re
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from click.testing import CliRunner

from project_workflow.domain import phase_report
from project_workflow.domain.phase_report import (
    PHASE_REPORT_INSTRUCTIONS,
    PhaseReport,
    PhaseReportFormatError,
)
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder
from project_workflow.interfaces.cli import ui  # noqa: F401 -- register commands
from project_workflow.interfaces.cli.core import cli
from project_workflow.interfaces.ui.routes.configured_cli_api import error
from tests.test_configured_cli import WRITER, enroll, step
from tests.test_configured_cli import configured as configured
from tests.test_configured_cli_transport import agent_env as agent_env


def packet():
    return {
        "source": {"request": "Owner request", "decisions": []},
        "result": {"artifacts": [{"name": "Requirements", "content": {"scope": ["Saved text"]}}],
                   "assumptions": []},
        "unresolved": [],
    }


def missing_source_close(length):
    """Sanitized variants of the five observed failures, not a format converter."""
    value = packet()
    value["result"]["artifacts"][0]["content"]["scope"] = [""]
    raw = json.dumps(value, separators=(",", ":"))
    raw = raw.replace(']},"result":', '],"result":', 1)
    value["result"]["artifacts"][0]["content"]["scope"] = ["x" * (length - len(raw))]
    raw = json.dumps(value, separators=(",", ":")).replace(']},"result":', '],"result":', 1)
    assert len(raw) == length
    return raw


def reason(raw):
    with pytest.raises(PhaseReportFormatError) as raised:
        PhaseReport.parse(raw)
    return str(raised.value)


@pytest.mark.parametrize("length", [5111, 4142, 4879, 4424, 3501])
def test_five_sanitized_missing_source_closures_explain_syntax_and_eof(length):
    raw = missing_source_close(length)
    with pytest.raises(json.JSONDecodeError) as raised:
        json.loads(raw)
    decode = raised.value
    message = reason(raw)
    assert decode.msg.lower() in message.lower()
    assert f"line {decode.lineno}" in message.lower()
    assert f"column {decode.colno}" in message.lower()
    assert "end of input" in message.lower() or "eof" in message.lower()
    assert "x" * 50 not in message
    # A terminal brace alone makes valid JSON but leaves result inside source.
    nested = json.loads(raw + "}")
    assert "result" not in nested and "result" in nested["source"]
    reason(raw + "}")


@pytest.mark.parametrize("raw", ['{"source":\n', '{"source": nope}', '{"source" "secret-value"}'])
def test_syntax_uses_standard_safe_description_and_exact_location(raw):
    with pytest.raises(json.JSONDecodeError) as raised:
        json.loads(raw)
    decode = raised.value
    message = reason(raw)
    assert decode.msg.lower() in message.lower()
    assert f"line {decode.lineno}" in message.lower()
    assert f"column {decode.colno}" in message.lower()
    assert "secret-value" not in message and "nope" not in message


@pytest.mark.parametrize("raw,path,expected,actual", [
    ('{"source":{"request":7,"decisions":[]},"result":{"artifacts":[],"assumptions":[]},'
     '"unresolved":[]}', "source.request", "string", "number"),
    ('{"source":{"request":"","decisions":false},"result":{"artifacts":[],"assumptions":[]},'
     '"unresolved":[]}', "source.decisions", "array", "boolean"),
    ('{"source":{"request":"","decisions":[]},"result":{"artifacts":[{"name":"doc","content":[]}],'
     '"assumptions":[]},"unresolved":[]}', "result.artifacts[0].content", "string or object", "array"),
    ('{"source":{"request":"","decisions":[]},"result":{"artifacts":[{"name":null,"content":"doc"}],'
     '"assumptions":[]},"unresolved":[]}', "result.artifacts[0].name", "string", "null"),
    ('{"source":{"request":"","decisions":[]},"result":{"artifacts":[],"assumptions":[false]},'
     '"unresolved":[]}', "result.assumptions[0]", "string", "boolean"),
])
def test_known_schema_path_expected_type_and_actual_type(raw, path, expected, actual):
    message = reason(raw).lower()
    assert path.lower() in message
    assert "expected" in message and expected in message
    assert "received" in message and actual in message


@pytest.mark.parametrize("raw,path", [
    ('{"source":{"request":"","decisions":[]},"result":{"artifacts":[{"name":"doc"}],'
     '"assumptions":[]},"unresolved":[]}', "result.artifacts[0].content"),
    ('{"source":{"request":"","decisions":[{"subject":"Access"}]},'
     '"result":{"artifacts":[],"assumptions":[]},"unresolved":[]}', "source.decisions[0].value"),
    ('{"source":{"request":"","decisions":[]},"result":{"artifacts":[],"assumptions":[]},'
     '"unresolved":[{"kind":"question"}]}', "unresolved[0].text"),
])
def test_missing_nested_fields_are_named_without_manufactured_defaults(raw, path):
    message = reason(raw).lower()
    assert path.lower() in message and "required" in message


def test_valid_json_with_wrong_nesting_does_not_promote_source_children():
    value = packet()
    nested = {"source": {**value["source"], "result": value["result"], "unresolved": []}}
    raw = json.dumps(nested)
    assert isinstance(json.loads(raw), dict)
    message = reason(raw).lower()
    assert "source" in message or "result" in message
    assert any(word in message for word in ("extra", "unknown", "unexpected", "required"))


@pytest.mark.parametrize("location", ["root", "source", "artifact"])
def test_unknown_secret_field_names_and_values_never_appear_in_errors(location):
    value = packet()
    target = {"root": value, "source": value["source"],
              "artifact": value["result"]["artifacts"][0]}[location]
    target["private-key-must-not-leak"] = "private-value-must-not-leak"
    value["source"]["request"] = "private-owner-request-must-not-leak"
    message = reason(json.dumps(value))
    assert "private-" not in message
    assert any(word in message.lower() for word in ("extra", "unknown", "unexpected"))
    response = error(PhaseReportFormatError(message))
    assert response.status_code == 422
    body = json.loads(response.body)
    assert body["error_code"] == "invalid-phase-report"
    assert body["error"] == message
    assert "private-" not in response.body.decode()


@pytest.mark.parametrize("raw,description", [
    ('{"private-secret-key":1,"private-secret-key":2}', "duplicate"),
    ('{"source":{"request":"","decisions":[]},"result":{"artifacts":[{"name":"d",'
     '"content":{"private-secret-key":NaN}}],"assumptions":[]},"unresolved":[]}', "non-finite"),
    (" " * 32001, "syntax"),
], ids=["duplicate", "nonfinite", "whitespace"])
def test_boundary_failures_are_distinct_safe_and_never_repaired(raw, description):
    message = reason(raw).lower()
    assert description in message
    assert "private-secret-key" not in message


def test_depth_error_rejects_without_repair():
    value = packet()
    value["result"]["artifacts"][0]["content"] = "DEPTH_SENTINEL"
    nested = '{"private-depth-key":' * 400 + "null" + "}" * 400
    raw = json.dumps(value).replace('"DEPTH_SENTINEL"', nested)
    assert len(raw) < 32000
    message = reason(raw)
    assert "Invalid phase report" in message
    assert "private-depth-key" not in message


def test_empty_required_string_has_a_known_path_and_no_value_echo():
    value = packet()
    value["result"]["artifacts"][0]["name"] = ""
    message = reason(json.dumps(value)).lower()
    assert "result.artifacts[0].name" in message
    assert any(word in message for word in ("nonempty", "non-empty", "empty", "length"))


@pytest.mark.parametrize("length", [5111, 4142, 4879, 4424, 3501])
def test_cli_human_and_json_explain_same_local_error_without_http_or_model(agent_env, monkeypatch, length):
    http = Mock(side_effect=AssertionError("Invalid report cannot reach HTTP"))
    advisor = Mock(side_effect=AssertionError("Invalid report cannot reach Advisor"))
    monkeypatch.setattr(requests.Session, "request", http)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", advisor)
    raw = missing_source_close(length)
    expected = reason(raw)
    args = ["step", "--task", "SDLC-33", "--report", "-",
            "--operation-key", "invalid-shape", "--expected-version", "3"]
    machine = CliRunner().invoke(cli, ["--json", *args], input=raw)
    human = CliRunner().invoke(cli, args, input=raw)
    assert machine.exit_code == human.exit_code == 1
    payload = json.loads(machine.output)
    assert payload["error_code"] == "invalid-phase-report"
    assert payload["error"] == expected
    assert payload["http_status"] is None
    assert payload["acceptance_unknown"] is False
    assert "Отчёт не отправлен: локальная ошибка формата" in human.output
    assert expected in re.sub(r"\s+", " ", human.output)
    assert "x" * 50 not in human.output
    http.assert_not_called()
    advisor.assert_not_called()


def test_configured_http_422_preserves_same_safe_error_without_model_or_transition(configured, monkeypatch):
    enroll(configured)
    before = step(configured).json()["result"]
    advisor = Mock(side_effect=AssertionError("Invalid report cannot reach Advisor"))
    monkeypatch.setattr(OpenAICompatibleClient, "respond", advisor)
    raw = missing_source_close(4424)
    response = step(configured, report=raw, operation_key="invalid-diagnostic", expected_version=before["version"])
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "invalid-phase-report"
    assert body["error"] == reason(raw)
    after = step(configured).json()["result"]
    assert (after["version"], after["phase_code"], after["status"]) == (
        before["version"], before["phase_code"], before["status"])
    advisor.assert_not_called()


def test_large_configured_http_report_preserves_document_through_advisor_and_history(configured, monkeypatch):
    enroll(configured)
    before = step(configured).json()["result"]
    value = packet()
    value["result"]["artifacts"][0]["content"] = {
        "document": "Полный сохранённый документ без сокращений. " * 4000,
        "tail": "Final document field must survive",
    }
    raw = json.dumps(value, ensure_ascii=False)
    assert len(raw) > 32000

    def respond(*_args, **kwargs):
        request = json.loads(kwargs["user"])
        assert request["report"] == value
        return {
            "verdict": "PARTIAL",
            "assessments": {item["id"]: {
                "covered": False, "reason": "Controlled criterion evaluation", "required_change": "Continue work",
            } for item in request["criteria"]},
            "blockers": [], "confidence": 1.0,
        }

    advisor = Mock(side_effect=respond)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", advisor)
    response = step(configured, report=raw, operation_key="large-report", expected_version=before["version"])
    assert response.status_code == 200, response.text
    assert response.json()["result"]["verdict"] == "PARTIAL"
    advisor.assert_called_once()
    client, assignment = configured
    history = client.get("/internal/runtime/history", headers=WRITER, params={
        "interaction_protocol": "configured-cli-v1", "task": assignment["task"],
        "namespace_id": assignment["namespace_id"],
    })
    assert history.status_code == 200, history.text
    records = history.json()["result"]["records"]
    assert len(records) == 1 and records[0]["worker_report"] == raw
    assert json.loads(records[0]["worker_report"]) == value


def test_correct_serialization_preserves_quotes_newlines_unicode_and_nested_content():
    value = packet()
    content = {"заголовок": 'Точный "документ"\nВторая строка',
               "nested": {"rows": [True, None, -1, {"private-business-key": "данные"}]}}
    value["result"]["artifacts"][0]["content"] = content
    value["source"]["decisions"] = [{"subject": "Доступ", "value": {"owner_only": True}}]
    raw = json.dumps(value, ensure_ascii=False)
    assert PhaseReport.parse(raw).model_dump(mode="json") == value
    assert PhaseReport.parse(raw).result.artifacts[0].content == content


def test_published_instruction_json_example_is_executable():
    example = PHASE_REPORT_INSTRUCTIONS.split("Example: ", 1)[1]
    value, _ = json.JSONDecoder().raw_decode(example)
    raw = json.dumps(value, ensure_ascii=False)
    assert PhaseReport.parse(raw).model_dump(mode="json") == value


def test_published_python_example_serializes_supplied_objects_without_mutation():
    code = PHASE_REPORT_INSTRUCTIONS.split("```python\n", 1)[1].split("```", 1)[0]
    inputs = {
        "request_text": 'Владелец: "точно"\nБез сокращения',
        "owner_decisions": [{"subject": "Доступ", "value": {"owner_only": True}}],
        "artifact_name": "Требования",
        "saved_document": json.loads('{"scope":["Полный документ"],"nested":{"flags":[true,null,-1]}}'),
        "assumptions": [],
        "unresolved": [],
    }
    before = deepcopy(inputs)
    namespace = dict(inputs)
    output = StringIO()
    with redirect_stdout(output):
        exec(compile(code, "<phase-report-instructions>", "exec"), namespace)
    expected = {
        "source": {"request": inputs["request_text"], "decisions": inputs["owner_decisions"]},
        "result": {"artifacts": [{"name": inputs["artifact_name"], "content": inputs["saved_document"]}],
                   "assumptions": inputs["assumptions"]},
        "unresolved": inputs["unresolved"],
    }
    assert PhaseReport.parse(output.getvalue()).model_dump(mode="json") == expected
    assert inputs == before
    assert namespace["report"]["result"]["artifacts"][0]["content"] is inputs["saved_document"]


def test_worker_format_instructions_do_not_change_actual_advisor_prepared_request(monkeypatch):
    from tests._report_helpers import response_body

    captured = []
    answer = {"verdict": "PASS", "assessments": {"C1": {
        "covered": True, "reason": "Документ содержит исходные факты.", "required_change": None}},
        "blockers": [], "confidence": 1.0}

    def send(session, prepared, **kwargs):
        assert isinstance(prepared, requests.PreparedRequest)
        assert prepared.method == "POST" and prepared.url == "https://advisor.invalid/responses"
        captured.append(prepared.body)
        response = requests.Response()
        response.status_code = 200
        response.request = prepared
        response._content = json.dumps(response_body(json.dumps(answer, ensure_ascii=False))).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    current = packet()
    current["source"]["decisions"] = [{"subject": "Формат", "value": {"format": "CSV"}}]
    parsed = PhaseReport.parse(json.dumps(current, ensure_ascii=False)).model_dump(mode="json")
    history = [packet()]
    phase = SimpleNamespace(name="Requirements preparation", delegate=None)
    items = [("phase:check:1", "The document preserves the owner's current decisions.")]
    for worker_text in ("old-worker-format-sentinel", "new-worker-serializer-sentinel"):
        monkeypatch.setattr(phase_report, "PHASE_REPORT_INSTRUCTIONS", worker_text)
        user = PromptBuilder.build_user_prompt("SDLC-33", phase, parsed, items,
            previous_reports=history, previous_assessments={}, delegation_allowed=False)
        client = OpenAICompatibleClient(base_url="https://advisor.invalid", model="app-test", api_key="",
            timeout=1200, max_tokens=4000, reasoning_effort="high")
        before = len(captured)
        schema = PromptBuilder.response_schema(items, delegation_allowed=False)
        assert client.respond(PromptBuilder.SYSTEM_PROMPT, user, response_format=schema) == answer
        assert len(captured) == before + 1
        body = json.loads(captured[-1])
        actual = json.loads(body["input"][0]["content"])
        assert actual["report"] == parsed and actual["previous_reports"] == history
        assert body["model"] == "app-test" and body["reasoning"] == {"effort": "high"}
        assert body["max_output_tokens"] == 4000 and body["text"]["format"] == schema
        assert worker_text not in captured[-1].decode()
    assert len(captured) == 2 and captured[0] == captured[1]
