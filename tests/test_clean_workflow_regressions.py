"""Independent clean-evaluator regressions; all provider and authority peers are local fakes."""

from __future__ import annotations

import copy
import hashlib
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import httpx
import pytest
import requests
from sqlalchemy import select

from project_workflow import config
from project_workflow.domain.exceptions import ConcurrentTransitionError
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.evaluate import _replay
from project_workflow.supervisor.models import Phase, PhaseCheck
from tests._report_helpers import report_json
from tests.test_configured_cli import MACHINE, enroll, step
from tests.test_configured_cli import configured as configured

pytestmark = pytest.mark.supervisor
ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "docs/evidence/clean-workflow-case-labels-20261104.json"
ORIGINAL_LABELS = ROOT / "docs/evidence/advisor-v16-case-labels-20261103.json"
ORIGINAL_SHA256 = "1ef1f4590b1242a35c6423189c8774ed844e15fec98821248d7c9631d0bfdeb3"


@pytest.fixture(autouse=True)
def deny_external_network(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.test")
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", "https://auth.test")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "clean-workflow-local-fixture-secret-not-a-real-credential")
    config.get_settings.cache_clear()

    def denied(*args, **kwargs):
        raise AssertionError("Clean Workflow tests must not access a stand or provider")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)


def wire(payload, verdict="PARTIAL", *, covered=False):
    return {
        "verdict": verdict,
        "assessments": {
            item["id"]: {"covered": covered, "reason": "Explicit fixture evidence, not a semantic heuristic",
                         "required_change": None if covered else "Supply the missing fixture evidence"}
            for item in payload["criteria"]
        },
        "blockers": [],
        "confidence": 0.9,
    }


def database_proof():
    with SAUnitOfWork() as uow:
        rows = list(uow.session.scalars(select(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id)))
        assert len(rows) == 1
        row = rows[0]
        task = uow.tasks.get_by_id(row.task_id)
        return {
            "row": (row.id, row.worker_report, row.evaluation_snapshot, row.supervisor_response),
            "task": (task.current_phase_code, task.status),
            "events": copy.deepcopy(uow.list_phase_events(row.task_id)),
        }


@pytest.mark.parametrize("wire_format", ["json_object", "json_schema"])
@pytest.mark.parametrize("outcome", ["invalid_json", "invalid_schema", "inconsistent_partial",
                                     "timeout", "connection_error", "partial"])
def test_configured_evaluation_calls_once_and_saved_history_replay_calls_zero(
    configured, monkeypatch, wire_format, outcome,
):
    monkeypatch.setenv("OPENAI_EVALUATOR_RESPONSE_FORMAT", wire_format)
    config.get_settings.cache_clear()
    enroll(configured)
    before = step(configured).json()["result"]

    def answer(**kwargs):
        payload = json.loads(kwargs["user"])
        if outcome == "invalid_json":
            return OpenAICompatibleClient._extract_json('{"verdict":')
        if outcome == "invalid_schema":
            return {"verdict": "PASS"}
        if outcome == "inconsistent_partial":
            return wire(payload, covered=True)
        if outcome == "timeout":
            raise requests.Timeout("Fixture timeout")
        if outcome == "connection_error":
            raise requests.ConnectionError("Fixture connection failure")
        return wire(payload)

    client = Mock(model="fixture-only", api_key="", last_call_diagnostics={}, last_response_content=None)
    client.chat.side_effect = answer
    factory = Mock(return_value=client)
    monkeypatch.setattr("project_workflow.supervisor.evaluate.OpenAICompatibleClient", factory)
    arguments = {"report": report_json("Actual incomplete result; no invented owner decisions"),
                 "operation_key": "clean-single-call", "expected_version": before["version"]}
    submitted = step(configured, **arguments)
    assert submitted.status_code == 200, submitted.text
    assert client.chat.call_count == 1, "No format, transport or semantic retry is allowed"
    factory.assert_called_once()
    result = submitted.json()["result"]
    assert result["phase_code"] == before["phase_code"]
    assert result["next_phase_code"] is None and result["complete"] is False
    assert "terminal_receipt" not in result
    proof = database_proof()
    assert not any(event["event_type"] == "completed" for event in proof["events"])
    snapshot = json.loads(proof["row"][2])
    assert len(snapshot["diagnostics"]["attempts"]) == 1
    if outcome == "partial":
        assert result["verdict"] == "PARTIAL" and result["retryable"] is False
        assert snapshot["diagnostics"]["outcome"] != "technical_failure"
        assert snapshot["advisor_assessments"]
    else:
        assert result["verdict"] == "BLOCKED"
        assert snapshot["diagnostics"]["outcome"] == "technical_failure"
        assert snapshot["advisor_assessments"] == {}

    client.chat.reset_mock()
    factory.reset_mock()
    client.chat.side_effect = AssertionError("History and exact operation replay must never evaluate")
    readback = configured[0].get("/internal/runtime/history", headers=MACHINE, params={
        "interaction_protocol": "configured-cli-v1", "task": configured[1]["task"],
        "namespace_id": configured[1]["namespace_id"], "operation_key": arguments["operation_key"], "n": 1,
    })
    assert readback.status_code == 200, readback.text
    assert readback.json()["result"]["records"][0]["result"] == result
    replay = step(configured, **arguments)
    assert replay.status_code == 200 and replay.json()["result"] == result
    factory.assert_not_called()
    client.chat.assert_not_called()
    assert database_proof() == proof


