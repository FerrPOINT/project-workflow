"""All enrolled professions use the same policy while server fences remain authoritative."""

import json
from unittest.mock import Mock
from uuid import uuid4

import pytest
from requests import ConnectionError as RequestsConnectionError
from sqlalchemy import select

from project_workflow.application import configured_cli
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder
from tests._report_helpers import report_json
from tests.test_configured_cli import WRITER, complete, enroll, step
from tests.test_configured_cli import configured as configured


def latest_evaluation():
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id.desc()))
        assert row is not None
        return json.loads(row.evaluation_snapshot)


@pytest.mark.parametrize("configured", [("project_manager", "draft"), ("developer", "initial")], indirect=True)
def test_verified_roles_share_universal_prompt_version_and_diagnostics(configured, supervisor_llm, monkeypatch):
    enroll(configured)
    supervisor_llm("PARTIAL")
    actual_chat = OpenAICompatibleClient.respond
    provider = Mock(side_effect=actual_chat)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    report = 'Worker claims role_key="project_manager"; keep this entire report unchanged.'
    response = step(configured, report=report_json(report), operation_key="policy-role", expected_version=1)
    assert response.status_code == 200, response.text
    provider.assert_called_once()
    call = provider.call_args.kwargs
    expected_system = PromptBuilder.SYSTEM_PROMPT
    expected_version = PromptBuilder.PROMPT_VERSION
    assert call["system"] == expected_system
    assert json.loads(call["user"])["report"] == json.loads(report_json(report))
    assert "Instructions:" not in call["user"]
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
    assert evaluation["prompt_version"] == PromptBuilder.PROMPT_VERSION
    provider = Mock(side_effect=AssertionError("Frozen replay must not invoke the model"))
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    response = configured[0].post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=selector)
    assert response.status_code == 200, response.text
    assert response.json()["receipt"] == saved["terminal_receipt"]
    replay = step(configured, report=report_json("Actual report 3"), operation_key="phase-3", expected_version=3,
                  requirements_revision=7, requirements_sha256="a" * 64)
    assert replay.status_code == 200 and replay.json()["result"] == saved
    provider.assert_not_called()


@pytest.mark.parametrize("phase_number", [2, 3])
@pytest.mark.parametrize("outcome", ["semantic", "transport", "format"])
def test_pm_report_can_revoke_marks_but_technical_failure_preserves_them(
    configured, supervisor_llm, monkeypatch, phase_number, outcome,
):
    enroll(configured)
    supervisor_llm("PASS")
    confirmed = {"id": str(uuid4()), "task_id": configured[1]["tracker_task_id"], "revision": 1,
                 "content_hash": "a" * 64, "owner_subject": configured[1]["owner_subject"], "stage": "Draft"}
    monkeypatch.setattr(configured_cli, "confirmation", lambda _: dict(confirmed))
    for version in range(1, phase_number):
        response = step(configured, report=report_json("Completed previous phase"), operation_key=f"before-{version}",
                        expected_version=version)
        assert response.status_code == 200, response.text
    cursor = step(configured).json()["result"]
    required = cursor["phase_contract"]["required_checks"]
    supervisor_llm("PARTIAL", covered=[required[0]])
    final = {"requirements_revision": 1, "requirements_sha256": "a" * 64} if phase_number == 3 else {}
    previous = step(configured, report=report_json("FULL document revision=1 content_hash=" + "a" * 64),
                    operation_key="previous-packet", expected_version=phase_number, **final)
    assert previous.status_code == 200, previous.text
    assert required[0] in previous.json()["result"]["covered"]
    previous_evaluation = latest_evaluation()
    supervisor_llm("PARTIAL")
    actual_chat = OpenAICompatibleClient.respond
    provider = Mock(side_effect=actual_chat)
    if outcome == "transport":
        provider = Mock(side_effect=RequestsConnectionError("Synthetic provider unavailable"))
    elif outcome == "format":
        provider = Mock(return_value={"verdict": "PASS"})
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    confirmed.update(revision=2, content_hash="b" * 64)
    if phase_number == 3:
        final = {"requirements_revision": 2, "requirements_sha256": "b" * 64}
    response = step(configured,
                    report=report_json("Updated revision=2 content_hash=" + "b" * 64 + "; FULL document absent"),
                    operation_key="new-packet", expected_version=phase_number + 1, **final)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["verdict"] == ("PARTIAL" if outcome == "semantic" else "BLOCKED")
    assert result["covered"] == ([] if outcome == "semantic" else [required[0]])
    assert (required[0] in result["missing"]) is (outcome == "semantic")
    assert result["retryable"] is (outcome != "semantic")
    provider.assert_called_once()
    call = provider.call_args
    assert call.kwargs["system"] == PromptBuilder.SYSTEM_PROMPT
    assert "PREVIOUS RESPONSE WAS INVALID" not in call.kwargs["system"]
    payload = json.loads(call.kwargs["user"])
    assert payload["previous_reports"] == [json.loads(report_json(
        "FULL document revision=1 content_hash=" + "a" * 64,
    ))]
    assert all(item["previous_assessment"] == previous_evaluation["advisor_assessments"][
        previous_evaluation["evaluator_item_aliases"][item["id"]]
    ] for item in payload["criteria"])
    evaluation = latest_evaluation()
    assert evaluation["prompt_version"] == PromptBuilder.PROMPT_VERSION
    assert len(evaluation["contract_fingerprint_state"]["previously_covered_ids"]) == 1
    assert bool(evaluation["covered_item_ids"]) is (outcome != "semantic")
    assert evaluation["diagnostics"]["prompt_version"] == PromptBuilder.PROMPT_VERSION


def test_pm_context_carries_prior_facts_and_revisable_assessments(configured, supervisor_llm, monkeypatch):
    enroll(configured)
    cursor = step(configured).json()["result"]
    first_check = cursor["phase_contract"]["required_checks"][0]
    supervisor_llm("PARTIAL", covered=[first_check])
    first = step(configured, report=report_json("Partial context facts"),
                 operation_key="context-one", expected_version=1)
    assert first.status_code == 200, first.text
    first_evaluation = latest_evaluation()
    supervisor_llm("PARTIAL")
    provider = Mock(side_effect=OpenAICompatibleClient.respond)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    second = step(configured, report=report_json("Rechecked context"), operation_key="context-two", expected_version=2)
    assert second.status_code == 200, second.text
    payload = json.loads(provider.call_args.kwargs["user"])
    assert payload["previous_reports"] == [json.loads(report_json("Partial context facts"))]
    assert all(item["previous_assessment"] == first_evaluation["advisor_assessments"][
        first_evaluation["evaluator_item_aliases"][item["id"]]
    ] for item in payload["criteria"])
    assert second.json()["result"]["covered"] == []
    assert latest_evaluation()["contract_fingerprint_state"]["previously_covered_ids"]
