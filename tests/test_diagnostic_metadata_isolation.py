"""Metadata failure must not replace the provider content or transport error."""

from unittest.mock import Mock, patch

import pytest
import requests

from project_workflow import config
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder
from tests._report_helpers import response_body

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


def test_response_metadata_failure_does_not_change_success_or_retry():
    client = OpenAICompatibleClient(base_url="https://synthetic.invalid/v1", api_key="test-key")
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.headers = {}
    response.json.return_value = response_body("{}")
    with patch("project_workflow.infrastructure.llm.requests.post", return_value=response) as post:
        with patch.object(client, "_capture_response_diagnostics", side_effect=ValueError("private-secret")):
            assert client.respond("system", "report", response_format=PromptBuilder.response_schema([])) == {}
    post.assert_called_once()
    assert client.last_call_diagnostics["outcome"] == "success"
    assert client.last_call_diagnostics["metadata_error"] == "ValueError"
    assert "private-secret" not in str(client.last_call_diagnostics)


def test_response_metadata_failure_does_not_hide_content_error():
    client = OpenAICompatibleClient(base_url="https://synthetic.invalid/v1", api_key="test-key")
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.headers = {}
    response.json.return_value = response_body("")
    with patch("project_workflow.infrastructure.llm.requests.post", return_value=response):
        with patch.object(client, "_capture_response_diagnostics", side_effect=ValueError("private-secret")):
            with pytest.raises(ValueError, match="Empty content from LLM"):
                client.respond("system", "report", response_format=PromptBuilder.response_schema([]))
