"""Tests for reasoning integration into LLM evaluate."""

from __future__ import annotations

from unittest.mock import patch

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.wizard.core import WizardEngine


def test_evaluate_llm_with_reasoning_uses_reasoning_result(monkeypatch):
    uow = SAUnitOfWork()
    uow.create_all()

    engine = WizardEngine("REAS-1", uow=uow)
    phase = engine._get_current_phase_obj()
    assert phase is not None
    reasoning_json = {
        "analysis": "Report omits evidence",
        "claims": [{"item": "done X", "matches": ["Check A"], "valid": True}],
        "blockers": [],
        "missing": ["Evidence 1"],
        "verdict": "PARTIAL",
        "confidence": 0.75,
        "next_steps": ["Attach Evidence 1"],
    }

    call_index = {"n": 0}

    def fake_chat(*, system, user, temperature=0.0, **kwargs):
        call_index["n"] += 1
        if "internal reviewer" in system or "внутренний рецензент" in system:
            return reasoning_json
        # Second call is legacy evaluate; we won't let it happen.
        return reasoning_json

    monkeypatch.setattr("project_workflow.config.SMART_REASONING", True)
    with patch("project_workflow.wizard.evaluate.OllamaClient") as mock_client:
        client = mock_client.return_value
        client.chat.side_effect = fake_chat
        result = engine.evaluate_llm("I did X.", phase)

    assert result["verdict"] == "PARTIAL"
    assert result["confidence"] == 0.75
    assert "Attach Evidence 1" in result.get("next_steps", [])
    assert "Evidence 1" in result.get("missing", [])
    assert result["phase"] == phase.code
