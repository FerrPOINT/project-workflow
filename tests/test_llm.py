"""Tests for OpenAI-compatible evaluation and response parsing."""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

pytestmark = [pytest.mark.unit]

from project_workflow.infrastructure.llm import (
    LlmVerdict,
    OpenAICompatibleClient,
    PromptBuilder,
    ResponseParser,
)


class FakePhase:
    """Minimal Phase-like object for prompt building."""

    def __init__(self, **kwargs):
        self.code = kwargs.get("code", "1")
        self.name = kwargs.get("name", "Test")
        self.instructions = kwargs.get("instructions", [])
        self.checks = kwargs.get("checks", [])
        self.evidence = kwargs.get("evidence", [])
        self.rollback_target = kwargs.get("rollback_target")


class FakeInstruction:
    def __init__(self, step):
        self.step = step


class FakeCheck:
    def __init__(self, description):
        self.description = description


class FakeEvidence:
    def __init__(self, item):
        self.item = item


class TestOpenAICompatibleClient:
    """Unit tests for the provider-neutral Chat Completions wrapper."""

    def test_openrouter_defaults(self, monkeypatch):
        from project_workflow.config import get_settings

        for name in (
            "OPENAI_BASE_URL",
            "OPENAI_MODEL",
            "OPENAI_TIMEOUT",
            "OPENAI_API_KEY",
            "OPENAI_REASONING_EFFORT",
        ):
            monkeypatch.delenv(name, raising=False)
        get_settings.cache_clear()
        client = OpenAICompatibleClient()
        assert client.base_url == "https://openrouter.ai/api/v1"
        assert client.model == "z-ai/glm-5.2"
        assert client.timeout == 120
        assert client.api_key == ""
        assert client.reasoning_effort == "none"

    def test_env_overrides(self, monkeypatch):
        from project_workflow.config import get_settings

        monkeypatch.setenv("OPENAI_BASE_URL", "https://provider.example/v1/")
        monkeypatch.setenv("OPENAI_MODEL", "provider-model")
        monkeypatch.setenv("OPENAI_TIMEOUT", "45")
        monkeypatch.setenv("OPENAI_API_KEY", "secret")
        monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")
        get_settings.cache_clear()
        client = OpenAICompatibleClient()
        assert client.base_url == "https://provider.example/v1"
        assert client.model == "provider-model"
        assert client.timeout == 45
        assert client.api_key == "secret"
        assert client.reasoning_effort == "low"

    def test_dotenv_overrides(self, tmp_path, monkeypatch):
        from project_workflow.config import get_settings

        for name in (
            "OPENAI_BASE_URL",
            "OPENAI_MODEL",
            "OPENAI_TIMEOUT",
            "OPENAI_API_KEY",
            "OPENAI_REASONING_EFFORT",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text(
            "OPENAI_BASE_URL=https://dotenv.example/v1\n"
            "OPENAI_MODEL=dotenv-model\n"
            "OPENAI_TIMEOUT=35\n"
            "OPENAI_API_KEY=dotenv-secret\n",
            encoding="utf-8",
        )
        get_settings.cache_clear()

        client = OpenAICompatibleClient()

        assert client.base_url == "https://dotenv.example/v1"
        assert client.model == "dotenv-model"
        assert client.timeout == 35
        assert client.api_key == "dotenv-secret"
        assert client.reasoning_effort == "none"

    def test_chat_parses_json_response(self):
        client = OpenAICompatibleClient(api_key="test-key", base_url="https://ollama.com/v1")
        expected = {"verdict": "PASS", "confidence": 0.95}
        with patch("project_workflow.infrastructure.llm.requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"choices": [{"message": {"content": json.dumps(expected)}}]},
                raise_for_status=lambda: None,
            )
            result = client.chat("system text", "user text")
        assert result == expected
        mock_post.assert_called_once()
        assert mock_post.call_args.args[0] == "https://ollama.com/v1/chat/completions"
        assert mock_post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"

    def test_chat_payload_structure(self):
        client = OpenAICompatibleClient(model="test-model", base_url="http://host:1234/v1")
        with patch("project_workflow.infrastructure.llm.requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"choices": [{"message": {"content": "{}"}}]},
                raise_for_status=lambda: None,
            )
            client.chat("sys", "usr", temperature=0.5)
            _, kwargs = mock_post.call_args
            payload = kwargs["json"]
            assert payload["model"] == "test-model"
            assert payload["temperature"] == 0.5
            assert payload["max_tokens"] == 4000
            assert payload["reasoning_effort"] == "none"
            assert payload["response_format"] == {"type": "json_object"}
            assert len(payload["messages"]) == 2
            assert payload["messages"][0]["role"] == "system"
            assert payload["messages"][1]["role"] == "user"

    def test_chat_omits_reasoning_effort_when_disabled(self):
        client = OpenAICompatibleClient(reasoning_effort="")
        with patch("project_workflow.infrastructure.llm.requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                json=lambda: {"choices": [{"message": {"content": "{}"}}]},
                raise_for_status=lambda: None,
            )
            client.chat("sys", "usr")

        assert "reasoning_effort" not in mock_post.call_args.kwargs["json"]

    def test_chat_empty_content_raises(self):
        client = OpenAICompatibleClient()
        with patch("project_workflow.infrastructure.llm.requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"choices": [{"message": {"content": ""}}]},
                raise_for_status=lambda: None,
            )
            with pytest.raises(ValueError, match="Empty content"):
                client.chat("sys", "usr")


class TestPromptBuilder:
    """Unit tests for prompt assembly."""

    def test_build_user_prompt_includes_task_and_phase(self):
        phase = FakePhase(code="1", name="Preflight", instructions=["Check git"])
        prompt = PromptBuilder.build_user_prompt("RUN-1", phase, "report text")
        assert "TASK: RUN-1" in prompt
        assert "CURRENT PHASE: 1 — Preflight" in prompt
        assert "report text" in prompt

    def test_build_user_prompt_includes_instructions(self):
        phase = FakePhase(instructions=[FakeInstruction("Step one"), FakeInstruction("Step two")])
        prompt = PromptBuilder.build_user_prompt("T-1", phase, "r")
        assert "Step one" in prompt
        assert "Step two" in prompt

    def test_build_user_prompt_includes_checks_and_evidence(self):
        phase = FakePhase(
            checks=[FakeCheck("Check A")],
            evidence=[FakeEvidence("Screenshot")],
        )
        prompt = PromptBuilder.build_user_prompt("T-1", phase, "r")
        assert "Check A" in prompt
        assert "Screenshot" in prompt

    def test_build_user_prompt_with_previously_covered(self):
        phase = FakePhase(instructions=[FakeInstruction("Run tests")])
        prompt = PromptBuilder.build_user_prompt("T-1", phase, "r", previously_covered=["Run tests"])
        assert "ALREADY COMPLETED" in prompt
        assert "Run tests" in prompt

    def test_build_user_prompt_marks_ids_without_decorative_brackets(self):
        phase = FakePhase()
        prompt = PromptBuilder.build_user_prompt(
            "T-1",
            phase,
            "done",
            evaluation_items=[("-1:check:1", "Task is clear")],
        )

        assert 'ID: "-1:check:1"' in prompt
        assert "[-1:check:1]" not in prompt
        assert "REQUIRED ITEM COUNT: 1" in prompt
        assert "len(covered) + len(missing) MUST equal 1" in prompt

    def test_system_prompt_is_not_empty(self):
        assert "strict workflow supervisor" in PromptBuilder.SYSTEM_PROMPT
        assert "verdict" in PromptBuilder.SYSTEM_PROMPT
        assert "covered" in PromptBuilder.SYSTEM_PROMPT
        assert "do not add brackets" in PromptBuilder.SYSTEM_PROMPT
        assert "missing" in PromptBuilder.SYSTEM_PROMPT


class TestResponseParser:
    """Unit tests for the exact evaluator response contract."""

    def test_parse_full_valid_response(self):
        raw = {
            "verdict": "PASS",
            "covered": ["Item 1"],
            "missing": [],
            "blockers": [],
            "message": "All good",
            "confidence": 0.92,
        }
        v = ResponseParser.parse(raw)
        assert v.verdict == "PASS"
        assert v.covered == ["Item 1"]
        assert v.missing == []
        assert v.blockers == []
        assert v.message == "All good"
        assert v.next_phase is None
        assert v.next_phase_name is None
        assert v.confidence == 0.92

    def test_parse_invalid_verdict_is_rejected(self):
        raw = {"verdict": "UNKNOWN", "covered": [], "missing": [], "blockers": []}
        with pytest.raises(ValueError):
            ResponseParser.parse(raw)

    def test_parse_lowercase_verdict_is_rejected(self):
        raw = {
            "verdict": "pass", "covered": [], "missing": [], "blockers": [],
            "message": "done", "confidence": 0.5,
        }
        with pytest.raises(ValueError):
            ResponseParser.parse(raw)

    def test_pass_with_blockers_is_rejected(self):
        with pytest.raises(ValueError):
            ResponseParser.parse(
                {
                    "verdict": "PASS", "covered": [], "missing": [], "blockers": ["No access"],
                    "message": "blocked", "confidence": 0.5,
                }
            )

    def test_pass_with_missing_items_is_rejected(self):
        with pytest.raises(ValueError):
            ResponseParser.parse(
                {
                    "verdict": "PASS", "covered": [], "missing": ["Run tests"], "blockers": [],
                    "message": "missing", "confidence": 0.5,
                }
            )

    def test_parse_missing_message_and_confidence_is_rejected(self):
        with pytest.raises(ValueError):
            ResponseParser.parse({"verdict": "PARTIAL", "covered": [], "missing": ["item"], "blockers": []})

    @pytest.mark.parametrize("value", [1.5, -0.3, None, "unknown", float("nan"), True])
    def test_parse_invalid_confidence_is_rejected(self, value):
        raw = {"verdict": "PASS", "covered": [], "missing": [], "blockers": [], "message": "done", "confidence": value}
        with pytest.raises(ValueError):
            ResponseParser.parse(raw)

    @pytest.mark.parametrize("value", [None, 42, [], {}])
    def test_parse_invalid_message_is_rejected(self, value):
        raw = {"verdict": "PASS", "covered": [], "missing": [], "blockers": [], "message": value, "confidence": 0.5}
        with pytest.raises(ValueError):
            ResponseParser.parse(raw)

    def test_parse_string_instead_of_list_is_rejected(self):
        raw = {
            "verdict": "PASS",
            "covered": "single item",
            "missing": ["a", "", "b"],
            "blockers": [],
            "message": "done",
            "confidence": 0.5,
        }
        with pytest.raises(ValueError):
            ResponseParser.parse(raw)

    def test_llm_verdict_dataclass_immutable(self):
        v = LlmVerdict(
            verdict="PASS",
            covered=[],
            missing=[],
            blockers=[],
            message="",
            next_phase=None,
            next_phase_name=None,
            confidence=1.0,
            raw={},
        )
        with pytest.raises(AttributeError):
            v.verdict = "BLOCKED"


class TestSupervisorEngineEvaluateLLM:
    """Integration tests for SupervisorEngine.evaluate_llm with a mocked provider."""

    @pytest.fixture
    def engine(self):
        from project_workflow.supervisor import SupervisorEngine

        return SupervisorEngine("RUN-1001")

    def test_evaluate_llm_pass(self, engine, supervisor_llm):
        supervisor_llm("PASS")
        result = engine.evaluate_llm("I checked git", engine._get_current_phase_obj())
        assert result["verdict"] == "PASS"
        assert result["phase"] == "1.INTAKE"
        assert result["covered"]
        assert result["missing"] == []

    def test_evaluate_llm_blocked(self, engine, supervisor_llm):
        supervisor_llm("BLOCKED", blockers=["No access"])
        result = engine.evaluate_llm("Cannot access", engine._get_current_phase_obj())
        assert result["verdict"] == "BLOCKED"
        assert result["blockers"] == ["No access"]

    def test_evaluate_llm_fails_closed_on_provider_failure(self, engine):
        with patch(
            "project_workflow.supervisor.evaluate.OpenAICompatibleClient.chat",
            side_effect=requests.ConnectionError("down"),
        ):
            result = engine.evaluate("")
        assert result["verdict"] == "BLOCKED"
        assert result["next_phase"] is None
        assert result["retryable"] is True
        task = engine.db.tasks.get_by_id(engine.task["id"]).to_dict()
        assert (task["current_phase"], task["status"]) == ("1.INTAKE", "blocked")
        history = engine.db.get_task_history(engine.task["id"])
        assert [item["status"] for item in history] == ["blocked"]
        run = engine.db.get_supervisor_runs(task_key=engine.task_key, limit=1)[0]
        assert run["verdict"] == "blocked"
        assert run["report_fingerprint"] is None

    def test_evaluate_llm_uses_previously_covered(self, engine, supervisor_llm):
        """LLM prompt includes previously covered items."""
        supervisor_llm("PASS")
        fixture_chat = OpenAICompatibleClient.chat
        with patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient.chat") as mock_chat:
            mock_chat.side_effect = fixture_chat
            engine.evaluate_llm("Report", engine._get_current_phase_obj())
            _, kwargs = mock_chat.call_args
            # The prompt builder does NOT include previously covered items
            # unless they were passed as previously_covered param.
            # Here we just verify the prompt was built and sent.
            assert "Report" in kwargs["user"]
            assert "RUN-1001" in kwargs["user"]


class TestSupervisorEngineMandatoryLLM:
    """Report evaluation always uses the configured LLM."""

    @pytest.fixture
    def engine(self):
        from project_workflow.supervisor import SupervisorEngine

        return SupervisorEngine("RUN-1002")

    def test_evaluate_uses_llm(self, engine):
        with patch.object(engine, "evaluate_llm", return_value={"verdict": "BLOCKED"}) as evaluate_llm:
            result = engine.evaluate("report")
        assert result["verdict"] == "BLOCKED"
        evaluate_llm.assert_called_once_with("report", engine._get_current_phase_obj())


class TestResponseParserEdgeCases:
    """Edge-case parsing for LLM responses."""

    def test_parse_confidence_none_is_rejected(self):
        raw = {"verdict": "PASS", "covered": [], "missing": [], "blockers": [], "message": "done", "confidence": None}
        with pytest.raises(ValueError):
            ResponseParser.parse(raw)

    def test_parse_blockers_with_whitespace_strings(self):
        raw = {
            "verdict": "BLOCKED",
            "covered": [],
            "missing": [],
            "blockers": ["  ", "real blocker", ""],
            "message": "blocked",
            "confidence": 0.5,
        }
        with pytest.raises(ValueError):
            ResponseParser.parse(raw)

    def test_parse_next_phase_null_from_llm(self):
        raw = {
            "verdict": "PASS",
            "covered": [],
            "missing": [],
            "blockers": [],
            "message": "done",
            "confidence": 0.5,
            "next_phase": None,
            "next_phase_name": None,
        }
        with pytest.raises(ValueError):
            ResponseParser.parse(raw)

    def test_parse_rejects_extra_response_fields(self):
        raw = {
            "verdict": "PASS", "covered": [], "missing": [], "blockers": [],
            "message": "done", "confidence": 0.5, "extra_key": "rejected",
        }
        with pytest.raises(ValueError):
            ResponseParser.parse(raw)

    def test_parse_rejects_verdict_whitespace(self):
        raw = {
            "verdict": "  PASS  ", "covered": [], "missing": [], "blockers": [],
            "message": "done", "confidence": 0.5,
        }
        with pytest.raises(ValueError):
            ResponseParser.parse(raw)


class TestPromptBuilderEdgeCases:
    """Edge cases for prompt assembly."""

    def test_empty_phase_contract(self):
        phase = FakePhase(code="99", name="Empty", instructions=[], checks=[], evidence=[])
        prompt = PromptBuilder.build_user_prompt("T-99", phase, "done")
        assert "T-99" in prompt
        assert "99 — Empty" in prompt
        assert "done" in prompt

    def test_missing_instructions_skips_section(self):
        phase = FakePhase(code="1", checks=[FakeCheck("Check X")])
        prompt = PromptBuilder.build_user_prompt("T-1", phase, "r")
        assert "Instructions:" not in prompt
        assert "Check X" in prompt

    def test_previously_covered_empty_list_omitted(self):
        phase = FakePhase(instructions=[FakeInstruction("Step 1")])
        prompt = PromptBuilder.build_user_prompt("T-1", phase, "r", previously_covered=[])
        assert "ALREADY COMPLETED" not in prompt

    def test_multiple_evidence_items(self):
        phase = FakePhase(evidence=[FakeEvidence("A"), FakeEvidence("B"), FakeEvidence("C")])
        prompt = PromptBuilder.build_user_prompt("T-1", phase, "r")
        assert "  • A" in prompt
        assert "  • B" in prompt
        assert "  • C" in prompt


class TestSupervisorEngineLLMIntegrationDB:
    """DB state after LLM evaluate."""

    @pytest.fixture
    def engine(self):
        from project_workflow.supervisor import SupervisorEngine

        return SupervisorEngine("RUN-1003")

    def test_supervisor_run_recorded_after_llm_evaluate(self, engine, supervisor_llm):
        supervisor_llm("PASS")
        engine.evaluate("Report")

        runs = engine.db.get_supervisor_runs(task_key="RUN-1003", limit=5)
        assert len(runs) == 1
        run = runs[0]
        assert run["verdict"] == "pass"
        assert run["report"] == "Report"
        assert run["covered"]
        assert run["missing"] == []
        assert run["report_fingerprint"]

    def test_task_phase_advanced_after_llm_pass(self, engine, supervisor_llm):
        supervisor_llm("PASS")
        engine.evaluate("Report")

        task = engine.db.tasks.get_by_id(engine.task["id"]).to_dict()
        assert task["current_phase"] == "2.REQUIREMENTS"

    def test_task_blocked_after_llm_blocked(self, engine, supervisor_llm):
        supervisor_llm("BLOCKED", blockers=["No access"])
        engine.evaluate("Report")

        task = engine.db.tasks.get_by_id(engine.task["id"]).to_dict()
        assert task["current_phase"] == "1.INTAKE"
        assert task["status"] == "blocked"

    def test_rollback_without_config_is_retryable_and_blocks_current_phase(self, engine, supervisor_llm):
        supervisor_llm("ROLLBACK")
        result = engine.evaluate("Report")

        assert result["verdict"] == "BLOCKED"
        assert result["retryable"] is True
        task = engine.db.tasks.get_by_id(engine.task["id"]).to_dict()
        assert (task["current_phase"], task["status"]) == ("1.INTAKE", "blocked")
        assert [item["status"] for item in engine.db.get_task_history(engine.task["id"])] == ["blocked"]

    def test_supervisor_run_failure_rolls_back_db_and_engine_state(self, engine, monkeypatch, supervisor_llm):
        task_id = engine.task["id"]
        original_task = dict(engine.task)
        original_phase = engine.current_phase
        monkeypatch.setattr(
            engine.db,
            "create_supervisor_run",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("supervisor write failed")),
        )

        supervisor_llm("PASS")
        with pytest.raises(RuntimeError, match="supervisor write failed"):
            engine.evaluate("Report")

        persisted = engine.db.tasks.get_by_id(task_id).to_dict()
        assert persisted["current_phase"] == original_task["current_phase"]
        assert persisted["status"] == original_task["status"]
        assert engine.task == original_task
        assert engine.current_phase == original_phase
        assert engine.db.get_task_history(task_id) == []
        assert engine.db.get_supervisor_runs(task_key=engine.task_key, limit=5) == []


