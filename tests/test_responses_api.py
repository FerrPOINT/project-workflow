"""Regressions for the single native Responses evaluator contract."""

import json
from unittest.mock import Mock

import pytest
import requests

from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder

pytestmark = pytest.mark.unit


def envelope(text="{}", *, status="completed"):
    return {
        "status": status,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    }


def test_native_schema_does_not_depend_on_json_in_worker_report(monkeypatch):
    reply = Mock(spec=requests.Response, status_code=200, headers={})
    reply.json.return_value = envelope('{"verdict":"PARTIAL"}')
    post = Mock(return_value=reply)
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    client = OpenAICompatibleClient(base_url="https://provider.invalid/v1", api_key="test-key", max_tokens=65)
    fmt = PromptBuilder.response_schema([("phase:check:1", "Work is ready")])
    assert client.respond("Evaluate work.", "Work has not been prepared.", response_format=fmt) == {
        "verdict": "PARTIAL"
    }
    post.assert_called_once_with(
        "https://provider.invalid/v1/responses",
        headers={"Content-Type": "application/json", "Authorization": "Bearer test-key"},
        json={
            "model": "app-test",
            "instructions": "Evaluate work.",
            "input": [{"role": "user", "content": "Work has not been prepared."}],
            "text": {"format": fmt},
            "max_output_tokens": 65,
            "reasoning": {"effort": "high"},
            "store": False,
            "stream": False,
        },
        timeout=(30, 1200),
        allow_redirects=False,
    )


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled", "in_progress", "queued", None])
def test_noncompleted_response_never_becomes_acceptance(monkeypatch, status):
    reply = Mock(spec=requests.Response, status_code=200, headers={})
    reply.json.return_value = envelope('{"verdict":"PASS"}', status=status)
    post = Mock(return_value=reply)
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    client = OpenAICompatibleClient()
    with pytest.raises(ValueError):
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    post.assert_called_once()


def test_http_error_has_no_chat_fallback(monkeypatch):
    reply = Mock(spec=requests.Response, status_code=500, headers={})
    reply.raise_for_status.side_effect = requests.HTTPError("provider failed")
    post = Mock(return_value=reply)
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    with pytest.raises(requests.HTTPError):
        OpenAICompatibleClient().respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    post.assert_called_once()
    reply.json.assert_not_called()


def test_provider_output_over_budget_is_not_an_accepted_evaluation(monkeypatch):
    data = envelope('{"verdict":"PASS"}')
    data["usage"] = {"output_tokens": 179}
    reply = Mock(spec=requests.Response, status_code=200, headers={})
    reply.json.return_value = data
    post = Mock(return_value=reply)
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    client = OpenAICompatibleClient(max_tokens=16)
    with pytest.raises(ValueError, match="exceeded the output token limit"):
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    assert client.last_call_diagnostics["outcome"] == "limit_exceeded"
    post.assert_called_once()


def test_reasoning_is_not_evaluator_content(monkeypatch):
    data = envelope("{}")
    data["output"].insert(0, {"type": "reasoning", "summary": [{"type": "summary_text", "text": "private"}]})
    reply = Mock(spec=requests.Response, status_code=200, headers={})
    reply.json.return_value = data
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", Mock(return_value=reply))
    client = OpenAICompatibleClient()
    assert client.respond("sys", "usr", response_format=PromptBuilder.response_schema([])) == {}
    assert client.last_response_content == "{}"
    assert "private" not in str(client.last_call_diagnostics)


@pytest.mark.parametrize(
    "part",
    [
        {"type": "function_call", "arguments": "{}"},
        {
            "type": "message",
            "role": "assistant",
            "status": "incomplete",
            "content": [{"type": "output_text", "text": "{}"}],
        },
        {"type": "message", "role": "user", "status": "completed", "content": [{"type": "output_text", "text": "{}"}]},
    ],
)
def test_unexpected_or_incomplete_output_is_rejected(monkeypatch, part):
    reply = Mock(spec=requests.Response, status_code=200, headers={})
    reply.json.return_value = {"status": "completed", "output": [part]}
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", Mock(return_value=reply))
    with pytest.raises(ValueError):
        OpenAICompatibleClient().respond("sys", "usr", response_format=PromptBuilder.response_schema([]))


def raw_response(text):
    response = requests.Response()
    response.status_code = 200
    response.encoding = "utf-8"
    response._content = text.encode("utf-8")
    return response


@pytest.mark.parametrize("key", ["status", "output"])
def test_duplicate_outer_envelope_keys_fail_without_retry(monkeypatch, key):
    data = envelope('{"verdict":"PASS"}')
    text = json.dumps(data)
    text = text[:-1] + "," + json.dumps(key) + ":" + json.dumps(data[key]) + "}"
    post = Mock(return_value=raw_response(text))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    client = OpenAICompatibleClient()
    with pytest.raises(ValueError, match="duplicate object keys"):
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    post.assert_called_once()
    assert client.last_call_diagnostics["outcome"] != "success"
    assert client.last_response_content is None


@pytest.mark.parametrize("value", [None, True, False, -1, 1.0, 1.5, "1", [], {}])
def test_malformed_output_token_usage_fails_without_retry(monkeypatch, value):
    data = envelope('{"verdict":"PASS"}')
    data["usage"] = {"output_tokens": value}
    post = Mock(return_value=raw_response(json.dumps(data)))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    client = OpenAICompatibleClient()
    with pytest.raises(ValueError, match="Invalid evaluator output token usage"):
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    post.assert_called_once()
    assert client.last_call_diagnostics["outcome"] != "success"


@pytest.mark.parametrize("value", [0, 16])
def test_exact_nonnegative_output_token_usage_is_accepted(monkeypatch, value):
    data = envelope("{}")
    data["usage"] = {"output_tokens": value}
    post = Mock(return_value=raw_response(json.dumps(data)))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    client = OpenAICompatibleClient(max_tokens=16)
    assert client.respond("sys", "usr", response_format=PromptBuilder.response_schema([])) == {}
    post.assert_called_once()


@pytest.mark.parametrize(
    "content",
    ['{"verdict":"PASS","verdict":"PARTIAL"}', '{"assessments":[],"assessments":[]}'],
)
def test_duplicate_assessment_json_keys_fail_without_retry(monkeypatch, content):
    post = Mock(return_value=raw_response(json.dumps(envelope(content))))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    client = OpenAICompatibleClient()
    with pytest.raises(ValueError, match="duplicate object keys"):
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    post.assert_called_once()
    assert client.last_call_diagnostics["outcome"] != "success"


def test_refusal_cannot_accept_parseable_output(monkeypatch):
    data = envelope('{"verdict":"PASS"}')
    data["output"][0]["content"].append({"type": "refusal", "refusal": "not available"})
    post = Mock(return_value=raw_response(json.dumps(data)))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    client = OpenAICompatibleClient()
    with pytest.raises(ValueError, match="refused"):
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    post.assert_called_once()
    assert client.last_call_diagnostics["outcome"] == "refusal"
