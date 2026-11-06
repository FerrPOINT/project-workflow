"""The evaluated phase context is frozen, rechecked and never reconstructed on readback."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from project_workflow.application import standalone
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.standalone import StandaloneFence
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder
from project_workflow.interfaces.ui.app import create_app
from project_workflow.supervisor.evidence import validate_frozen_evaluation
from tests._report_helpers import report_json
from tests.test_standalone_execution import local_execution as local_execution
from tests.test_standalone_execution import report


def response(payload, covered):
    return {"verdict": "PASS" if covered else "PARTIAL", "assessments": {
        item["id"]: {"covered": covered, "reason": "Exact fixture evidence",
                     "required_change": None if covered else "Supply the complete fixture artifact"}
        for item in payload["criteria"]}, "blockers": [], "confidence": 0.9}


def submit_partial(uow, start, monkeypatch):
    standalone.step(uow, start)
    monkeypatch.setattr(OpenAICompatibleClient, "respond",
                        lambda _self, **kwargs: response(json.loads(kwargs["user"]), False))
    command = report(start, 1)
    accepted = standalone.step(uow, command)["result"]
    assert accepted["verdict"] == "PARTIAL" and not accepted["complete"]
    return command


@pytest.mark.parametrize("policy", ["supervisor-evaluator-v18", "supervisor-evaluator-v19"])
def test_supplement_gets_exact_phase_facts_and_assessment_then_next_phase_is_empty(
    local_execution, monkeypatch, policy,
):
    monkeypatch.setattr(PromptBuilder, "PROMPT_VERSION", policy)
    uow, start = local_execution
    original = submit_partial(uow, start, monkeypatch)
    calls = []

    def answer(_self, **kwargs):
        payload = json.loads(kwargs["user"])
        calls.append(payload)
        return response(payload, True)

    monkeypatch.setattr(OpenAICompatibleClient, "respond", answer)
    correction = report(start, 2, key="correction", document="Corrected complete artifact")
    accepted = standalone.step(uow, correction)["result"]
    assert calls[0]["previous_reports"] == [json.loads(original.report)]
    assert all(item["previous_assessment"] == {
        "covered": False, "reason": "Exact fixture evidence",
        "required_change": "Supply the complete fixture artifact",
    } for item in calls[0]["criteria"])
    assert accepted["phase_code"] == "local.2"
    row = uow.step_history.list(task_id=uow.tasks.list()[0].id, limit=None)[0].to_dict()
    snapshot = row["evaluation_snapshot"]
    frozen = deepcopy(snapshot)
    call_count = len(calls)
    assert len(snapshot["contract_fingerprint_state"]["phase_context_fingerprint"]) == 64
    assert validate_frozen_evaluation(
        row, snapshot, replay_fingerprint=row["replay_fingerprint"],
    ) == row["covered_item_ids"]
    assert snapshot == frozen and len(calls) == call_count
    prior_snapshot = deepcopy(snapshot)
    del prior_snapshot["contract_fingerprint_state"]["phase_context_fingerprint"]
    with pytest.raises(ConflictError, match="phase context"):
        validate_frozen_evaluation(row, prior_snapshot, replay_fingerprint=row["replay_fingerprint"])
    invalid = deepcopy(snapshot)
    invalid["contract_fingerprint_state"]["phase_context_fingerprint"] = None
    with pytest.raises(ConflictError, match="phase context"):
        validate_frozen_evaluation(row, invalid, replay_fingerprint=row["replay_fingerprint"])
    standalone.step(uow, report(start, 3, key="next-phase"))
    assert calls[1]["previous_reports"] == []
    assert all(item["previous_assessment"] is None for item in calls[1]["criteria"])


def test_v18_result_replays_through_http_after_v19_activation_without_evaluation(local_execution, monkeypatch):
    uow, start = local_execution
    calls = []
    current_system = PromptBuilder.SYSTEM_PROMPT
    archive = Path(__file__).resolve().parents[1] / "docs/evidence/advisor-v18-verdict-boundary-dda58fa-20261104.json"
    prior_system = json.loads(archive.read_text(encoding="utf-8"))["system"]
    assert prior_system["sha256"] == "6e00082f63c0ce05166a751225afd6eb3f2aa9194757b905e175e0089f3b7c9a"
    assert not prior_system["truncated"] and not prior_system["redacted"]

    def answer(_self, **kwargs):
        assert kwargs["system"] == prior_system["text"]
        calls.append(json.loads(kwargs["user"]))
        return response(calls[-1], True)

    monkeypatch.setattr(PromptBuilder, "PROMPT_VERSION", "supervisor-evaluator-v18")
    monkeypatch.setattr(PromptBuilder, "SYSTEM_PROMPT", prior_system["text"])
    monkeypatch.setattr(OpenAICompatibleClient, "respond", answer)
    with TestClient(create_app(), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert client.post("/internal/runtime/step", json=start.model_dump(mode="json")).status_code == 200
        command = report(start, 1).model_dump(mode="json")
        accepted = client.post("/internal/runtime/step", json=command)
        assert accepted.status_code == 200, accepted.text
        uow.session.expire_all()
        task = uow.tasks.get_by_key(start.task, project_id=start.namespace_id)
        assert task is not None
        frozen = deepcopy([row.to_dict() for row in uow.step_history.list(task_id=task.id, limit=None)])
        assert frozen[0]["evaluation_snapshot"]["prompt_version"] == "supervisor-evaluator-v18"

        monkeypatch.setattr(PromptBuilder, "PROMPT_VERSION", "supervisor-evaluator-v19")
        monkeypatch.setattr(PromptBuilder, "SYSTEM_PROMPT", current_system)
        monkeypatch.setattr(OpenAICompatibleClient, "respond", lambda *_a, **_kw: pytest.fail("Readback cannot infer"))
        replay = client.post("/internal/runtime/step", json=command)
        assert replay.status_code == 200 and replay.json()["ok"] is True
        assert replay.json()["result"] == accepted.json()["result"]
        history = client.get("/internal/runtime/history", params={
            "interaction_protocol": "configured-cli-v1", "namespace_id": start.namespace_id,
            "task": start.task, "operation_key": command["operation_key"],
        })
        assert history.status_code == 200, history.text
        assert history.json()["result"]["records"][0]["result"] == accepted.json()["result"]
        uow.session.expire_all()
        assert [row.to_dict() for row in uow.step_history.list(task_id=task.id, limit=None)] == frozen
        assert len(calls) == 1


def test_same_phase_http_context_keeps_owner_fact_omitted_from_later_report(local_execution, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "docs/evidence/workflow-advisor-audit-live-20261103.json"
    audit = json.loads(source.read_text(encoding="utf-8"))
    case = next(item for item in audit["cases"] if item["task_key"] == "SDLC-32")
    saved = {item["history_id"]: item["request"]["report"] for item in case["evaluations"]}

    # Explicit test projection preserves old facts; runtime accepts only the current format.
    reports = [{
        "source": {"request": saved[number]["source"], "decisions": []},
        "result": {"artifacts": [
            {"name": name, "content": content} for name, content in saved[number]["result"].items()
        ], "assumptions": []},
        "unresolved": saved[number]["unresolved"],
    } for number in (189, 190)]
    assert "\u00ab\u0417\u0430\u043a\u0440\u044b\u0442\u0430\u00bb" in reports[0]["source"]["request"]
    assert "\u00ab\u0417\u0430\u043a\u0440\u044b\u0442\u0430\u00bb" not in reports[1]["source"]["request"]
    calls = []

    def answer(_self, **kwargs):
        payload = json.loads(kwargs["user"])
        calls.append(payload)
        return response(payload, False)

    monkeypatch.setattr(OpenAICompatibleClient, "respond", answer)
    uow, start = local_execution
    with TestClient(create_app(), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert client.post("/internal/runtime/step", json=start.model_dump(mode="json")).status_code == 200
        for version, payload in enumerate(reports, start=1):
            command = report(start, version, key=f"source-facts-{version}").model_copy(update={
                "report": json.dumps(payload, ensure_ascii=False),
            })
            accepted = client.post("/internal/runtime/step", json=command.model_dump(mode="json"))
            assert accepted.status_code == 200, accepted.text
            assert accepted.json()["result"]["verdict"] == "PARTIAL"
        assert len(calls) == 2
        assert calls[0]["previous_reports"] == []
        assert calls[1]["previous_reports"] == [reports[0]]
        assert calls[1]["report"] == reports[1]
        uow.session.expire_all()
        task = uow.tasks.get_by_key(start.task, project_id=start.namespace_id)
        rows = uow.step_history.list(task_id=task.id, limit=None)
        assert [json.loads(row.worker_report) for row in reversed(rows)] == reports


@pytest.mark.parametrize("changed", ["report", "reason"])
def test_in_place_history_mutation_with_same_ids_and_coverage_prevents_transition(
    local_execution, monkeypatch, changed,
):
    uow, start = local_execution
    original = submit_partial(uow, start, monkeypatch)
    captured = []

    def answer(_self, **kwargs):
        payload = json.loads(kwargs["user"])
        captured.append(payload)
        row = uow.session.query(m.TaskStepHistoryEntry).one()
        if changed == "report":
            row.worker_report = report_json("Changed historical fact", source="New owner decision")
        else:
            saved = json.loads(row.evaluation_snapshot)
            for assessment in saved["advisor_assessments"].values():
                assessment["reason"] = "Changed saved reason with the same covered flag"
            row.evaluation_snapshot = json.dumps(saved)
        uow.commit()
        return response(payload, True)

    monkeypatch.setattr(OpenAICompatibleClient, "respond", answer)
    result = standalone.step(uow, report(start, 2, key="concurrent-mutation"))["result"]
    assert len(captured) == 1 and captured[0]["previous_reports"] == [json.loads(original.report)]
    assert result["verdict"] == "BLOCKED" and result["retryable"] is True
    assert result["phase_code"] == "local.1" and not result["complete"]
    rows = uow.session.query(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id).all()
    snapshot = json.loads(rows[-1].evaluation_snapshot)
    assert snapshot["raw_evaluator"]["error"] == "PhaseContractChanged"
    assert snapshot["diagnostics"]["outcome"] == "technical_failure"


def test_incompatible_archive_is_readable_but_cannot_silently_become_new_context(local_execution, monkeypatch):
    uow, start = local_execution
    original = submit_partial(uow, start, monkeypatch)
    row = uow.session.query(m.TaskStepHistoryEntry).one()
    archived = '{"source":"Archived source","result":{"document":"Old report"},"unresolved":[]}'
    row.worker_report = archived
    uow.commit()
    calls = []
    monkeypatch.setattr(OpenAICompatibleClient, "respond", lambda *args, **kwargs: calls.append(kwargs))
    result = standalone.step(uow, report(start, 2, key="new-contract"))["result"]
    assert calls == []
    assert result["verdict"] == "BLOCKED" and result["retryable"] is True
    assert result["phase_code"] == "local.1" and not result["complete"]
    assert "несовместимый" in " ".join(result["blockers"])
    saved = standalone.history(uow, start.task, start.namespace_id, operation_key=original.operation_key)
    assert saved["result"]["records"][0]["worker_report"] == archived
    assert calls == []


def test_exact_archived_operation_replays_before_current_format_validation(local_execution, monkeypatch):
    uow, start = local_execution
    original = submit_partial(uow, start, monkeypatch)
    row = uow.session.query(m.TaskStepHistoryEntry).one()
    archived = original.model_copy(update={
        "report": '{"source":"Archive","result":{"document":"Accepted old result"},"unresolved":[]}',
    })
    task = uow.tasks.list()[0]
    fence = StandaloneFence(task.id, task.project_id, task.workflow_id, task.mode_id,
        task.cycle_number, task.assignment_revision, task.assignment_operation_key,
        task.current_phase_id, task.status, standalone.version(uow, task), archived)
    snapshot = json.loads(row.evaluation_snapshot)
    snapshot["standalone"]["request_sha256"] = fence.request_sha256
    row.worker_report = archived.report
    row.evaluation_snapshot = json.dumps(snapshot)
    expected = json.loads(row.supervisor_response)
    uow.commit()
    calls = []
    monkeypatch.setattr(OpenAICompatibleClient, "respond", lambda *args, **kwargs: calls.append(kwargs))
    assert standalone.step(uow, archived)["result"] == expected
    with pytest.raises(ConflictError, match="payload conflict"):
        standalone.step(uow, archived.model_copy(update={"report": archived.report + " "}))
    assert calls == []