@pytest.mark.parametrize("failure", ["invalid_json", "timeout", "connection_error"])
def test_actual_provider_transport_does_not_retry(monkeypatch, failure):
    response = Mock(status_code=200, headers={})
    response.json.return_value = {
        "choices": [{"finish_reason": "stop", "message": {"content": '{"verdict":'}}],
    }
    post = Mock(return_value=response)
    if failure == "timeout":
        post.side_effect = requests.Timeout("Fixture timeout")
    elif failure == "connection_error":
        post.side_effect = requests.ConnectionError("Fixture connection failure")
    monkeypatch.setattr(requests, "post", post)
    client = OpenAICompatibleClient(base_url="https://fixture.invalid/v1", model="fixture", api_key="", timeout=1)
    with pytest.raises((ValueError, requests.RequestException)):
        client.chat("Fixture policy", "{}", response_format={"type": "json_object"})
    post.assert_called_once()


def coverage_engine(runs, *, duplicate_text=False):
    engine = object.__new__(SupervisorEngine)
    engine.task = {"id": 7}
    engine.execution_mode_id = 11
    engine.execution_cycle_number = 3
    engine.workflow = None
    checks = [PhaseCheck(id=41, description="Actual criterion")]
    if duplicate_text:
        checks.append(PhaseCheck(id=42, description="Actual criterion"))
    engine.all_phases = [Phase(id=19, code="P", name="Current", checks=checks)]
    engine.db = MagicMock()
    engine.db.step_history.list.return_value = [
        SimpleNamespace(to_dict=lambda row=row, index=index: {**row, "id": len(runs) - index})
        for index, row in enumerate(runs)
    ]
    return engine


def coverage_run(covered, *, missing=(), items=None, technical=False):
    return {
        "worker_report": report_json("Saved current-phase fixture"),
        "covered_item_ids": list(covered), "missing_item_ids": list(missing),
        "supervisor_response": {"retryable": technical},
        "evaluation_snapshot": {
            "contract_fingerprint_state": {"group": ["P"]},
            "evaluated_phase_group": ["P"],
            "contract_snapshot": {} if items is None else {"evaluation_items": items},
            "advisor_assessments": {
                item_id: {"covered": item_id in covered, "reason": "Explicit saved fixture assessment",
                          "required_change": None if item_id in covered else "Supply missing fixture evidence"}
                for item_id in (*covered, *missing)
            },
            "diagnostics": {"outcome": "technical_failure" if technical else "success"},
        },
    }


@pytest.mark.parametrize("duplicate_text", [False, True])
@pytest.mark.parametrize("saved_items", [None, [], [{"id": "P:check:41", "text": "Actual criterion"}]])
def test_checklist_text_never_becomes_criterion_identity(saved_items, duplicate_text):
    engine = coverage_engine([coverage_run(["Actual criterion"], items=saved_items)], duplicate_text=duplicate_text)
    assert engine._get_previously_covered("P") == set()
    engine.db.step_history.list.assert_called_once_with(
        task_id=7, phase_id=19, mode_id=11, cycle_number=3, limit=None,
    )


@pytest.mark.parametrize("saved_id", ["OLD:check:41", "P:check:999"])
def test_same_text_with_different_id_does_not_transfer_coverage(saved_id):
    run = coverage_run([saved_id], items=[{"id": saved_id, "text": "Actual criterion"}])
    assert coverage_engine([run])._get_previously_covered("P") == set()


def test_real_id_coverage_survives_technical_errors_but_not_new_missing_or_changed_text():
    item_id = "P:check:41"
    items = [{"id": item_id, "text": "Actual criterion"}]
    accepted = coverage_run([item_id], items=items)
    technical = coverage_run([], items=items, technical=True)
    assert coverage_engine([technical, accepted])._get_previously_covered("P") == {item_id}
    missing = coverage_run([], missing=[item_id], items=items)
    assert coverage_engine([missing, accepted])._get_previously_covered("P") == set()
    changed = coverage_run([item_id], items=[{"id": item_id, "text": "Previous criterion"}])
    assert coverage_engine([changed, accepted])._get_previously_covered("P") == set()


