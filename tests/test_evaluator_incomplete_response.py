"""A parseable prefix must not turn a token-limited completion into acceptance."""

from unittest.mock import Mock

import pytest

from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder
from tests._report_helpers import response_body

pytestmark = pytest.mark.unit


def test_token_limited_json_is_not_a_completed_evaluation(monkeypatch):
    content = '{"verdict":"PASS"}'
    response = Mock(status_code=200, headers={})
    response.json.return_value = {
        **response_body(
            content,
            status=("incomplete" if "length" in ("length", "content_filter") else "completed"),
            reason=(
                "max_output_tokens"
                if "length" == "length"
                else "content_filter"
                if "length" == "content_filter"
                else None
            ),
        ),
        "usage": {"output_tokens": 4000},
    }
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", Mock(return_value=response))
    client = OpenAICompatibleClient(api_key="test-only", reasoning_effort="high")

    with pytest.raises(ValueError, match="token limit"):
        client.respond("Evaluate criteria and return JSON", "Report", response_format=PromptBuilder.response_schema([]))

    assert client.last_response_content is None
    assert client.last_call_diagnostics["outcome"] == "incomplete"
    assert client.last_call_diagnostics["finish_reason"] == "max_output_tokens"
    assert client.last_call_diagnostics["usage"]["output_tokens"] == 4000
