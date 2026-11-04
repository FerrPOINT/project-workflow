"""Client diagnostics use synthetic provider responses; no network or model calls."""

import json
from itertools import count
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from project_workflow.infrastructure import llm
from project_workflow.supervisor.evaluate import _evaluate_strict_response

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("boundary", ["envelope", "content"])
@pytest.mark.parametrize("recover", [False, True])
def test_deep_provider_json_has_one_bounded_format_retry(client, monkeypatch, boundary, recover):
    valid = {"verdict": "PASS", "assessments": {
        "C1": {"covered": True, "reason": "The required result is supplied"},
    }, "blockers": [], "confidence": 0.9}
    deep = '{"nested":' + '[' * 3000 + '0' + ']' * 3000 + '}'

    def response(bad):
        value = Mock(status_code=200, headers={})
        if bad and boundary == "envelope":
            value.json.side_effect = RecursionError("private provider content")
        else:
            value.json.return_value = {"choices": [{"finish_reason": "stop", "message": {
                "content": deep if bad else json.dumps(valid),
            }}]}
        return value

    post = Mock(side_effect=[response(True), response(not recover)])
    monkeypatch.setattr(llm.requests, "post", post)
    attempts = []
    arguments = dict(client=client, user='{"actual":"unchanged report"}',
                     evaluation_items=[("P:check:1", "Required result")],
                     phase=SimpleNamespace(delegate=None), attempts=attempts)
    if recover:
        _, parsed = _evaluate_strict_response(**arguments)
        assert parsed.verdict == "PASS"
    else:
        with pytest.raises(ValueError, match="nesting") as failure:
            _evaluate_strict_response(**arguments)
        assert "private provider content" not in str(failure.value)
    assert post.call_count == len(attempts) == 2
    bodies = [call.kwargs["json"] for call in post.call_args_list]
    assert bodies[0]["messages"][1] == bodies[1]["messages"][1]
    assert bodies[0]["messages"][0] != bodies[1]["messages"][0]
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
        "model": "provider/returned-model", "id": "untrusted-envelope-id",
        "choices": [{"finish_reason": "stop", "message": {
            "content": '{"value":"raw-content-secret"}', "reasoning_content": "private-reasoning-secret",
        }}],
        "usage": {
            "prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
            "completion_tokens_details": {"reasoning_tokens": 3, "private": "private-usage-secret"},
            "private": "private-usage-secret",
        },
        "_hidden_params": {"provider": "internal-attribution-secret"},
    }
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.headers = requests.structures.CaseInsensitiveDict({
        "X-Request-Id": "req_123-abc.456", "Authorization": "response-header-secret",
    })
    response.json.return_value = data
    post = Mock(return_value=response)
    monkeypatch.setattr(llm.requests, "post", post)
    monkeypatch.setattr(llm, "perf_counter", Mock(side_effect=count(1.0, 0.025)))
    return post, response, data


def test_success_is_bounded_and_preserves_wire_request(client, provider, capsys, caplog):
    post, _, _ = provider
    assert client.last_call_diagnostics == {} and client.last_response_content is None
    assert client.chat("system-secret", "user-secret", temperature=0.25) == {"value": "raw-content-secret"}
    assert client.last_call_diagnostics == {
        "model": "provider/requested-model", "timeout": 17, "max_tokens": 650,
        "reasoning_effort": "low", "temperature": 0.25, "latency_ms": 25.0,
        "http_status": 200, "returned_model": "provider/returned-model", "finish_reason": "stop",
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18, "reasoning_tokens": 3},
        "request_id": "req_123-abc.456", "outcome": "success",
    }
    post.assert_called_once_with(
        client.base_url + "/chat/completions",
        headers={"Content-Type": "application/json", "Authorization": "Bearer api-key-secret"},
        json={"model": "provider/requested-model", "messages": [
            {"role": "system", "content": "system-secret"}, {"role": "user", "content": "user-secret"},
        ], "temperature": 0.25, "response_format": {"type": "json_object"}, "max_tokens": 650,
              "reasoning_effort": "low"}, timeout=17,
    )
    metadata = json.dumps(client.last_call_diagnostics, allow_nan=False)
    for secret in (
        "endpoint.invalid", "private-endpoint-secret", "api-key-secret", "system-secret", "user-secret",
        "raw-content-secret", "private-reasoning-secret", "private-usage-secret", "internal-attribution-secret",
        "response-header-secret", "untrusted-envelope-id", "reasoning_content", "_hidden_params",
    ):
        assert secret not in metadata
    assert client.last_response_content == '{"value":"raw-content-secret"}'
    assert "private-reasoning-secret" not in client.last_response_content
    captured = capsys.readouterr()
    assert captured.out == captured.err == "" and not caplog.records


