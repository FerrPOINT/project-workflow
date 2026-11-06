"""Regressions for the single native Responses evaluator contract."""

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
            "reasoning": {"effort": "none"},
            "store": False,
            "stream": False,
        },
        timeout=120,
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
