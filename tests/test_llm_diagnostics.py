"""Client diagnostics use synthetic provider responses; no network or model calls."""

import json
from itertools import count
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from project_workflow.infrastructure import llm
from project_workflow.infrastructure.llm import PromptBuilder
from project_workflow.supervisor.evaluate import _evaluate_strict_response
from tests._report_helpers import report_json, response_body

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("boundary", ["envelope", "content"])
@pytest.mark.parametrize("queued_valid", [False, True])
def test_deep_provider_json_fails_without_retry_even_if_next_response_would_be_valid(
    client, monkeypatch, boundary, queued_valid, json_recursion_failure,
):
    valid = {"verdict": "PASS", "assessments": {
        "C1": {"covered": True, "reason": "The required result is supplied", "required_change": None},
    }, "blockers": [], "confidence": 0.9}
    deep = '{"nested":' + '[' * 3000 + '0' + ']' * 3000 + '}'
    if boundary == "content":
        json_recursion_failure(deep)

    def response(bad):
        value = Mock(status_code=200, headers={})
        if bad and boundary == "envelope":
            value.json.side_effect = RecursionError("private provider content")
        else:
            value.json.return_value = response_body(deep if bad else json.dumps(valid))
        return value

    post = Mock(side_effect=[response(True), response(not queued_valid)])
    monkeypatch.setattr(llm.requests, "post", post)
    attempts = []
    phase = SimpleNamespace(name="Review", delegate=None)
    items = [("P:check:1", "Required result")]
    user = llm.PromptBuilder.build_user_prompt(
        "not-transmitted", phase, json.loads(report_json("Actual unchanged report")), items,
    )
    with pytest.raises(ValueError, match="nesting") as failure:
        _evaluate_strict_response(
            client, user=user, evaluation_items=items, phase=phase, attempts=attempts,
            response_format=llm.PromptBuilder.response_schema(items),
        )
    assert "private provider content" not in str(failure.value)
    assert post.call_count == len(attempts) == 1
    bodies = [call.kwargs["json"] for call in post.call_args_list]
    assert bodies[0]["instructions"] == llm.PromptBuilder.SYSTEM_PROMPT
    assert bodies[0]["input"] == [{"role": "user", "content": user}]
    assert attempts[0]["error"]["category"] == "response_contract"
    assert all(attempt["provider"]["outcome"] == "invalid_json" for attempt in attempts[:1])


@pytest.fixture
def client():
    return llm.OpenAICompatibleClient(
        base_url="https://endpoint.invalid/private-endpoint-secret", api_key="api-key-secret",
        model="provider/requested-model", timeout=17, max_tokens=650, reasoning_effort="low",
    )


@pytest.fixture
def provider(monkeypatch):
    data = {
        **response_body(
            '{"value":"raw-content-secret"}',
            status="completed",
        ),
        "model": "provider/returned-model",
        "id": "untrusted-envelope-id",
        "usage": {
            "input_tokens": 11,
            "output_tokens": 7,
            "total_tokens": 18,
            "output_tokens_details": {"reasoning_tokens": 3, "private": "private-usage-secret"},
            "private": "private-usage-secret",
        },
        "_hidden_params": {"provider": "internal-attribution-secret"},
    }
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.headers = requests.structures.CaseInsensitiveDict(
        {
            "X-Request-Id": "req_123-abc.456",
            "Authorization": "response-header-secret",
        }
    )
    response.json.return_value = data
    post = Mock(return_value=response)
    monkeypatch.setattr(llm.requests, "post", post)
    monkeypatch.setattr(llm, "perf_counter", Mock(side_effect=count(1.0, 0.025)))
    return post, response, data


def test_success_is_bounded_and_preserves_wire_request(client, provider, capsys, caplog):
    post, _, _ = provider
    assert client.last_call_diagnostics == {} and client.last_response_content is None
    assert client.respond("system-secret", "user-secret", response_format=PromptBuilder.response_schema([])) == {
        "value": "raw-content-secret"
    }
    assert client.last_call_diagnostics == {
        "model": "provider/requested-model",
        "timeout": 17,
        "max_tokens": 650,
        "reasoning_effort": "low",
        "latency_ms": 25.0,
        "http_status": 200,
        "returned_model": "provider/returned-model",
        "finish_reason": "completed",
        "usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18, "reasoning_tokens": 3},
        "request_id": "req_123-abc.456",
        "outcome": "success",
    }
    post.assert_called_once_with(
        client.base_url + "/responses",
        headers={"Content-Type": "application/json", "Authorization": "Bearer api-key-secret"},
        json={
            "model": "provider/requested-model",
            "instructions": "system-secret",
            "input": [{"role": "user", "content": "user-secret"}],
            "text": {"format": llm.PromptBuilder.response_schema([])},
            "max_output_tokens": 650,
            "reasoning": {"effort": "low"},
            "store": False,
            "stream": False,
        },
        timeout=(30, 17), allow_redirects=False,
    )
    metadata = json.dumps(client.last_call_diagnostics, allow_nan=False)
    for secret in (
        "endpoint.invalid",
        "private-endpoint-secret",
        "api-key-secret",
        "system-secret",
        "user-secret",
        "raw-content-secret",
        "private-reasoning-secret",
        "private-usage-secret",
        "internal-attribution-secret",
        "response-header-secret",
        "untrusted-envelope-id",
        "reasoning_content",
        "_hidden_params",
    ):
        assert secret not in metadata
    assert client.last_response_content == '{"value":"raw-content-secret"}'
    assert "private-reasoning-secret" not in client.last_response_content
    captured = capsys.readouterr()
    assert captured.out == captured.err == "" and not caplog.records


