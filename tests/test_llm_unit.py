"""Unit tests for llm.py without network calls."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wartz_workflow.llm import (
    OLLAMA_API_KEY,
    OllamaClient,
    PromptBuilder,
    ResponseParser,
    _load_api_key,
)
from wartz_workflow.models import Phase


class TestLoadApiKey:
    def test_env_key(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "env-token")
        import importlib, wartz_workflow.llm
        importlib.reload(wartz_workflow.llm)
        assert wartz_workflow.llm._load_api_key() == "env-token"

    def test_env_empty_reads_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "")
        env_file = Path.home() / ".hermes" / ".env"
        try:
            env_file.parent.mkdir(parents=True, exist_ok=True)
            env_file.write_text("OLLAMA_API_KEY=file-token\n")
            import importlib, wartz_workflow.llm
            importlib.reload(wartz_workflow.llm)
            assert wartz_workflow.llm._load_api_key() == "file-token"
        finally:
            if env_file.exists():
                env_file.unlink()

    def test_no_key_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "")
        env_file = Path.home() / ".hermes" / ".env"
        if env_file.exists():
            env_file.unlink()
        import importlib, wartz_workflow.llm
        importlib.reload(wartz_workflow.llm)
        assert wartz_workflow.llm._load_api_key() == ""

    def test_fresh_import_env(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "fresh-token")
        import importlib, wartz_workflow.llm
        importlib.reload(wartz_workflow.llm)
        assert wartz_workflow.llm._load_api_key() == "fresh-token"
        assert wartz_workflow.llm.OLLAMA_API_KEY == "fresh-token"


class TestOllamaClientDetection:
    def test_cloud_detection(self):
        client = OllamaClient(base_url="https://ollama.com/v1", api_key="k")
        assert client.is_cloud is True

    def test_local_detection(self):
        client = OllamaClient(base_url="http://localhost:11434")
        assert client.is_cloud is False


class TestOllamaClientIsAvailable:
    def test_local_available(self):
        with patch("requests.get", return_value=MagicMock(status_code=200)) as mock:
            client = OllamaClient(base_url="http://localhost:11434")
            assert client.is_available() is True
            mock.assert_called_once_with("http://localhost:11434/api/tags", timeout=5)

    def test_cloud_available(self):
        with patch("requests.get", return_value=MagicMock(status_code=200)) as mock:
            client = OllamaClient(base_url="https://ollama.com/v1", api_key="k")
            assert client.is_available() is True
            mock.assert_called_once_with(
                "https://ollama.com/v1/models",
                headers={"Authorization": "Bearer k"},
                timeout=5,
            )

    def test_unavailable(self):
        with patch("requests.get", side_effect=ConnectionError("no")):
            client = OllamaClient(base_url="http://localhost:11434")
            assert client.is_available() is False


class TestOllamaClientChatErrors:
    def test_timeout(self):
        with patch("requests.post", side_effect=TimeoutError("slow")):
            client = OllamaClient()
            with pytest.raises(TimeoutError):
                client.chat("sys", "user")

    def test_http_error(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("bad")
        with patch("requests.post", return_value=resp):
            client = OllamaClient()
            with pytest.raises(Exception, match="bad"):
                client.chat("sys", "user")

    def test_empty_content(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"message": {"content": ""}}
        with patch("requests.post", return_value=resp):
            client = OllamaClient()
            with pytest.raises(ValueError, match="Empty content"):
                client.chat("sys", "user")

    def test_cloud_empty_content(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": "  "}}]}
        with patch("requests.post", return_value=resp):
            client = OllamaClient(base_url="https://ollama.com/v1")
            with pytest.raises(ValueError, match="Empty content"):
                client.chat("sys", "user")


class TestExtractJson:
    def test_extract_markdown_json(self):
        text = '```json\n{"verdict": "PASS"}\n```'
        result = OllamaClient._extract_json(text)
        assert result["verdict"] == "PASS"

    def test_extract_plain_json(self):
        text = '{"verdict": "BLOCKED"}'
        result = OllamaClient._extract_json(text)
        assert result["verdict"] == "BLOCKED"

    def test_extract_nested_json(self):
        text = 'Some text {"verdict": "PARTIAL"} more text'
        result = OllamaClient._extract_json(text)
        assert result["verdict"] == "PARTIAL"

    def test_extract_invalid_json_fallback(self):
        text = "not json"
        result = OllamaClient._extract_json(text)
        assert result["verdict"] == "BLOCKED"
        assert "LLM response was not valid JSON" in result["blockers"]


class TestPromptBuilder:
    def test_build_user_prompt(self):
        phase = Phase(
            code="1",
            name="Phase One",
            instructions=[],
            checks=[],
            evidence=[],
        )
        report = "I did it"
        prompt = PromptBuilder.build_user_prompt("TASK-1", phase, report)
        assert "TASK: TASK-1" in prompt
        assert "Phase One" in prompt
        assert report in prompt

    def test_build_user_prompt_with_lists(self):
        from wartz_workflow.models import PhaseInstruction, PhaseCheck, PhaseEvidence
        phase = Phase(
            code="1",
            name="Phase One",
            instructions=[PhaseInstruction(step="Run tests")],
            checks=[PhaseCheck(description="Check A")],
            evidence=[PhaseEvidence(item="Screenshot")],
        )
        prompt = PromptBuilder.build_user_prompt("TASK-1", phase, "done", previously_covered=["A"])
        assert "Run tests" in prompt
        assert "Check A" in prompt
        assert "Screenshot" in prompt
        assert "A" in prompt


class TestResponseParser:
    def test_parse_full(self):
        raw = {
            "verdict": "pass",
            "covered": ["A"],
            "missing": ["B"],
            "blockers": ["C"],
            "message": "ok",
            "next_phase": "2",
            "next_phase_name": "Two",
            "confidence": 0.9,
        }
        v = ResponseParser.parse(raw)
        assert v.verdict == "PASS"
        assert v.covered == ["A"]
        assert v.next_phase == "2"
        assert v.confidence == 0.9

    def test_parse_invalid_verdict(self):
        v = ResponseParser.parse({"verdict": "UNKNOWN"})
        assert v.verdict == "PARTIAL"

    def test_parse_coerces_types(self):
        v = ResponseParser.parse({
            "verdict": "blocked",
            "covered": "single",
            "missing": None,
            "blockers": [],
            "confidence": None,
        })
        assert v.covered == ["single"]
        assert v.missing == []
        assert v.confidence == 0.5

    def test_parse_clamps_confidence(self):
        v = ResponseParser.parse({"verdict": "pass", "confidence": 1.5})
        assert v.confidence == 1.0
        v = ResponseParser.parse({"verdict": "pass", "confidence": -0.5})
        assert v.confidence == 0.0

    def test_to_str_list_skips_empty(self):
        assert ResponseParser._to_str_list(["a", "", "b"]) == ["a", "b"]
        assert ResponseParser._to_str_list(None) == []
        assert ResponseParser._to_str_list(123) == []
