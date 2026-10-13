"""Durable accepted receipts, not model text, EOF or synthetic owner ACKs."""

import copy
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.application import base_admission, base_terminal
from project_workflow.domain.base_admission import BASE_SKILLS_REVISION
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure import base_package
from project_workflow.infrastructure.base_package import digest
from project_workflow.infrastructure.db import models
from project_workflow.infrastructure.db.managed_catalog import load_managed_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests.base_candidate.test_admission import OWNER, REAL_GIT_READ, RUNTIME, assign_and_bind, snapshot, step
from tests.base_candidate.test_admission import base as base
from tests.base_candidate.test_machine_readers import CATALOG_READER, PM_READER, READER, TESTER_READER
from tests.base_candidate.test_machine_readers import registered_readers as registered_readers
from tests.test_pm_execution import ADAPTER, OLD_RUN, bind_pm
from tests.test_pm_execution import pm as pm
from tests.test_runtime_api import _step_payload

READBACK = "/internal/runtime/base/terminal-receipt/readback"
pytestmark = pytest.mark.usefixtures("registered_readers")


def complete(base, supervisor_llm):
    client, payload = base
    bound, _ = assign_and_bind(base)
    supervisor_llm("PASS")
    for number in range(1, 4):
        request = step(
            bound, payload, report=f"Synthetic accepted phase {number} evidence",
            step_operation_key=f"base-terminal-report:{number}", expected_phase_code=f"DV-INITIAL-{number:02}",
        )
        response = client.post("/internal/runtime/step", headers=RUNTIME, json=request)
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["complete"] is (number == 3)
        if number < 3:
            assert "base_terminal_receipt" not in result
    lookup = {key: request[key] for key in (
        "task", "step_operation_key", "assignment_revision", "assignment_ref", "binding_ref", "hermes_run_ref",
        "mode_key", "cycle_number", "attempt_number", "base_config_ref", "base_config_sha256",
    )}
    return request, lookup, result["base_terminal_receipt"]