@pytest.mark.parametrize(
    "error",
    [
        requests.Timeout("exception-secret"),
        requests.ConnectionError("exception-secret"),
        TimeoutError("exception-secret"),
        RuntimeError("exception-secret"),
    ],
)
def test_transport_error_resets_previous_call_before_post(client, provider, error):
    post, _, _ = provider
    client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    previous = client.last_call_diagnostics

    def fail(*args, **kwargs):
        assert client.last_response_content is None
        assert client.last_call_diagnostics["outcome"] == "transport"
        assert client.last_call_diagnostics["latency_ms"] == 0
        assert client.last_call_diagnostics["http_status"] is None
        assert client.last_call_diagnostics["request_id"] is None
        assert client.last_call_diagnostics["usage"] == {}
        raise error

    post.side_effect = fail
    with pytest.raises(type(error)) as raised:
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    assert raised.value is error
    assert post.call_count == 2 and previous["outcome"] == "success"
    assert client.last_call_diagnostics["outcome"] == "transport"
    assert client.last_call_diagnostics["latency_ms"] == 25
    assert "exception-secret" not in json.dumps(client.last_call_diagnostics)


def test_http_failure_keeps_status_and_safe_id_without_reading_body(client, provider):
    post, response, _ = provider
    error = requests.HTTPError("private-http-exception-secret")
    response.status_code = 503
    response.raise_for_status.side_effect = error
    with pytest.raises(requests.HTTPError) as raised:
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    assert raised.value is error
    post.assert_called_once()
    response.json.assert_not_called()
    assert client.last_call_diagnostics["outcome"] == "http"
    assert client.last_call_diagnostics["http_status"] == 503
    assert client.last_call_diagnostics["request_id"] == "req_123-abc.456"
    assert client.last_call_diagnostics["latency_ms"] == 25
    assert client.last_response_content is None
    assert "private-http-exception-secret" not in json.dumps(client.last_call_diagnostics)


@pytest.mark.parametrize(
    "content,outcome,error",
    [
        ("", "empty", ValueError),
        (" \n ", "empty", ValueError),
        ("not-json-secret", "invalid_json", json.JSONDecodeError),
        ("```json\n{}\n```", "invalid_json", json.JSONDecodeError),
        ("[]", "invalid_json", ValueError),
        ("null", "invalid_json", ValueError),
        (None, "invalid_json", ValueError),
        (42, "invalid_json", ValueError),
    ],
)
def test_content_failures_keep_usage_and_finish_without_reasoning(client, provider, content, outcome, error):
    post, _, data = provider
    data["output"][0]["content"][0]["text"] = content
    with pytest.raises(error):
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    post.assert_called_once()
    diagnostics = client.last_call_diagnostics
    assert diagnostics["outcome"] == outcome and diagnostics["latency_ms"] == 25
    assert diagnostics["finish_reason"] == "completed" and diagnostics["returned_model"] == "provider/returned-model"
    assert diagnostics["usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "reasoning_tokens": 3,
    }
    assert client.last_response_content == (content if isinstance(content, str) else None)
    assert "private-reasoning-secret" not in json.dumps(diagnostics)
    assert "reasoning_content" not in json.dumps(diagnostics)


@pytest.mark.parametrize("content", ["", " \n ", "not-json-secret", "[]", "null", None, 42, "{}"])
def test_truncated_content_is_incomplete_before_json_parsing(client, provider, content):
    post, _, data = provider
    data.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    data["output"][0]["content"][0]["text"] = content
    with pytest.raises(ValueError, match="response is incomplete"):
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    post.assert_called_once()
    diagnostics = client.last_call_diagnostics
    assert diagnostics["outcome"] == "incomplete" and diagnostics["latency_ms"] == 25
    assert diagnostics["finish_reason"] == "max_output_tokens"
    assert diagnostics["usage"]["reasoning_tokens"] == 3
    assert client.last_response_content is None
    assert "private-reasoning-secret" not in json.dumps(diagnostics)


