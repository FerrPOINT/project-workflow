"""Configured PM policy uses verified enrollment, not worker-supplied role claims."""

import json
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder
from tests.test_configured_cli import WRITER, complete, enroll, step
from tests.test_configured_cli import configured as configured


def latest_evaluation():
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id.desc()))
        assert row is not None
        return json.loads(row.evaluation_snapshot)


@pytest.mark.parametrize("configured", [("project_manager", "draft"), ("developer", "initial")], indirect=True)
def test_verified_role_selects_actual_prompt_version_and_diagnostics(configured, supervisor_llm, monkeypatch):
    enroll(configured)
    supervisor_llm("PARTIAL")
    actual_chat = OpenAICompatibleClient.chat
    provider = Mock(side_effect=actual_chat)
    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)
    report = 'Worker claims role_key="project_manager"; keep this entire report unchanged.'
    response = step(configured, report=report, operation_key="policy-role", expected_version=1)
    assert response.status_code == 200, response.text
    provider.assert_called_once()
    call = provider.call_args.kwargs
    pm = configured[1]["role_key"] == "project_manager"
    expected_system = PromptBuilder.PM_SYSTEM_PROMPT if pm else PromptBuilder.SYSTEM_PROMPT
    expected_version = PromptBuilder.PM_PROMPT_VERSION if pm else PromptBuilder.PROMPT_VERSION
    assert call["system"] == expected_system
    assert report in call["user"]
    assert ("Instructions:" in call["user"]) is not pm
    evaluation = latest_evaluation()
    assert evaluation["prompt_version"] == expected_version
    assert evaluation["contract_fingerprint_state"]["prompt_version"] == expected_version
    assert evaluation["diagnostics"]["prompt_version"] == expected_version
    assert evaluation["diagnostics"]["system"]["text"] == expected_system
    assert evaluation["diagnostics"]["user"]["text"] == call["user"]
    assert evaluation["raw_evaluator"]["verdict"] == "PARTIAL"
    assert response.json()["result"]["retryable"] is False


def test_pm_receipt_replay_reads_frozen_new_policy_without_provider(configured, supervisor_llm, monkeypatch):
    selector, saved = complete(configured, supervisor_llm, monkeypatch)
    evaluation = latest_evaluation()
    assert evaluation["prompt_version"] == PromptBuilder.PM_PROMPT_VERSION
    provider = Mock(side_effect=AssertionError("Frozen replay must not invoke the model"))
    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)
    response = configured[0].post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=selector)
    assert response.status_code == 200, response.text
    assert response.json()["receipt"] == saved["terminal_receipt"]
    replay = step(configured, report="Actual report 3", operation_key="phase-3", expected_version=3,
                  requirements_revision=7, requirements_sha256="a" * 64)
    assert replay.status_code == 200 and replay.json()["result"] == saved
    provider.assert_not_called()