def test_terminal_receipt_persisted_in_existing_history_and_survives_new_app(base, supervisor_llm):
    request, lookup, receipt = complete(base, supervisor_llm)
    assert receipt["receipt_sha256"] == payload_sha256({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    assert receipt["base_admission"] == base[1]["base_admission"]
    assert receipt["execution_scope"] == "delivery"
    assert receipt["mode_key"] == "initial"
    assert receipt["bind_request_sha256"] and receipt["run"]["identity_sha256"]
    assert receipt["cursor"]["revision"] > 0
    stored = snapshot()
    assert len(stored[3]) == 3
    terminal = next(item for item in stored[3] if item["step_operation_key"] == request["step_operation_key"])
    assert terminal["supervisor_response"]["base_terminal_receipt"] == receipt
    assert any(event["id"] == receipt["cursor"]["revision"] for event in stored[2])
    with TestClient(create_app()) as restarted:
        for headers in (READER,):
            response = restarted.post(
                READBACK, headers=headers, json={**lookup, "receipt_sha256": receipt["receipt_sha256"]},
            )
            assert response.status_code == 200, response.text
            assert response.json() == {"ok": True, "complete": True, "receipt": receipt}
        replay = restarted.post("/internal/runtime/step", headers=RUNTIME, json=request)
        assert replay.status_code == 200, replay.text
        assert replay.json()["result"]["base_terminal_receipt"] == receipt
    assert snapshot() == stored


@pytest.mark.parametrize("field,value", [
    ("assignment_revision", 2), ("assignment_ref", "foreign"), ("binding_ref", "foreign"),
    ("hermes_run_ref", "foreign"), ("mode_key", "rework"), ("cycle_number", 1), ("attempt_number", 2),
    ("base_config_ref", "foreign"), ("base_config_sha256", "0" * 64), ("receipt_sha256", "0" * 64),
])
def test_exact_lookup_mismatch_is_not_success(base, supervisor_llm, field, value):
    _, lookup, _ = complete(base, supervisor_llm)
    before = snapshot()
    response = base[0].post(READBACK, headers=READER, json={**lookup, field: value})
    assert response.status_code == 409, response.text
    assert snapshot() == before


@pytest.mark.parametrize("corruption", [
    "receipt", "complete", "status", "report", "evaluator", "coverage", "cursor", "event", "bind", "receipt_hash",
])
def test_missing_or_corrupted_terminal_evidence_cannot_be_read_or_replayed(base, supervisor_llm, corruption):
    request, lookup, _ = complete(base, supervisor_llm)
    with SAUnitOfWork() as uow:
        history = uow.step_history.get_by_step_operation_key(request["step_operation_key"])
        row = uow.session.get(models.TaskStepHistoryEntry, history.id)
        response = history.to_dict()["supervisor_response"]
        if corruption == "receipt":
            response.pop("base_terminal_receipt")
        elif corruption == "complete":
            response["complete"] = False
        elif corruption == "status":
            response["status"] = "active"
        elif corruption == "receipt_hash":
            response["base_terminal_receipt"]["receipt_sha256"] = "0" * 64
        elif corruption == "report":
            row.worker_report = "Different report"
        elif corruption == "evaluator":
            evaluation = history.to_dict()["evaluation_snapshot"]
            evaluation["raw_evaluator"]["verdict"] = "BLOCKED"
            row.evaluation_snapshot = json.dumps(evaluation)
        elif corruption == "coverage":
            row.covered_item_ids = "[]"
        elif corruption == "cursor":
            uow.tasks.update(history.task_id, {"status": "active"})
        elif corruption == "event":
            events = [
                event for event in uow.tasks.list_phase_events(history.task_id) if event.step_history_id == history.id
            ]
            for event in events:
                uow.session.delete(uow.session.get(models.TaskPhaseEvent, event.id))
        elif corruption == "bind":
            assignment = uow.tasks.get_assignment_by_operation_key(history.assignment_operation_key)
            uow.session.get(models.TaskRuntimeAssignment, assignment.id).bind_request_sha256 = "0" * 64
        uow.step_history.update_supervisor_response(history.id, response)
        uow.commit()
    before = snapshot()
    assert base[0].post(READBACK, headers=READER, json=lookup).status_code == 409
    assert base[0].post("/internal/runtime/step", headers=RUNTIME, json=request).status_code == 409
    assert snapshot() == before


def test_instruction_only_eof_and_partial_report_are_not_terminal(base, supervisor_llm):
    client, payload = base
    bound, _ = assign_and_bind(base)
    request = step(bound, payload)
    instructions = client.post("/internal/runtime/step", headers=RUNTIME, json=request)
    assert instructions.status_code == 200
    assert instructions.json()["result"]["complete"] is False
    lookup = {key: request[key] for key in (
        "task", "step_operation_key", "assignment_revision", "assignment_ref", "binding_ref", "hermes_run_ref",
        "mode_key", "cycle_number", "attempt_number", "base_config_ref", "base_config_sha256",
    )}
    assert client.post(READBACK, headers=READER, json=lookup).status_code == 404
    supervisor_llm("PARTIAL")
    request["report"] = "EOF is not accepted evidence"
    result = client.post("/internal/runtime/step", headers=RUNTIME, json=request)
    assert result.status_code == 200, result.text
    assert result.json()["result"]["complete"] is False
    assert "base_terminal_receipt" not in result.json()["result"]
    assert client.post(READBACK, headers=READER, json=lookup).status_code == 409


@pytest.mark.parametrize("verdict", ["PARTIAL", "BLOCKED"])
def test_terminal_phase_requires_successful_evaluator_not_just_a_report(base, supervisor_llm, verdict):
    client, payload = base
    bound, _ = assign_and_bind(base)
    supervisor_llm("PASS")
    for number in (1, 2):
        response = client.post("/internal/runtime/step", headers=RUNTIME, json=step(
            bound, payload, report="Synthetic accepted evidence", step_operation_key=f"accepted-before:{number}",
            expected_phase_code=f"DV-INITIAL-{number:02}",
        ))
        assert response.status_code == 200
    supervisor_llm(verdict)
    request = step(bound, payload, report="Terminal phase report", expected_phase_code="DV-INITIAL-03")
    response = client.post("/internal/runtime/step", headers=RUNTIME, json=request)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["complete"] is False
    assert "base_terminal_receipt" not in response.json()["result"]
    lookup = {key: request[key] for key in (
        "task", "step_operation_key", "assignment_revision", "assignment_ref", "binding_ref", "hermes_run_ref",
        "mode_key", "cycle_number", "attempt_number", "base_config_ref", "base_config_sha256",
    )}
    assert client.post(READBACK, headers=READER, json=lookup).status_code == 409


def test_pm_readback_retains_execution_scope_and_cannot_synthesize_base_ack(pm, supervisor_llm):
    client, runtime, _, _, bound = bind_pm(pm)
    supervisor_llm("PASS")
    request = {**_step_payload(bound), "session_run_id": OLD_RUN, "report": "Synthetic legacy PM evidence"}
    response = client.post("/internal/runtime/step", headers=runtime, json=request)
    assert response.status_code == 200, response.text
    lookup = {key: request[key] for key in (
        "task", "step_operation_key", "assignment_revision", "assignment_ref", "binding_ref", "hermes_run_ref",
        "mode_key", "cycle_number", "attempt_number", "session_run_id",
    )}
    lookup.update(base_config_ref="not-a-base-config", base_config_sha256="a" * 64)
    before = client.get("/internal/runtime/history", headers=runtime, params={"task": lookup["task"]}).json()
    no_scope = PM_READER
    assert client.post(READBACK, headers=no_scope, json=lookup).status_code == 403
    stale = {**lookup, "session_run_id": "22222222-2222-4222-8222-222222222222"}
    scoped_reader = {**runtime, **PM_READER}
    assert client.post(READBACK, headers=scoped_reader, json=stale).status_code == 409
    # Correct scope still cannot turn a legacy report into a Base receipt.
    assert client.post(READBACK, headers=scoped_reader, json=lookup).status_code == 409
    assert client.post(READBACK, headers=ADAPTER, json=lookup).status_code == 401
    assert client.get("/internal/runtime/history", headers=runtime, params={"task": lookup["task"]}).json() == before


def test_receipt_failure_rolls_back_terminal_report_and_cursor(base, supervisor_llm, monkeypatch):
    client, payload = base
    bound, _ = assign_and_bind(base)
    supervisor_llm("PASS")
    for number in (1, 2):
        response = client.post("/internal/runtime/step", headers=RUNTIME, json=step(
            bound, payload, report="Synthetic accepted phase evidence", step_operation_key=f"before-terminal:{number}",
            expected_phase_code=f"DV-INITIAL-{number:02}",
        ))
        assert response.status_code == 200
    before = snapshot()

    def fail(*args, **kwargs):
        raise ConflictError("Receipt persistence unavailable")

    monkeypatch.setattr(base_terminal, "build_terminal_receipt", fail)
    response = client.post("/internal/runtime/step", headers=RUNTIME, json=step(
        bound, payload, report="Synthetic terminal evidence", step_operation_key="failed-terminal",
        expected_phase_code="DV-INITIAL-03",
    ))
    assert response.status_code == 409, response.text
    assert snapshot() == before


def test_readback_scope_unknown_foreign_and_catalog_credentials(base, supervisor_llm, monkeypatch):
    _, lookup, _ = complete(base, supervisor_llm)
    client, _ = base
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "catalog-" + "c" * 32)
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({
        "developer": RUNTIME["Authorization"][7:], "tester": "tester-" + "t" * 32,
    }))
    config.get_settings.cache_clear()
    assert client.post(READBACK, json=lookup).status_code == 401
    catalog_response = client.post(READBACK, headers=CATALOG_READER, json=lookup)
    assert catalog_response.status_code == 403
    assert client.post(READBACK, headers=TESTER_READER, json=lookup).status_code == 404
    assert client.post(READBACK, headers=OWNER, json=lookup).status_code == 401
    assert client.post(READBACK, headers=RUNTIME, json=lookup).status_code == 401
    assert client.post(READBACK, headers=READER, json={**lookup, "task": "OTHER-1"}).status_code == 404