@pytest.mark.parametrize("data,error", [(None, ValueError), ([], ValueError), ({"output": []}, ValueError)])
def test_malformed_envelope_preserves_existing_exception(client, provider, data, error):
    post, response, _ = provider
    response.json.return_value = data
    with pytest.raises(error):
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    post.assert_called_once()
    assert client.last_call_diagnostics["outcome"] == "invalid_json"
    assert client.last_call_diagnostics["latency_ms"] == 25
    assert client.last_response_content is None


def test_envelope_json_decode_error_has_no_raw_content(client, provider):
    post, response, _ = provider
    error = requests.exceptions.JSONDecodeError("private-json-secret", "private-envelope-secret", 0)
    response.json.side_effect = error
    with pytest.raises(requests.exceptions.JSONDecodeError) as raised:
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    assert raised.value is error
    post.assert_called_once()
    assert client.last_call_diagnostics["outcome"] == "invalid_json"
    assert client.last_response_content is None
    assert "secret" not in json.dumps(client.last_call_diagnostics)


@pytest.mark.parametrize(
    "request_id",
    [
        "",
        "x" * 129,
        "id\nsecret",
        "id\x00secret",
        "id secret",
        "id\u00e9",
        "https://private.invalid/id",
        {"private": "secret"},
        42,
    ],
)
def test_unsafe_request_ids_are_omitted(client, provider, request_id):
    _, response, _ = provider
    response.headers["x-request-id"] = request_id
    client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    assert client.last_call_diagnostics["request_id"] is None


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), 2**80, "123", [], {"private": "secret"}])
def test_usage_is_numeric_nonnegative_bounded_and_whitelisted(client, provider, value):
    _, _, data = provider
    data["usage"] = {
        "input_tokens": value,
        "output_tokens": value,
        "total_tokens": value,
        "reasoning_tokens": value,
        "output_tokens_details": {"reasoning_tokens": value},
    }
    if type(value) is int and value > client.max_tokens:
        with pytest.raises(ValueError, match="output token limit"):
            client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    else:
        with pytest.raises(ValueError, match="Invalid evaluator output token usage"):
            client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    assert client.last_call_diagnostics["usage"] == {}
    json.dumps(client.last_call_diagnostics, allow_nan=False)


def test_optional_metadata_is_not_required_by_existing_mocks(client, provider):
    _, response, _ = provider
    response.headers = Mock()
    response.status_code = Mock()
    response.json.return_value = response_body("{}")
    assert client.respond("sys", "usr", response_format=PromptBuilder.response_schema([])) == {}
    assert client.last_call_diagnostics["http_status"] is None
    assert client.last_call_diagnostics["request_id"] is None
    assert client.last_call_diagnostics["finish_reason"] == "completed"
    assert client.last_call_diagnostics["returned_model"] is None
    assert client.last_call_diagnostics["usage"] == {}


def test_uncapped_diagnostics_keep_null_limit_and_valid_large_usage(client, provider):
    post, _, data = provider
    client.max_tokens = None
    data["usage"] = {"input_tokens": 11, "output_tokens": 4501, "total_tokens": 4512}
    assert client.respond("sys", "usr", response_format=PromptBuilder.response_schema([])) == {
        "value": "raw-content-secret",
    }
    post.assert_called_once()
    assert "max_output_tokens" not in post.call_args.kwargs["json"]
    assert client.last_call_diagnostics["max_tokens"] is None
    assert client.last_call_diagnostics["usage"] == data["usage"]
    assert client.last_call_diagnostics["outcome"] == "success"


def test_untrusted_labels_are_not_metadata(client, provider):
    _, _, data = provider
    client.model = "https://private.invalid/secret"
    client.reasoning_effort = "private\nreasoning"
    data["model"] = "x" * 129
    data["model"] = {"private": "secret"}
    data["usage"] = {"input_tokens": 1.5, "output_tokens_details":{"reasoning_tokens":2}}
    client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    diagnostics = client.last_call_diagnostics
    for key in ("model", "reasoning_effort", "returned_model"):
        assert diagnostics[key] is None
    assert diagnostics["usage"] == {"input_tokens": 1.5, "reasoning_tokens": 2}
    json.dumps(diagnostics, allow_nan=False)


def test_configuration_failure_resets_content_and_records_latency(client, provider):
    post, _, _ = provider
    client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    client.base_url = "https://openrouter.ai/api/v1"
    client.api_key = ""
    with pytest.raises(llm.LlmConfigurationError):
        client.respond("sys", "usr", response_format=PromptBuilder.response_schema([]))
    post.assert_called_once()
    assert client.last_response_content is None
    assert client.last_call_diagnostics["outcome"] == "configuration"
    assert client.last_call_diagnostics["latency_ms"] == 25
