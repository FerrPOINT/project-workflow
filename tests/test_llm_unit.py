"""Unit tests for llm.py without network calls."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.infrastructure.llm import (
    OllamaClient,
    PromptBuilder,
    ResponseParser,
)
from project_workflow.wizard.evaluate import evaluate_llm_report
from project_workflow.wizard.models import Phase


def _make_engine():
    engine = MagicMock()
    engine.task_key = "TASK-1"
    engine.task = {"id": 1}
    engine.all_phases = []
    engine.phase_map = {}
    engine._get_previously_covered.return_value = []
    engine._resolve_current_phase.return_value = "1"
    engine.db.get_task.return_value = engine.task
    return engine


class TestEvaluateLlmReportVerdicts:
    def test_blocked_sets_default_blocker(self):
        engine = _make_engine()
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[])
        with patch.object(OllamaClient, "chat", return_value={
            "verdict": "BLOCKED",
            "covered": [],
            "missing": ["x"],
            "blockers": [],
            "message": "blocked",
            "next_phase": None,
            "next_phase_name": None,
            "confidence": 0.7,
        }):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "BLOCKED"
        assert result["blockers"] == ["LLM identified blocker"]
        engine._record_transition.assert_called_once()

    def test_rollback_uses_rollback_target(self):
        engine = _make_engine()
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[], rollback_target="0")
        with patch.object(OllamaClient, "chat", return_value={
            "verdict": "ROLLBACK",
            "covered": [],
            "missing": [],
            "blockers": [],
            "message": "rb",
            "next_phase": None,
            "next_phase_name": None,
            "confidence": 0.6,
        }):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "ROLLBACK"
        assert result["rollback_target"] == "0"
        assert result["next_phase"] is None

    def test_delegate_records_transition(self):
        engine = _make_engine()
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[])
        with patch.object(OllamaClient, "chat", return_value={
            "verdict": "DELEGATE",
            "covered": [],
            "missing": [],
            "blockers": [],
            "message": "delegate",
            "next_phase": None,
            "next_phase_name": None,
            "confidence": 0.5,
        }):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "DELEGATE"
        engine._record_transition.assert_called_once()

    def test_pass_fills_next_phase_from_builder(self):
        engine = _make_engine()
        next_phase = Phase(code="2", name="Two", instructions=[], checks=[], evidence=[])
        engine.all_phases = [Phase(code="1", name="One", instructions=[], checks=[], evidence=[]), next_phase]
        engine.phase_map = {"2": next_phase}
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[])
        with patch.object(OllamaClient, "chat", return_value={
            "verdict": "PASS",
            "covered": ["a"],
            "missing": [],
            "blockers": [],
            "message": "ok",
            "next_phase": None,
            "next_phase_name": None,
            "confidence": 0.9,
        }):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "PASS"
        assert result["next_phase"] == "2"
        assert result["next_phase_name"] == "Two"


class TestLoadApiKey:
    def test_env_key(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "env-token")
        import importlib
        import project_workflow.infrastructure.llm
        importlib.reload(project_workflow.infrastructure.llm)
        assert project_workflow.infrastructure.llm._load_api_key() == "env-token"

    def test_env_empty_reads_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "")
        env_file = Path.home() / ".hermes" / ".env"
        try:
            env_file.parent.mkdir(parents=True, exist_ok=True)
            env_file.write_text("OLLAMA_API_KEY=file-token\n")
            import importlib
            import project_workflow.infrastructure.llm
            importlib.reload(project_workflow.infrastructure.llm)
            assert project_workflow.infrastructure.llm._load_api_key() == "file-token"
        finally:
            if env_file.exists():
                env_file.unlink()

    def test_no_key_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "")
        env_file = Path.home() / ".hermes" / ".env"
        if env_file.exists():
            env_file.unlink()
        import importlib
        import project_workflow.infrastructure.llm
        importlib.reload(project_workflow.infrastructure.llm)
        assert project_workflow.infrastructure.llm._load_api_key() == ""

    def test_fresh_import_env(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "fresh-token")
        import importlib
        import project_workflow.infrastructure.llm
        importlib.reload(project_workflow.infrastructure.llm)
        assert project_workflow.infrastructure.llm._load_api_key() == "fresh-token"
        assert project_workflow.infrastructure.llm.OLLAMA_API_KEY == "fresh-token"


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
        from project_workflow.wizard.models import PhaseInstruction, PhaseCheck, PhaseEvidence
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