@pytest.mark.parametrize("error", [
    requests.Timeout("exception-secret"), requests.ConnectionError("exception-secret"),
    TimeoutError("exception-secret"), RuntimeError("exception-secret"),
])
def test_transport_error_resets_previous_call_before_post(client, provider, error):
    post, _, _ = provider
    client.chat("sys", "usr")
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
        client.chat("sys", "usr")
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
        client.chat("sys", "usr")
    assert raised.value is error
    post.assert_called_once()
    response.json.assert_not_called()
    assert client.last_call_diagnostics["outcome"] == "http"
    assert client.last_call_diagnostics["http_status"] == 503
    assert client.last_call_diagnostics["request_id"] == "req_123-abc.456"
    assert client.last_call_diagnostics["latency_ms"] == 25
    assert client.last_response_content is None
    assert "private-http-exception-secret" not in json.dumps(client.last_call_diagnostics)


@pytest.mark.parametrize("content,outcome,error", [
    ("", "empty", ValueError), (" \n ", "empty", ValueError),
    ("not-json-secret", "invalid_json", json.JSONDecodeError),
    ('```json\n{}\n```', "invalid_json", json.JSONDecodeError),
    ("[]", "invalid_json", ValueError), ("null", "invalid_json", ValueError),
    (None, "invalid_json", AttributeError), (42, "invalid_json", AttributeError),
])
def test_content_failures_keep_usage_and_finish_without_reasoning(client, provider, content, outcome, error):
    post, _, data = provider
    data["choices"][0]["message"]["content"] = content
    with pytest.raises(error):
        client.chat("sys", "usr")
    post.assert_called_once()
    diagnostics = client.last_call_diagnostics
    assert diagnostics["outcome"] == outcome and diagnostics["latency_ms"] == 25
    assert diagnostics["finish_reason"] == "stop" and diagnostics["returned_model"] == "provider/returned-model"
    assert diagnostics["usage"] == {
        "prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18, "reasoning_tokens": 3,
    }
    assert client.last_response_content == (content if isinstance(content, str) else None)
    assert "private-reasoning-secret" not in json.dumps(diagnostics)
    assert "reasoning_content" not in json.dumps(diagnostics)


@pytest.mark.parametrize("content", ["", " \n ", "not-json-secret", "[]", "null", None, 42, '{}'])
def test_truncated_content_is_incomplete_before_json_parsing(client, provider, content):
    post, _, data = provider
    data["choices"][0]["finish_reason"] = "length"
    data["choices"][0]["message"]["content"] = content
    with pytest.raises(ValueError, match="token limit"):
        client.chat("sys", "usr")
    post.assert_called_once()
    diagnostics = client.last_call_diagnostics
    assert diagnostics["outcome"] == "incomplete" and diagnostics["latency_ms"] == 25
    assert diagnostics["finish_reason"] == "length"
    assert diagnostics["usage"]["reasoning_tokens"] == 3
    assert client.last_response_content == (content if isinstance(content, str) else None)
    assert "private-reasoning-secret" not in json.dumps(diagnostics)


