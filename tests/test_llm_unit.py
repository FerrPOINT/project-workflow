"""Unit tests for llm.py without network calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.infrastructure.llm import (
    OpenAICompatibleClient,
    PromptBuilder,
    ResponseParser,
)
from project_workflow.supervisor.evaluate import evaluate_llm_report
from project_workflow.supervisor.models import Phase


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
    def test_invalid_blocked_is_retryable_without_transition(self):
        engine = _make_engine()
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[])
        with patch.object(
            OpenAICompatibleClient,
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
        assert result["retryable"] is True
        assert result["blockers"] == ["Supervisor LLM unavailable: ValueError"]
        engine._record_evaluation.assert_not_called()

    def test_rollback_uses_rollback_target(self):
        engine = _make_engine()
        engine._resolve_transition.return_value = (None, None, "0")
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[], rollback_target="0")
        with patch.object(
            OpenAICompatibleClient,
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
            OpenAICompatibleClient,
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
            OpenAICompatibleClient,
            "chat",
            return_value={
                "verdict": "PASS",
                "covered": [],
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
            patch.object(
                OpenAICompatibleClient,
                "chat",
                return_value={"verdict": "PASS", "covered": [], "missing": [], "blockers": []},
            ),
            pytest.raises(RuntimeError, match="write failed"),
        ):
            evaluate_llm_report("r", phase, engine)

        engine._record_evaluation.assert_not_called()
        engine.db.rollback.assert_called_once_with()
        engine.db.commit.assert_not_called()


class TestOpenAICompatibleClientIsAvailable:
    def test_local_endpoint_available_without_key(self):
        with patch("requests.get", return_value=MagicMock(status_code=200)) as mock:
            client = OpenAICompatibleClient(base_url="http://localhost:11434/v1", api_key="")
            assert client.is_available() is True
            mock.assert_called_once_with("http://localhost:11434/v1/models", headers={}, timeout=5)

    def test_provider_available_with_bearer_key(self):
        with patch("requests.get", return_value=MagicMock(status_code=200)) as mock:
            client = OpenAICompatibleClient(base_url="https://provider.example/v1", api_key="k")
            assert client.is_available() is True
            mock.assert_called_once_with(
                "https://provider.example/v1/models",
                headers={"Authorization": "Bearer k"},
                timeout=5,
            )

    def test_unavailable(self):
        with patch("requests.get", side_effect=ConnectionError("no")):
            client = OpenAICompatibleClient(base_url="http://localhost:11434/v1")
            assert client.is_available() is False


class TestOpenAICompatibleClientChatErrors:
    def test_timeout(self):
        with patch("requests.post", side_effect=TimeoutError("slow")):
            client = OpenAICompatibleClient()
            with pytest.raises(TimeoutError):
                client.chat("sys", "user")

    def test_http_error(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("bad")
        with patch("requests.post", return_value=resp):
            client = OpenAICompatibleClient()
            with pytest.raises(Exception, match="bad"):
                client.chat("sys", "user")

    def test_empty_content(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": ""}}]}
        with patch("requests.post", return_value=resp):
            client = OpenAICompatibleClient()
            with pytest.raises(ValueError, match="Empty content"):
                client.chat("sys", "user")

    def test_whitespace_content(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": "  "}}]}
        with patch("requests.post", return_value=resp):
            client = OpenAICompatibleClient(base_url="https://provider.example/v1")
            with pytest.raises(ValueError, match="Empty content"):
                client.chat("sys", "user")


class TestExtractJson:
    def test_markdown_json_is_rejected(self):
        text = '```json\n{"verdict": "PASS"}\n```'
        with pytest.raises(ValueError):
            OpenAICompatibleClient._extract_json(text)

    def test_extract_plain_json(self):
        text = '{"verdict": "BLOCKED"}'
        result = OpenAICompatibleClient._extract_json(text)
        assert result["verdict"] == "BLOCKED"

    def test_free_text_around_json_is_rejected(self):
        text = 'Some text {"verdict": "PARTIAL"} more text'
        with pytest.raises(ValueError):
            OpenAICompatibleClient._extract_json(text)

    def test_invalid_json_is_rejected(self):
        text = "not json"
        with pytest.raises(ValueError):
            OpenAICompatibleClient._extract_json(text)


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
        from project_workflow.supervisor.models import PhaseCheck, PhaseEvidence, PhaseInstruction

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

    def test_parse_invalid_optional_fields_use_defaults(self):
        verdict = ResponseParser.parse(
            {"verdict": "pass", "covered": [], "missing": [], "blockers": [], "confidence": 1.5, "message": None}
        )
        assert verdict.confidence == 0.5
        assert verdict.message == ""

    def test_parse_missing_control_fields_is_rejected(self):
        with pytest.raises(ValueError):
            ResponseParser.parse({"verdict": "PARTIAL", "confidence": None})