def test_new_rework_assignment_makes_old_terminal_receipt_stale(base, supervisor_llm):
    _, lookup, _ = complete(base, supervisor_llm)
    client, payload = base
    rework = copy.deepcopy(payload)
    rework.update(
        mode_key="rework", cycle_number=1, stage_key="rework", expected_revision=1, expected_status="done",
        expected_mode_key="initial", expected_cycle_number=0, operation_key="base-rework:1", assignment_ref="rework@1",
    )
    response = client.post("/internal/runtime/assign", headers=OWNER, json=rework)
    assert response.status_code == 200, response.text
    assert client.post(READBACK, headers=READER, json=lookup).status_code == 409


@pytest.mark.skipif(not os.environ.get("WORKFLOW_BASE_PACKAGE_TEST_ROOT"), reason="Private package is explicit opt-in")
@pytest.mark.timeout(30)
def test_terminal_receipt_with_actual_pinned_private_git_package(base, supervisor_llm, monkeypatch):
    root = Path(os.environ["WORKFLOW_BASE_PACKAGE_TEST_ROOT"])
    monkeypatch.setattr(base_admission, "load_pinned_package", base_package.load_pinned_package)
    monkeypatch.setattr(base_package.GitPackage, "read", REAL_GIT_READ)
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", str(root))
    config.get_settings.cache_clear()
    catalog = load_managed_catalog(base_admission.CANDIDATE_PATH)
    manifest = base_package.load_pinned_package(root, catalog.skills_source)
    role = manifest["roles"]["developer"]
    package = base_package.GitPackage(root.resolve().parent, BASE_SKILLS_REVISION)
    base[1]["base_admission"].update(
        skills_manifest_sha256=digest(package.read("manifest.json")),
        role_instruction_sha256=role["roleInstruction"]["sha256"], physical_skills=role["physicalSkills"],
    )
    _, lookup, receipt = complete(base, supervisor_llm)
    response = base[0].post(READBACK, headers=READER, json=lookup)
    assert response.status_code == 200, response.text
    assert response.json()["receipt"] == receipt
    assert receipt["base_admission"]["skills_revision"] == BASE_SKILLS_REVISION