@pytest.mark.parametrize("data,error", [(None, AttributeError), ([], AttributeError), ({"choices": []}, IndexError)])
def test_malformed_envelope_preserves_existing_exception(client, provider, data, error):
    post, response, _ = provider
    response.json.return_value = data
    with pytest.raises(error):
        client.chat("sys", "usr")
    post.assert_called_once()
    assert client.last_call_diagnostics["outcome"] == "invalid_json"
    assert client.last_call_diagnostics["latency_ms"] == 25
    assert client.last_response_content is None


def test_envelope_json_decode_error_has_no_raw_content(client, provider):
    post, response, _ = provider
    error = requests.exceptions.JSONDecodeError("private-json-secret", "private-envelope-secret", 0)
    response.json.side_effect = error
    with pytest.raises(requests.exceptions.JSONDecodeError) as raised:
        client.chat("sys", "usr")
    assert raised.value is error
    post.assert_called_once()
    assert client.last_call_diagnostics["outcome"] == "invalid_json"
    assert client.last_response_content is None
    assert "secret" not in json.dumps(client.last_call_diagnostics)


@pytest.mark.parametrize("request_id", ["", "x" * 129, "id\nsecret", "id\x00secret", "id secret", "id\u00e9",
                                       "https://private.invalid/id", {"private": "secret"}, 42])
def test_unsafe_request_ids_are_omitted(client, provider, request_id):
    _, response, _ = provider
    response.headers["x-request-id"] = request_id
    client.chat("sys", "usr")
    assert client.last_call_diagnostics["request_id"] is None


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), 2**80, "123", [], {"private": "secret"}])
def test_usage_is_numeric_nonnegative_bounded_and_whitelisted(client, provider, value):
    _, _, data = provider
    data["usage"] = {"prompt_tokens": value, "completion_tokens": value, "total_tokens": value,
                     "reasoning_tokens": value, "completion_tokens_details": {"reasoning_tokens": value}}
    client.chat("sys", "usr")
    assert client.last_call_diagnostics["usage"] == {}
    json.dumps(client.last_call_diagnostics, allow_nan=False)


def test_optional_metadata_is_not_required_by_existing_mocks(client, provider):
    _, response, _ = provider
    response.headers = Mock()
    response.status_code = Mock()
    response.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
    assert client.chat("sys", "usr") == {}
    assert client.last_call_diagnostics["http_status"] is None
    assert client.last_call_diagnostics["request_id"] is None
    assert client.last_call_diagnostics["finish_reason"] is None
    assert client.last_call_diagnostics["returned_model"] is None
    assert client.last_call_diagnostics["usage"] == {}


def test_untrusted_labels_and_nonfinite_temperature_are_not_metadata(client, provider):
    _, _, data = provider
    client.model = "https://private.invalid/secret"
    client.reasoning_effort = "private\nreasoning"
    data["model"] = "x" * 129
    data["choices"][0]["finish_reason"] = {"private": "secret"}
    data["usage"] = {"prompt_tokens": 1.5, "reasoning_tokens": 2}
    client.chat("sys", "usr", temperature=float("nan"))
    diagnostics = client.last_call_diagnostics
    for key in ("model", "reasoning_effort", "temperature", "returned_model", "finish_reason"):
        assert diagnostics[key] is None
    assert diagnostics["usage"] == {"prompt_tokens": 1.5, "reasoning_tokens": 2}
    json.dumps(diagnostics, allow_nan=False)


def test_configuration_failure_resets_content_and_records_latency(client, provider):
    post, _, _ = provider
    client.chat("sys", "usr")
    client.base_url = "https://openrouter.ai/api/v1"
    client.api_key = ""
    with pytest.raises(llm.LlmConfigurationError):
        client.chat("sys", "usr")
    post.assert_called_once()
    assert client.last_response_content is None
    assert client.last_call_diagnostics["outcome"] == "configuration"
    assert client.last_call_diagnostics["latency_ms"] == 25