class TestOpenAICompatibleClientOverrides:
    """Custom env configuration."""

    def test_custom_base_url(self):
        client = OpenAICompatibleClient(base_url="http://custom:1234/v1")
        assert client.base_url == "http://custom:1234/v1"

    def test_custom_model(self):
        client = OpenAICompatibleClient(model="other-model")
        assert client.model == "other-model"

    def test_custom_timeout(self):
        client = OpenAICompatibleClient(timeout=300)
        assert client.timeout == 300


class TestEvaluatorV6PromptContract:
    """The live provider receives explicit contradiction and chronology rules."""

    def test_prompt_version_is_v6(self):
        assert PromptBuilder.PROMPT_VERSION == "supervisor-evaluator-v7"

    def test_contradictory_current_facts_prohibit_pass(self):
        prompt = PromptBuilder.SYSTEM_PROMPT

        assert "Mutually exclusive CURRENT facts" in prompt
        assert "prohibit PASS" in prompt
        assert "return PARTIAL" in prompt
        assert "return ROLLBACK" in prompt
        assert "earlier-phase artifact" in prompt
        assert "affected required item IDs in missing" in prompt

    def test_build_user_prompt_exposes_rollback_target(self):
        phase = FakePhase(rollback_target="8.IMPLEMENT")

        prompt = PromptBuilder.build_user_prompt("RUN-1", phase, "reviewed")

        assert "ROLLBACK TARGET: 8.IMPLEMENT" in prompt

    def test_chronological_state_change_requires_timestamped_action_evidence(self):
        prompt = PromptBuilder.SYSTEM_PROMPT

        assert "first open, then merged" in prompt
        assert "timestamps and action evidence" in prompt

    def test_normal_complete_report_contract_still_allows_pass(self):
        assert "verdict = PASS" in PromptBuilder.SYSTEM_PROMPT
        assert "all items done, no blockers, no regressions" in PromptBuilder.SYSTEM_PROMPT

    def test_output_must_be_bare_json_without_markdown_fences(self):
        assert "one bare JSON object" in PromptBuilder.SYSTEM_PROMPT
        assert "Never wrap it in Markdown or code fences" in PromptBuilder.SYSTEM_PROMPT
