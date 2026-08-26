"""Unit tests for llm.py without network calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.infrastructure.llm import (
    LlmConfigurationError,
    OpenAICompatibleClient,
    PromptBuilder,
    ResponseParser,
)
from project_workflow.supervisor.contracts import PhaseContractBuilder
from project_workflow.supervisor.evaluate import evaluate_llm_report
from project_workflow.supervisor.models import Phase, PhaseDelegate


def _make_engine():
    engine = MagicMock()
    engine.task_key = "RUN-1"
    engine.task = {
        "id": 1,
        "project_id": 1,
        "current_phase_id": 1,
        "current_phase_code": "1",
        "status": "active",
    }
    engine.workflow_id = 1
    engine.current_phase_code = "1"
    engine._get_previously_covered.return_value = []
    engine._resolve_transition.return_value = (None, None, None)
    engine.db.record_step.return_value = 42
    engine.db.step_history.get_by_fingerprint.return_value = None
    return engine


def _set_phase(engine, phase: Phase, *extra: Phase) -> None:
    phases = [phase, *extra]
    engine.all_phases = phases
    engine.phase_map = {item.code: item for item in phases}
    engine.contract_builder = PhaseContractBuilder(phases)


class TestEvaluateLlmReportVerdicts:
    def test_invalid_client_configuration_is_fail_closed(self):
        engine = _make_engine()
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[])
        _set_phase(engine, phase)
        with patch(
            "project_workflow.supervisor.evaluate.OpenAICompatibleClient",
            side_effect=LlmConfigurationError("secret"),
        ):
            result = evaluate_llm_report("r", phase, engine)

        assert result["verdict"] == "BLOCKED"
        assert result["retryable"] is True
        assert result["blockers"] == [
            "Проверяющий LLM не настроен: для OpenRouter требуется OPENAI_API_KEY."
        ]
        run_data = engine.db.record_step.call_args.args[0]
        assert run_data["replay_fingerprint"] is None
        assert run_data["evaluation_snapshot"]["model"] is None
        assert run_data["evaluation_snapshot"]["raw_evaluator"] == {
            "error": "LlmConfigurationError"
        }

    def test_invalid_blocked_is_retryable_and_records_blocked_transition(self):
        engine = _make_engine()
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[])
        _set_phase(engine, phase)
        with patch.object(
            OpenAICompatibleClient,
            "chat",
            return_value={
                "verdict": "BLOCKED",
                "covered": [],
                "missing": ["x"],
                "blockers": [],
                "message": "blocked",
                "confidence": 0.7,
            },
        ):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "BLOCKED"
        assert result["retryable"] is True
        assert result["blockers"] == ["Проверяющий LLM вернул некорректный ответ."]
        engine._record_evaluation.assert_called_once_with(
            phase, "blocked", None, None, 42, commit=False
        )

    def test_rollback_uses_rollback_target(self):
        engine = _make_engine()
        engine._resolve_transition.return_value = (None, None, "0")
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[], rollback_target_phase_code="0")
        _set_phase(engine, phase)
        with patch.object(
            OpenAICompatibleClient,
            "chat",
            return_value={
                "verdict": "ROLLBACK",
                "covered": [],
                "missing": [],
                "blockers": [],
                "message": "rb",
                "confidence": 0.6,
            },
        ):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "ROLLBACK"
        assert result["rollback_phase_code"] == "0"
        assert result["next_phase_code"] == "0"

    def test_delegate_records_transition(self):
        engine = _make_engine()
        phase = Phase(
            code="1",
            name="One",
            instructions=[],
            checks=[],
            evidence=[],
            delegate=PhaseDelegate(agent="reviewer"),
        )
        _set_phase(engine, phase)
        with patch.object(
            OpenAICompatibleClient,
            "chat",
            return_value={
                "verdict": "DELEGATE",
                "covered": [],
                "missing": [],
                "blockers": [],
                "message": "delegate",
                "confidence": 0.5,
            },
        ):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "DELEGATE"
        engine._record_evaluation.assert_called_once_with(
            phase, "delegate", None, None, 42, commit=False
        )

    def test_pass_fills_next_phase_from_builder(self):
        engine = _make_engine()
        engine._resolve_transition.return_value = ("2", "Two", None)
        next_phase = Phase(code="2", name="Two", instructions=[], checks=[], evidence=[])
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[])
        _set_phase(engine, phase, next_phase)
        with patch.object(
            OpenAICompatibleClient,
            "chat",
            return_value={
                "verdict": "PASS",
                "covered": [],
                "missing": [],
                "blockers": [],
                "message": "ok",
                "confidence": 0.9,
            },
        ):
            result = evaluate_llm_report("r", phase, engine)
        assert result["verdict"] == "PASS"
        assert result["next_phase_code"] == "2"
        assert result["next_phase_name"] == "Two"

    def test_persistence_failure_rolls_back_transaction(self):
        engine = _make_engine()
        engine.db.record_step.side_effect = RuntimeError("write failed")
        phase = Phase(code="1", name="One", instructions=[], checks=[], evidence=[])
        _set_phase(engine, phase)
        with (
            patch.object(
                OpenAICompatibleClient,
                "chat",
                return_value={
                    "verdict": "PASS", "covered": [], "missing": [], "blockers": [],
                    "message": "ok", "confidence": 0.9,
                },
            ),
            pytest.raises(RuntimeError, match="write failed"),
        ):
            evaluate_llm_report("r", phase, engine)

        engine._record_evaluation.assert_not_called()
        engine.db.rollback.assert_called_once_with()
        # The read snapshot transaction is closed before the provider call;
        # the failed write transaction is rolled back separately.
        engine.db.commit.assert_called_once_with()


class TestOpenAICompatibleClientChatErrors:
    def test_openrouter_without_key_is_rejected_before_network(self):
        client = OpenAICompatibleClient(base_url="https://openrouter.ai/api/v1", api_key="   ")
        with patch("requests.post") as post, pytest.raises(
            LlmConfigurationError,
            match="OPENAI_API_KEY",
        ):
            client.chat("sys", "user")

        post.assert_not_called()

    def test_custom_endpoint_remains_available_without_key(self):
        client = OpenAICompatibleClient(base_url="http://provider.internal/v1", api_key="")
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
        with patch("requests.post", return_value=response) as post:
            assert client.chat("sys", "user") == {}

        assert "Authorization" not in post.call_args.kwargs["headers"]

    def test_timeout(self):
        with patch("requests.post", side_effect=TimeoutError("slow")):
            client = OpenAICompatibleClient(api_key="test-key")
            with pytest.raises(TimeoutError):
                client.chat("sys", "user")

    def test_http_error(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = Exception("bad")
        with patch("requests.post", return_value=resp):
            client = OpenAICompatibleClient(api_key="test-key")
            with pytest.raises(Exception, match="bad"):
                client.chat("sys", "user")

    def test_empty_content(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"choices": [{"message": {"content": ""}}]}
        with patch("requests.post", return_value=resp):
            client = OpenAICompatibleClient(api_key="test-key")
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
        prompt = PromptBuilder.build_user_prompt("RUN-1", phase, report)
        assert "TASK: RUN-1" in prompt
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
        prompt = PromptBuilder.build_user_prompt("RUN-1", phase, "done", previously_covered=["A"])
        assert "Run tests" in prompt
        assert "Check A" in prompt
        assert "Screenshot" in prompt
        assert "A" in prompt


class TestResponseParser:
    def test_parse_full(self):
        raw = {
            "verdict": "PASS",
            "covered": ["A"],
            "missing": [],
            "blockers": [],
            "message": "ok",
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

    def test_parse_invalid_required_fields_is_rejected(self):
        with pytest.raises(ValueError):
            ResponseParser.parse(
                {"verdict": "PASS", "covered": [], "missing": [], "blockers": [], "confidence": 1.5, "message": None}
            )

    def test_parse_missing_control_fields_is_rejected(self):
        with pytest.raises(ValueError):
            ResponseParser.parse({"verdict": "PARTIAL", "confidence": None})
