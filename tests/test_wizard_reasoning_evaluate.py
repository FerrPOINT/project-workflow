"""Compatibility check for the retired alternate reasoning path."""

from __future__ import annotations

from unittest.mock import patch

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.wizard.core import WizardEngine


def test_smart_reasoning_flag_does_not_select_an_alternate_evaluator(monkeypatch):
    uow = SAUnitOfWork()
    uow.create_all()

    engine = WizardEngine("REAS-1", uow=uow)
    phase = engine._get_current_phase_obj()
    assert phase is not None
    response = {
        "covered": ["done X"],
        "blockers": [],
        "missing": ["Evidence 1"],
        "verdict": "PARTIAL",
        "message": "Report omits evidence",
        "confidence": 0.75,
    }

    call_index = {"n": 0}

    def fake_chat(*, system, user, temperature=0.0, **kwargs):
        call_index["n"] += 1
        return response

    monkeypatch.setattr("project_workflow.config.SMART_REASONING", True)
    with patch("project_workflow.wizard.evaluate.OllamaClient") as mock_client:
        client = mock_client.return_value
        client.chat.side_effect = fake_chat
        result = engine.evaluate_llm("I did X.", phase)

    assert result["verdict"] == "PARTIAL"
    assert result["confidence"] == 0.75
    assert "Evidence 1" in result.get("missing", [])
    assert result["phase"] == phase.code
    assert call_index["n"] == 1
