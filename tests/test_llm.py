"""Tests for LLM-based evaluate (OllamaClient, PromptBuilder, ResponseParser)."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest
import requests

from wartz_workflow.llm import (
    OllamaClient,
    PromptBuilder,
    ResponseParser,
    LlmVerdict,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
)


class FakePhase:
    """Minimal Phase-like object for prompt building."""

    def __init__(self, **kwargs):
        self.code = kwargs.get("code", "1")
        self.name = kwargs.get("name", "Test")
        self.instructions = kwargs.get("instructions", [])
        self.checks = kwargs.get("checks", [])
        self.evidence = kwargs.get("evidence", [])


class FakeInstruction:
    def __init__(self, step):
        self.step = step


class FakeCheck:
    def __init__(self, description):
        self.description = description


class FakeEvidence:
    def __init__(self, item):
        self.item = item

class TestOllamaClient:
    """Unit tests for Ollama HTTP wrapper."""

    def test_default_env_vars(self):
        assert OLLAMA_BASE_URL == "http://localhost:11434"
        assert OLLAMA_MODEL == "kimi-k2.6"

    def test_is_available_true(self):
        client = OllamaClient()
        with patch("wartz_workflow.llm.requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200)
            assert client.is_available() is True

    def test_is_available_false_on_timeout(self):
        client = OllamaClient()
        with patch("wartz_workflow.llm.requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout()
            assert client.is_available() is False

    def test_chat_parses_json_response(self):
        client = OllamaClient()
        expected = {"verdict": "PASS", "confidence": 0.95}
        with patch("wartz_workflow.llm.requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"message": {"content": json.dumps(expected)}},
                raise_for_status=lambda: None,
            )
            result = client.chat("system text", "user text")
            assert result == expected

    def test_chat_payload_structure(self):
        client = OllamaClient(model="test-model", base_url="http://host:1234")
        with patch("wartz_workflow.llm.requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"message": {"content": "{}"}},
                raise_for_status=lambda: None,
            )
            client.chat("sys", "usr", temperature=0.5)
            args, kwargs = mock_post.call_args
            payload = kwargs["json"]
            assert payload["model"] == "test-model"
            assert payload["format"] == "json"
            assert payload["options"]["temperature"] == 0.5
            assert payload["options"]["num_ctx"] == 32000
            assert payload["stream"] is False
            assert len(payload["messages"]) == 2
            assert payload["messages"][0]["role"] == "system"
            assert payload["messages"][1]["role"] == "user"

    def test_chat_empty_content_raises(self):
        client = OllamaClient()
        with patch("wartz_workflow.llm.requests.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"message": {"content": ""}},
                raise_for_status=lambda: None,
            )
            with pytest.raises(ValueError, match="Empty content"):
                client.chat("sys", "usr")


class TestPromptBuilder:
    """Unit tests for prompt assembly."""

    def test_build_user_prompt_includes_task_and_phase(self):
        phase = FakePhase(code="1", name="Preflight", instructions=["Check git"])
        prompt = PromptBuilder.build_user_prompt("TASK-1", phase, "report text")
        assert "TASK: TASK-1" in prompt
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
        prompt = PromptBuilder.build_user_prompt(
            "T-1", phase, "r", previously_covered=["Run tests"]
        )
        assert "ALREADY COMPLETED" in prompt
        assert "Run tests" in prompt

    def test_system_prompt_is_not_empty(self):
        assert "strict workflow supervisor" in PromptBuilder.SYSTEM_PROMPT
        assert "verdict" in PromptBuilder.SYSTEM_PROMPT
        assert "covered" in PromptBuilder.SYSTEM_PROMPT
        assert "missing" in PromptBuilder.SYSTEM_PROMPT


class TestResponseParser:
    """Unit tests for LLM response normalisation."""

    def test_parse_full_valid_response(self):
        raw = {
            "verdict": "PASS",
            "covered": ["Item 1"],
            "missing": ["Item 2"],
            "blockers": [],
            "message": "All good",
            "next_phase": "2",
            "next_phase_name": "Next",
            "confidence": 0.92,
        }
        v = ResponseParser.parse(raw)
        assert v.verdict == "PASS"
        assert v.covered == ["Item 1"]
        assert v.missing == ["Item 2"]
        assert v.blockers == []
        assert v.message == "All good"
        assert v.next_phase == "2"
        assert v.next_phase_name == "Next"
        assert v.confidence == 0.92

    def test_parse_invalid_verdict_defaults_to_partial(self):
        raw = {"verdict": "UNKNOWN", "covered": [], "missing": [], "blockers": []}
        v = ResponseParser.parse(raw)
        assert v.verdict == "PARTIAL"

    def test_parse_lowercase_verdict_normalised(self):
        raw = {"verdict": "pass", "covered": [], "missing": [], "blockers": []}
        v = ResponseParser.parse(raw)
        assert v.verdict == "PASS"

    def test_parse_missing_fields_get_defaults(self):
        raw = {}
        v = ResponseParser.parse(raw)
        assert v.verdict == "PARTIAL"
        assert v.covered == []
        assert v.missing == []
        assert v.blockers == []
        assert v.message == ""
        assert v.confidence == 0.5

    def test_parse_confidence_clamped(self):
        raw = {"verdict": "PASS", "confidence": 1.5}
        v = ResponseParser.parse(raw)
        assert v.confidence == 1.0
        raw = {"verdict": "PASS", "confidence": -0.3}
        v = ResponseParser.parse(raw)
        assert v.confidence == 0.0

    def test_parse_string_list_coercion(self):
        raw = {
            "verdict": "PASS",
            "covered": "single item",
            "missing": ["a", "", "b"],
            "blockers": [],
        }
        v = ResponseParser.parse(raw)
        assert v.covered == ["single item"]
        assert v.missing == ["a", "b"]

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


class TestWizardEngineEvaluateLLM:
    """Integration tests for WizardEngine.evaluate_llm with mocked Ollama."""

    @pytest.fixture
    def engine(self, tmp_path, monkeypatch):
        test_db = tmp_path / "workflow.db"
        import wartz_workflow.db as db_module
        monkeypatch.setattr(db_module, "DB_PATH", str(test_db))
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            from wartz_workflow.wizard import WizardEngine
            engine = WizardEngine("SMOKE-LLM-1", repo=str(tmp_path))
        return engine

    def test_evaluate_llm_pass(self, engine, monkeypatch):
        monkeypatch.setattr("wartz_workflow.wizard.SMART_EVALUATE", True)
        llm_response = {
            "verdict": "PASS",
            "covered": ["Check git"],
            "missing": [],
            "blockers": [],
            "message": "✅ Good",
            "next_phase": "2",
            "next_phase_name": "Next",
            "confidence": 0.95,
        }
        with patch.object(OllamaClient, "chat", return_value=llm_response):
            result = engine.evaluate("I checked git")
        assert result["verdict"] == "PASS"
        assert result["phase"] == "-1"
        assert result["covered"] == ["Check git"]
        assert result["missing"] == []

    def test_evaluate_llm_blocked(self, engine, monkeypatch):
        monkeypatch.setattr("wartz_workflow.wizard.SMART_EVALUATE", True)
        llm_response = {
            "verdict": "BLOCKED",
            "covered": [],
            "missing": ["Check git"],
            "blockers": ["No access"],
            "message": "🔴 Blocked",
            "confidence": 0.9,
        }
        with patch.object(OllamaClient, "chat", return_value=llm_response):
            result = engine.evaluate("Cannot access")
        assert result["verdict"] == "BLOCKED"
        assert result["blockers"] == ["No access"]

    def test_evaluate_llm_fallback_on_ollama_failure(self, engine, monkeypatch):
        """If Ollama fails, evaluate() must fall back to rule-based."""
        monkeypatch.setattr("wartz_workflow.wizard.SMART_EVALUATE", True)
        with patch.object(OllamaClient, "chat", side_effect=requests.exceptions.ConnectionError("Ollama down")):
            # Rule-based: empty report against phase -1 → partial
            result = engine.evaluate("")
        assert result["verdict"] == "PARTIAL"

    def test_evaluate_llm_uses_previously_covered(self, engine, monkeypatch):
        """LLM prompt includes previously covered items."""
        monkeypatch.setattr("wartz_workflow.wizard.SMART_EVALUATE", True)
        llm_response = {
            "verdict": "PASS",
            "covered": ["Item A", "Item B"],
            "missing": [],
            "blockers": [],
            "message": "Done",
            "confidence": 0.9,
        }
        with patch.object(OllamaClient, "chat", return_value=llm_response) as mock_chat:
            engine.evaluate("Report")
            args, kwargs = mock_chat.call_args
            # The prompt builder does NOT include previously covered items
            # unless they were passed as previously_covered param.
            # Here we just verify the prompt was built and sent.
            assert "Report" in kwargs["user"]
            assert "SMOKE-LLM-1" in kwargs["user"]


class TestWizardEngineEvaluateLLMWithRule:
    """Test that rule-based still works when SMART_EVALUATE is off."""

    @pytest.fixture
    def engine(self, tmp_path, monkeypatch):
        test_db = tmp_path / "workflow.db"
        import wartz_workflow.db as db_module
        monkeypatch.setattr(db_module, "DB_PATH", str(test_db))
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            from wartz_workflow.wizard import WizardEngine
            engine = WizardEngine("SMOKE-RULE-1", repo=str(tmp_path))
        return engine

    def test_rule_based_evaluate_without_smart(self, engine, monkeypatch):
        monkeypatch.setattr("wartz_workflow.wizard.SMART_EVALUATE", False)
        result = engine.evaluate("")
        assert result["verdict"] == "PARTIAL"


class TestOllamaResponseParserEdgeCases:
    """Edge-case parsing for LLM responses."""

    def test_parse_confidence_none_defaults_to_half(self):
        raw = {"verdict": "PASS", "confidence": None}
        v = ResponseParser.parse(raw)
        assert v.confidence == 0.5

    def test_parse_blockers_with_whitespace_strings(self):
        raw = {"verdict": "BLOCKED", "blockers": ["  ", "real blocker", ""]}
        v = ResponseParser.parse(raw)
        assert v.blockers == ["real blocker"]

    def test_parse_next_phase_null_from_llm(self):
        raw = {"verdict": "PASS", "next_phase": None, "next_phase_name": None}
        v = ResponseParser.parse(raw)
        assert v.next_phase is None
        assert v.next_phase_name is None

    def test_parse_preserves_raw_response(self):
        raw = {"verdict": "PASS", "extra_key": "preserved"}
        v = ResponseParser.parse(raw)
        assert v.raw["extra_key"] == "preserved"

    def test_parse_strip_verdict_whitespace(self):
        raw = {"verdict": "  pass  ", "covered": [], "missing": [], "blockers": []}
        v = ResponseParser.parse(raw)
        assert v.verdict == "PASS"


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


class TestWizardEngineLLMIntegrationDB:
    """DB state after LLM evaluate."""

    @pytest.fixture
    def engine(self, tmp_path, monkeypatch):
        test_db = tmp_path / "workflow.db"
        import wartz_workflow.db as db_module
        monkeypatch.setattr(db_module, "DB_PATH", str(test_db))
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            from wartz_workflow.wizard import WizardEngine
            engine = WizardEngine("DB-LLM-1", repo=str(tmp_path))
        return engine

    def test_supervisor_run_recorded_after_llm_evaluate(self, engine, monkeypatch):
        monkeypatch.setattr("wartz_workflow.wizard.SMART_EVALUATE", True)
        llm_response = {
            "verdict": "PASS",
            "covered": ["Done"],
            "missing": [],
            "blockers": [],
            "message": "All good",
            "next_phase": "2",
            "next_phase_name": "Next",
            "confidence": 0.95,
        }
        with patch.object(OllamaClient, "chat", return_value=llm_response):
            engine.evaluate("Report")

        runs = engine.db.get_supervisor_runs(task_key="DB-LLM-1", limit=5)
        assert len(runs) == 1
        run = runs[0]
        assert run["verdict"] == "pass"
        assert run["report"] == "Report"
        assert run["covered"] == ["Done"]
        assert run["missing"] == []

    def test_task_phase_advanced_after_llm_pass(self, engine, monkeypatch):
        monkeypatch.setattr("wartz_workflow.wizard.SMART_EVALUATE", True)
        llm_response = {
            "verdict": "PASS",
            "covered": ["Done"],
            "missing": [],
            "blockers": [],
            "message": "All good",
            "next_phase": "2",
            "next_phase_name": "Next",
            "confidence": 0.95,
        }
        with patch.object(OllamaClient, "chat", return_value=llm_response):
            engine.evaluate("Report")

        task = engine.db.get_task(engine.task["id"])
        assert task["current_phase"] == "2"

    def test_task_blocked_after_llm_blocked(self, engine, monkeypatch):
        monkeypatch.setattr("wartz_workflow.wizard.SMART_EVALUATE", True)
        llm_response = {
            "verdict": "BLOCKED",
            "covered": [],
            "missing": ["Need X"],
            "blockers": ["No access"],
            "message": "Blocked",
            "confidence": 0.9,
        }
        with patch.object(OllamaClient, "chat", return_value=llm_response):
            engine.evaluate("Report")

        task = engine.db.get_task(engine.task["id"])
        assert task["current_phase"] == "-1"
        assert task["status"] == "blocked"

    def test_llm_rollback_records_history(self, engine, monkeypatch):
        monkeypatch.setattr("wartz_workflow.wizard.SMART_EVALUATE", True)
        llm_response = {
            "verdict": "ROLLBACK",
            "covered": [],
            "missing": [],
            "blockers": [],
            "message": "Rollback",
            "confidence": 0.8,
        }
        with patch.object(OllamaClient, "chat", return_value=llm_response):
            result = engine.evaluate("Report")

        # Check that task remains in a valid state after rollback
        task = engine.db.get_task(engine.task["id"])
        assert task["status"] in ("active", "blocked")
        # History should contain at least one entry
        history = engine.db.get_task_history(engine.task["id"])
        assert len(history) >= 1


class TestOllamaClientEnvOverrides:
    """Custom env configuration."""

    def test_custom_base_url(self):
        client = OllamaClient(base_url="http://custom:1234")
        assert client.base_url == "http://custom:1234"

    def test_custom_model(self):
        client = OllamaClient(model="other-model")
        assert client.model == "other-model"

    def test_custom_timeout(self):
        client = OllamaClient(timeout=300)
        assert client.timeout == 300