def test_coverage_history_is_not_limited_to_a_recent_window():
    item_id = "P:check:41"
    items = [{"id": item_id, "text": "Actual criterion"}]
    runs = [coverage_run([], items=items, technical=True) for _ in range(1005)]
    runs.append(coverage_run([item_id], items=items))
    engine = coverage_engine(runs)
    assert engine._get_previously_covered("P") == {item_id}
    assert engine.db.step_history.list.call_args.kwargs == {
        "task_id": 7, "phase_id": 19, "mode_id": 11, "cycle_number": 3, "limit": None,
    }


def replay_engine(verdict, *, cursor_matches, configured_fence):
    expected_phase = "NEXT" if verdict == "PASS" else "P"
    expected_status = {"PASS": "active", "PARTIAL": "active", "BLOCKED": "blocked"}[verdict]
    response = {"verdict": verdict, "phase_code": "P",
                "next_phase_code": "NEXT" if verdict == "PASS" else None,
                "replayed": False, "message": "Frozen result"}
    engine = MagicMock()
    engine.task = {"id": 7, "mode_id": 11, "cycle_number": 3}
    engine.runtime_fence = object() if configured_fence else None
    engine.phase_map = {"P": Phase(id=19, code="P", name="Current")}
    engine.db.step_history.get_by_fingerprint.return_value = SimpleNamespace(id=29, supervisor_response=response)
    engine.db.tasks.get_by_id.return_value = SimpleNamespace(
        current_phase_code=expected_phase if cursor_matches else "P",
        status=expected_status if cursor_matches else "done",
    )
    return engine, response


@pytest.mark.parametrize("configured_fence", [False, True])
@pytest.mark.parametrize("verdict", ["PASS", "PARTIAL", "BLOCKED"])
def test_replay_with_stale_cursor_rejects_without_repairing_any_transition(verdict, configured_fence):
    engine, response = replay_engine(verdict, cursor_matches=False, configured_fence=configured_fence)
    original = copy.deepcopy(response)
    try:
        with pytest.raises(ConcurrentTransitionError):
            _replay(engine, 7, 19, "retained-fingerprint")
    finally:
        engine._record_evaluation.assert_not_called()
        engine.db.record_step.assert_not_called()
        engine.db.tasks.update.assert_not_called()
        engine.db.commit.assert_not_called()
    assert response == original


@pytest.mark.parametrize("configured_fence", [False, True])
@pytest.mark.parametrize("verdict", ["PASS", "PARTIAL", "BLOCKED"])
def test_matching_replay_only_returns_the_saved_result(verdict, configured_fence):
    engine, response = replay_engine(verdict, cursor_matches=True, configured_fence=configured_fence)
    original = copy.deepcopy(response)
    assert _replay(engine, 7, 19, "retained-fingerprint") == {**response, "replayed": True}
    assert response == original
    engine._record_evaluation.assert_not_called()
    engine.db.record_step.assert_not_called()
    engine.db.tasks.update.assert_not_called()
    engine.db.commit.assert_not_called()


def test_qualification_keeps_original_seventeen_cases_and_exactly_thirty_six_slots():
    assert hashlib.sha256(ORIGINAL_LABELS.read_bytes()).hexdigest() == ORIGINAL_SHA256
    original = json.loads(ORIGINAL_LABELS.read_text(encoding="utf-8"))
    frozen = json.loads(LABELS.read_text(encoding="utf-8"))
    assert frozen["status"] == "prospective_not_run"
    assert frozen["cases"] == original["cases"]
    slots = frozen["planned_evaluations"]
    assert len(slots) == len({(slot["case_id"], slot["policy"], slot["sample"]) for slot in slots}) == 36
    assert frozen["http_budget"] == {"planned_evaluations": 36, "max_http_calls": 36,
                                    "format_repair_reserve": 0, "completed_calls": 0, "reused_calls": 0}
    assert frozen["policies"] == ["supervisor-evaluator-v17"]
    assert all(slot["policy"] == "supervisor-evaluator-v17" for slot in slots)
    expected_slots = {(case["id"], sample) for case in original["cases"] for sample in (1, 2)}
    expected_slots.update({("actual-pm-189", 3), ("actual-pm-189", 4)})
    assert {(slot["case_id"], slot["sample"]) for slot in slots} == expected_slots
    cases = {case["id"]: case for case in frozen["cases"]}
    assert cases["actual-pm-189"]["expected_assessments"]["C3"]["covered"] is False
    assert cases["actual-pm-189"]["expected_assessments"]["E2"]["covered"] is False
    assert cases["actual-pm-190"]["expected_assessments"]["C3"]["covered"] is False
    assert cases["actual-pm-190"]["expected_assessments"]["E2"]["covered"] is False
    assert cases["actual-pm-191"]["expected"]["verdict"] == "PASS"
