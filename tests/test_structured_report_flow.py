"""Actual configured HTTP admission, persistence and authorized historical readback."""

import json
from unittest.mock import Mock

import pytest
from sqlalchemy import func, select

from project_workflow.domain.configured_cli import ConfiguredStep
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.supervisor.evaluate import _report_fingerprint
from tests.test_configured_cli import MACHINE, enroll, step
from tests.test_configured_cli import configured as configured


def report(content=None, *, source="Original request", unresolved=None):
    return json.dumps({
        "source": {"request": source, "decisions": []},
        "result": {"artifacts": [] if content is None else [{"name": "document", "content": content}],
                   "assumptions": []},
        "unresolved": [{"kind": "question", "text": text} for text in (unresolved or [])],
    }, ensure_ascii=False)


@pytest.mark.parametrize("raw", [
    "free text", "{}",
    '{"source":{"request":"","decisions":[]},'
    '"result":{"artifacts":[],"assumptions":[]},"unresolved":[3]}',
    r'{"source":{"request":"\ud800","decisions":[]},'
    r'"result":{"artifacts":[],"assumptions":[]},"unresolved":[]}',
    '{"source":{"request":"","decisions":[]},'
    '"result":{"artifacts":[{"name":"document","content":{"x":1,"x":2}}],"assumptions":[]},"unresolved":[]}',
])
def test_malformed_report_does_not_call_model_or_commit_operation(configured, monkeypatch, raw):
    enroll(configured)
    before = step(configured).json()["result"]
    model = Mock(side_effect=AssertionError("Malformed report must not reach Advisor"))
    monkeypatch.setattr(OpenAICompatibleClient, "chat", model)
    response = step(configured, report=raw, operation_key="invalid-report", expected_version=before["version"])
    assert response.status_code == 422, response.text
    assert response.json()["error_code"] == "invalid-phase-report"
    model.assert_not_called()
    after = step(configured).json()["result"]
    assert (after["version"], after["phase_code"], after["status"]) == (
        before["version"], before["phase_code"], before["status"])
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 0


def test_structured_report_is_preserved_once_through_evaluation_and_readback(configured, monkeypatch):
    enroll(configured)
    raw = report({"title": "Исходный документ", "rules": ["one", "two"], "approved": False},
                 unresolved=["Какое ограничение выбрано?"])
    expected = json.loads(raw)
    requests = []

    def advisor(self, *, user, **kwargs):
        payload = json.loads(user)
        requests.append(payload)
        assert payload["report"] == expected
        return {"verdict": "PARTIAL", "assessments": {
            item["id"]: {"covered": False, "reason": "Нужно указать фактический результат чтения задачи.",
                         "required_change": "Укажите фактический результат чтения задачи."}
            for item in payload["criteria"]}, "blockers": [], "confidence": 0.8}

    monkeypatch.setattr(OpenAICompatibleClient, "chat", advisor)
    submitted = step(configured, report=raw, operation_key="structured-1", expected_version=1)
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()["result"]
    assert result["verdict"] == "PARTIAL"
    assert "Нужно указать" in submitted.json()["output"]
    assert len(requests) == 1
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskStepHistoryEntry))
        assert row.worker_report == raw
        snapshot = json.loads(row.evaluation_snapshot)
        assert json.loads(snapshot["diagnostics"]["user"]["text"])["report"] == expected
        assert snapshot["advisor_assessments"]
    replayed = step(configured, report=raw, operation_key="structured-1", expected_version=1)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["result"] == result
    assert len(requests) == 1
    changed = step(configured, report=report("different"),
                   operation_key="structured-1", expected_version=1)
    assert changed.status_code == 409
    assert len(requests) == 1


def test_invalid_wire_unicode_is_rejected_before_report_processing(configured, monkeypatch):
    enroll(configured)
    before = step(configured).json()["result"]
    provider = Mock(side_effect=AssertionError("Invalid Unicode cannot reach Advisor"))
    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)
    command = {"interaction_protocol": "configured-cli-v1", "task": configured[1]["task"],
               "namespace_id": configured[1]["namespace_id"], "report": report(source=chr(0xD800)),
               "operation_key": "invalid-unicode", "expected_version": before["version"]}
    response = configured[0].post("/internal/runtime/step",
        headers={**MACHINE, "Content-Type": "application/json"}, content=json.dumps(command, ensure_ascii=True))
    assert response.status_code == 422, response.text
    assert "error" in response.json()
    assert "\\ud800" not in response.text
    provider.assert_not_called()
    after = step(configured).json()["result"]
    assert (after["version"], after["phase_code"], after["status"]) == (
        before["version"], before["phase_code"], before["status"])
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 0


@pytest.mark.parametrize("other", ['{"value":-1}', '{"value":"A"}', '{"value":"a!"}'])
def test_report_identity_never_discards_case_sign_or_punctuation(other):
    assert _report_fingerprint(1, '{"value":"a"}', "contract") != _report_fingerprint(1, other, "contract")


def test_authorized_historical_text_readback_is_not_a_new_submission(configured, monkeypatch, supervisor_llm):
    enroll(configured)
    supervisor_llm("PARTIAL")
    accepted = step(configured, report=report("Prepared context"),
                    operation_key="historical-operation", expected_version=1)
    assert accepted.status_code == 200, accepted.text
    old_report = "Historical plain-text report; do not reinterpret it."
    legacy = ConfiguredStep(interaction_protocol="configured-cli-v1", task=configured[1]["task"],
        namespace_id=configured[1]["namespace_id"], report=old_report,
        operation_key="historical-operation", expected_version=1)
    # Seed an accepted pre-upgrade ledger entry, not a second admission path.
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskStepHistoryEntry))
        snapshot = json.loads(row.evaluation_snapshot)
        snapshot["configured_cli"]["request_sha256"] = payload_sha256(legacy.model_dump(mode="json"))
        row.evaluation_snapshot = json.dumps(snapshot)
        row.worker_report = old_report
        uow.commit()
    provider = Mock(side_effect=AssertionError("Historical readback cannot reevaluate"))
    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)
    replay = step(configured, report=old_report, operation_key="historical-operation", expected_version=1)
    assert replay.status_code == 200, replay.text
    assert replay.json()["result"] == accepted.json()["result"]
    provider.assert_not_called()
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskStepHistoryEntry))
        assert row.worker_report == old_report
        assert json.loads(row.evaluation_snapshot) == snapshot
    fresh = step(configured, report=old_report, operation_key="new-operation", expected_version=2)
    assert fresh.status_code == 422
    provider.assert_not_called()


def test_untrusted_caller_cannot_use_report_errors_to_read_task_state(configured, monkeypatch):
    enroll(configured)
    provider = Mock(side_effect=AssertionError("Unauthorized caller cannot evaluate"))
    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)
    request = {"interaction_protocol": "configured-cli-v1", "task": configured[1]["task"],
               "namespace_id": configured[1]["namespace_id"], "report": "bad report",
               "operation_key": "unauthorized", "expected_version": 1}
    response = configured[0].post("/internal/runtime/step", headers={"Authorization": "Bearer another"}, json=request)
    assert response.status_code == 403
    assert "Invalid phase report" not in response.text
    provider.assert_not_called()
