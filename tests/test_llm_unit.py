"""Unit tests for llm.py without network calls."""

from __future__ import annotations

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
    engine._resolve_transition.return_value = (None, None, None)
    engine._resolve_current_phase.return_value = "1"
    engine.db.get_task.return_value = engine.task
    return engine


class TestEvaluateLlmReportVerdicts:
    def test_blocked_sets_default_blocker(self):
        engine = _make_engine()
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[])
        with patch.object(
            OllamaClient,
            "chat",
            return_value={
                "verdict": "BLOCKED",
                "covered": [],
                "missing": ["x"],
                "blockers": [],
                "message": "blocked",
                "next_phase": None,
                "next_phase_name": None,
                "confidence": 0.7,
            },
        ):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "BLOCKED"
        assert result["blockers"] == ["LLM identified blocker"]
        engine._record_evaluation.assert_called_once_with(phase, "blocked", None, None, commit=False)

    def test_rollback_uses_rollback_target(self):
        engine = _make_engine()
        engine._resolve_transition.return_value = (None, None, "0")
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[], rollback_target="0")
        with patch.object(
            OllamaClient,
            "chat",
            return_value={
                "verdict": "ROLLBACK",
                "covered": [],
                "missing": [],
                "blockers": [],
                "message": "rb",
                "next_phase": None,
                "next_phase_name": None,
                "confidence": 0.6,
            },
        ):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "ROLLBACK"
        assert result["rollback_target"] == "0"
        assert result["next_phase"] == "0"

    def test_delegate_records_transition(self):
        engine = _make_engine()
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[], is_delegated=True)
        with patch.object(
            OllamaClient,
            "chat",
            return_value={
                "verdict": "DELEGATE",
                "covered": [],
                "missing": [],
                "blockers": [],
                "message": "delegate",
                "next_phase": None,
                "next_phase_name": None,
                "confidence": 0.5,
            },
        ):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "DELEGATE"
        engine._record_evaluation.assert_called_once_with(phase, "delegate", None, None, commit=False)

    def test_pass_fills_next_phase_from_builder(self):
        engine = _make_engine()
        engine._resolve_transition.return_value = ("2", "Two", None)
        next_phase = Phase(code="2", name="Two", instructions=[], checks=[], evidence=[])
        engine.all_phases = [Phase(code="1", name="One", instructions=[], checks=[], evidence=[]), next_phase]
        engine.phase_map = {"2": next_phase}
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[])
        with patch.object(
            OllamaClient,
            "chat",
            return_value={
                "verdict": "PASS",
                "covered": ["a"],
                "missing": [],
                "blockers": [],
                "message": "ok",
                "next_phase": None,
                "next_phase_name": None,
                "confidence": 0.9,
            },
        ):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "PASS"
        assert result["next_phase"] == "2"
        assert result["next_phase_name"] == "Two"

    def test_persistence_failure_rolls_back_transaction(self):
        engine = _make_engine()
        engine.db.create_supervisor_run.side_effect = RuntimeError("write failed")
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[])
        with (
            patch.object(OllamaClient, "chat", return_value={"verdict": "PARTIAL"}),
            pytest.raises(RuntimeError, match="write failed"),
        ):
            evaluate_llm_report("r", phase, engine)

        engine._record_evaluation.assert_called_once_with(phase, "partial", None, None, commit=False)
        engine.db.rollback.assert_called_once_with()
        engine.db.commit.assert_not_called()


class TestLoadApiKey:
    def test_env_key(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "env-token")
        import importlib

        import project_workflow.infrastructure.llm

        importlib.reload(project_workflow.infrastructure.llm)
        assert project_workflow.infrastructure.llm._load_api_key() == "env-token"

    def test_env_empty_reads_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "")
        env_file = tmp_path / "hermes.env"
        env_file.write_text("OLLAMA_API_KEY=file-token\n")
        import importlib

        import project_workflow.infrastructure.llm

        monkeypatch.setattr(project_workflow.infrastructure.llm.os.path, "expanduser", lambda _path: str(env_file))
        importlib.reload(project_workflow.infrastructure.llm)
        assert project_workflow.infrastructure.llm._load_api_key() == "file-token"

    def test_no_key_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OLLAMA_API_KEY", "")
        env_file = tmp_path / "missing.env"
        import importlib

        import project_workflow.infrastructure.llm

        monkeypatch.setattr(project_workflow.infrastructure.llm.os.path, "expanduser", lambda _path: str(env_file))
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
    def test_markdown_json_is_rejected(self):
        text = '```json\n{"verdict": "PASS"}\n```'
        with pytest.raises(ValueError):
            OllamaClient._extract_json(text)

    def test_extract_plain_json(self):
        text = '{"verdict": "BLOCKED"}'
        result = OllamaClient._extract_json(text)
        assert result["verdict"] == "BLOCKED"

    def test_free_text_around_json_is_rejected(self):
        text = 'Some text {"verdict": "PARTIAL"} more text'
        with pytest.raises(ValueError):
            OllamaClient._extract_json(text)

    def test_invalid_json_is_rejected(self):
        text = "not json"
        with pytest.raises(ValueError):
            OllamaClient._extract_json(text)


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
        from project_workflow.wizard.models import PhaseCheck, PhaseEvidence, PhaseInstruction

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
            "missing": [],
            "blockers": [],
            "message": "ok",
            "next_phase": "2",
            "next_phase_name": "Two",
            "confidence": 0.9,
        }
        v = ResponseParser.parse(raw)
        assert v.verdict == "PASS"
        assert v.covered == ["A"]
        assert v.next_phase is None
        assert v.confidence == 0.9

    def test_parse_invalid_verdict(self):
        with pytest.raises(ValueError):
            ResponseParser.parse({"verdict": "UNKNOWN"})

    def test_parse_rejects_wrong_collection_types(self):
        with pytest.raises(ValueError):
            ResponseParser.parse({"verdict": "BLOCKED", "covered": "single"})

    def test_parse_rejects_out_of_range_confidence(self):
        with pytest.raises(ValueError):
            ResponseParser.parse({"verdict": "pass", "confidence": 1.5})
        with pytest.raises(ValueError):
            ResponseParser.parse({"verdict": "pass", "confidence": -0.5})

    def test_parse_optional_fields_get_defaults(self):
        verdict = ResponseParser.parse({"verdict": "PARTIAL", "confidence": None})
        assert verdict.covered == []
        assert verdict.confidence == 0.5
