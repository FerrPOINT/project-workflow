"""Actual completion receipts, persisted replay and read-only failure boundaries."""

import hashlib
import json
from uuid import uuid4

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from sqlalchemy import select

from project_workflow import config
from project_workflow.application import single_task_terminal
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.task_step_history import SATaskStepHistoryRepository
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.interfaces.cli import ui
from project_workflow.interfaces.cli.core import cli
from project_workflow.interfaces.ui.app import create_app
from tests.test_single_task_runtime import API, PROFILE, RUNNER, SESSION, WRITER, prepare
from tests.test_single_task_runtime import bridge as bridge

READBACK = API + "terminal-receipt/readback"


def advance(client, monkeypatch, supervisor_llm):
    assignment, _, step, headers = prepare(client, monkeypatch)
    supervisor_llm("PASS")
    for number in range(2):
        report = {**step, "step_operation_key": f"terminal:preparation:{number}", "report": "Verified preparation"}
        response = client.post(API + "step", json=report, headers=headers)
        assert response.status_code == 200, response.text
        assert "workflow_receipt" not in response.json()["result"]
        step["expected_phase_code"] = response.json()["result"]["current_phase_code"]
    final = {**step, "step_operation_key": "terminal:final", "report": "Actual complete candidate with evidence"}
    lookup = {**PROFILE, "task": step["task"], "step_operation_key": final["step_operation_key"],
              "session_run_id": SESSION, "single_task_context_sha256": step["single_task_context_sha256"]}
    return assignment, final, lookup, headers


def complete(client, monkeypatch, supervisor_llm):
    assignment, final, lookup, headers = advance(client, monkeypatch, supervisor_llm)
    response = client.post(API + "step", json=final, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["complete"] is True
    return assignment, final, lookup, headers, response


def test_actual_completion_artifact_matches_readback_replay_and_restart(bridge, monkeypatch, supervisor_llm):
    assignment, final, lookup, headers, response = complete(bridge, monkeypatch, supervisor_llm)
    result = response.json()["result"]
    artifact, receipt = result["workflow_receipt"], result["single_task_terminal_receipt"]
    assert set(artifact) == {"reference", "sha256"}
    assert artifact["reference"] == receipt["reference"]
    assert artifact["sha256"] == hashlib.sha256(canonical_json(receipt).encode("utf-8")).hexdigest()
    assert receipt["binding"]["task_ref"] == receipt["binding"]["root_ref"] == assignment["business_task_ref"]
    assert receipt["binding"]["context"]["execution_ref"] == assignment["execution_ref"]
    assert receipt["binding"]["context"]["lease_ref"] == assignment["lease_ref"]
    assert receipt["binding"]["context"]["fencing_token"] == assignment["fencing_token"]
    assert receipt["step"]["worker_report_sha256"] == hashlib.sha256(final["report"].encode("utf-8")).hexdigest()
    before = None
    with SAUnitOfWork() as uow:
        history = uow.step_history.get_by_step_operation_key(final["step_operation_key"])
        before = history.to_dict()
        assert history.supervisor_response["workflow_receipt"] == artifact
        assert receipt["reference"].endswith(f":{history.id}")
        assert receipt["step"]["evaluation_sha256"] == payload_sha256(history.evaluation_snapshot)
    monkeypatch.setattr(OpenAICompatibleClient, "chat", lambda *_a, **_kw: pytest.fail("Replay must not evaluate"))
    assert bridge.post(API + "step", json=final, headers=headers).json() == response.json()
    read = bridge.post(READBACK, json={**lookup, "receipt_sha256": artifact["sha256"]}, headers=headers)
    assert read.status_code == 200, read.text
    assert read.headers["Cache-Control"] == "no-store"
    assert read.json() == {"ok": True, "complete": True, "workflow_receipt": artifact, "receipt": receipt}
    with SAUnitOfWork() as restarted:
        assert single_task_terminal.read_terminal_receipt(restarted, final["step_operation_key"]) == read.json()
        assert restarted.step_history.get_by_step_operation_key(final["step_operation_key"]).to_dict() == before


@pytest.mark.parametrize("failure", ["build", "seal"])
def test_receipt_and_actual_completion_commit_atomically(bridge, monkeypatch, supervisor_llm, failure):
    assignment, final, lookup, headers = advance(bridge, monkeypatch, supervisor_llm)
    with monkeypatch.context() as patcher:
        if failure == "build":
            def broken(*_args, **_kwargs):
                raise ConflictError("Injected receipt failure")
            patcher.setattr(single_task_terminal, "build_terminal_receipt", broken)
        else:
            original = SATaskStepHistoryRepository.update_supervisor_response

            def broken_seal(self, history_id, response):
                original(self, history_id, response)
                if "workflow_receipt" in response:
                    raise ConflictError("Injected after receipt write, before commit")
            patcher.setattr(SATaskStepHistoryRepository, "update_supervisor_response", broken_seal)
        failed = bridge.post(API + "step", json=final, headers=headers)
        assert failed.status_code == 409, failed.text
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key(assignment["task"])
        assert task.status == "active" and task.current_phase_code == "DV-INITIAL-03"
        assert len(uow.step_history.list(task_id=task.id)) == 2
        assert uow.step_history.get_by_step_operation_key(final["step_operation_key"]) is None
        assert not [e for e in uow.tasks.list_phase_events(task.id) if e.phase_id == task.current_phase_id
                    and e.event_type == "completed"]
    assert bridge.post(READBACK, json=lookup, headers=headers).status_code == 404
    retried = bridge.post(API + "step", json=final, headers=headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["result"]["complete"] is True


@pytest.mark.parametrize("mutation", [
    "body", "artifact", "report", "evaluation", "response", "event", "cursor", "assignment", "manifest", "unsealed",
])
def test_receipt_readback_and_exact_replay_reject_mismatch_or_stale_state(
    bridge, monkeypatch, supervisor_llm, mutation,
):
    _, final, lookup, headers, _ = complete(bridge, monkeypatch, supervisor_llm)
    with SAUnitOfWork() as uow:
        entry = uow.step_history.get_by_step_operation_key(final["step_operation_key"])
        row = uow.session.get(m.TaskStepHistoryEntry, entry.id)
        task = uow.session.get(m.Task, entry.task_id)
        if mutation in {"body", "artifact", "response", "unsealed"}:
            value = dict(entry.supervisor_response)
            if mutation == "body":
                value["single_task_terminal_receipt"]["cursor"]["completion_event_id"] += 1
            elif mutation == "artifact":
                value["workflow_receipt"]["sha256"] = "0" * 64
            elif mutation == "response":
                value["message"] = "Altered accepted response"
            else:
                value.pop("workflow_receipt")
                value.pop("single_task_terminal_receipt")
            uow.step_history.update_supervisor_response(entry.id, value)
        elif mutation == "report":
            row.worker_report = "Altered report"
        elif mutation == "evaluation":
            value = dict(entry.evaluation_snapshot)
            value["covered_item_ids"] = []
            row.evaluation_snapshot = canonical_json(value)
        elif mutation == "event":
            event = uow.session.scalar(select(m.TaskPhaseEvent).where(
                m.TaskPhaseEvent.step_history_id == entry.id, m.TaskPhaseEvent.event_type == "completed"))
            uow.session.delete(event)
        elif mutation == "cursor":
            task.status = "active"
        elif mutation == "assignment":
            task.assignment_revision += 1
        else:
            instruction = uow.phase_instructions.list(entry.phase_id)[0]
            uow.phase_instructions.update(instruction["id"], {"description": "Installed manifest drift"})
    read = bridge.post(READBACK, json=lookup, headers=headers)
    assert read.status_code == 409, read.text
    assert bridge.post(API + "step", json=final, headers=headers).status_code == 409


def test_incomplete_missing_wrong_hash_and_authority_are_not_receipts(bridge, monkeypatch, supervisor_llm):
    _, final, lookup, headers = advance(bridge, monkeypatch, supervisor_llm)
    assert bridge.post(READBACK, json=lookup, headers=headers).status_code == 404
    earlier = {**lookup, "step_operation_key": "terminal:preparation:1"}
    assert bridge.post(READBACK, json=earlier, headers=headers).status_code == 409
    supervisor_llm("BLOCKED")
    blocked = bridge.post(API + "step", json=final, headers=headers)
    assert blocked.status_code == 200 and blocked.json()["result"]["complete"] is False
    assert "workflow_receipt" not in blocked.json()["result"]
    assert bridge.post(READBACK, json=lookup, headers=headers).status_code == 409
    assert bridge.post(READBACK, json=lookup).status_code == 401
    assert bridge.post(READBACK, json=lookup, headers=WRITER).status_code == 403
    assert bridge.post(READBACK, json=lookup, headers=RUNNER).status_code == 403
    assert bridge.post(READBACK, json={**lookup, "session_run_id": str(uuid4())}, headers=headers).status_code == 409


def test_receipt_excludes_credentials_provider_inputs_and_report_text(bridge, monkeypatch, supervisor_llm):
    _, final, lookup, headers = advance(bridge, monkeypatch, supervisor_llm)
    original = OpenAICompatibleClient.chat
    provider_secret = "private-provider-input-not-for-receipt"
    report_secret = "private-report-text-not-for-receipt"

    def provider(*args, **kwargs):
        value = original(*args, **kwargs)
        value["message"] = report_secret
        return value

    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)
    original_build = single_task_terminal.build_terminal_receipt

    def build_with_private_metadata(uow, operation_key, *, fence):
        entry = uow.step_history.get_by_step_operation_key(operation_key)
        row = uow.session.get(m.TaskStepHistoryEntry, entry.id)
        evaluation = dict(entry.evaluation_snapshot)
        evaluation["provider_inputs"] = {"api_key": provider_secret}
        row.evaluation_snapshot = canonical_json(evaluation)
        uow.session.flush()
        return original_build(uow, operation_key, fence=fence)

    monkeypatch.setattr(single_task_terminal, "build_terminal_receipt", build_with_private_metadata)
    final["report"] = report_secret
    response = bridge.post(API + "step", json=final, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    receipt = result["single_task_terminal_receipt"]
    serialized = json.dumps(receipt)
    for forbidden in (provider_secret, report_secret, headers["X-Workflow-Execution-Token"],
                      "execution_token", "api_key", "provider_inputs", "raw_evaluator", "worker_report\""):
        assert forbidden not in serialized
    assert receipt["step"]["worker_report_sha256"] == hashlib.sha256(report_secret.encode()).hexdigest()
    assert result["workflow_receipt"]["sha256"] == payload_sha256(receipt)
    read = bridge.post(READBACK, json=lookup, headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["receipt"] == receipt
    assert bridge.post(READBACK, json={**lookup, "receipt_sha256": "0" * 64}, headers=headers).status_code == 409


def test_terminal_contract_has_no_caller_owner_lease_or_proof_fields(bridge):
    schema = bridge.get("/openapi.json").json()
    request = schema["components"]["schemas"]["SingleTaskTerminalReadback"]
    assert set(request["properties"]) == {
        "task", "step_operation_key", "instruction_profile", "instruction_manifest_sha256",
        "session_run_id", "single_task_context_sha256", "receipt_sha256",
    }
    assert request["additionalProperties"] is False
    assert READBACK in schema["paths"]


def test_existing_cli_exact_step_replay_outputs_usable_artifact_without_new_commands(
    bridge, monkeypatch, supervisor_llm, tmp_path,
):
    _, final, _, headers, response = complete(bridge, monkeypatch, supervisor_llm)
    request_file, token_file = tmp_path / "request.json", tmp_path / "execution.token"
    request_file.write_text(json.dumps(final), encoding="utf-8")
    token_file.write_text(headers["X-Workflow-Execution-Token"], encoding="ascii")
    monkeypatch.setenv("SDLC_API_TOKEN", "r" * 40)
    monkeypatch.setattr(ui, "SAUnitOfWork", lambda: pytest.fail("CLI DB fallback forbidden"))

    def request(method, path, *, body, execution_token):
        assert (method, path) == ("POST", "internal/runtime/step")
        assert body == final and execution_token == headers["X-Workflow-Execution-Token"]
        result = bridge.post(API + "step", json=body, headers=headers)
        assert result.status_code == 200, result.text
        return result.json()

    monkeypatch.setattr(ui, "_platform_request", request)
    args = ["--json", "step", "--task", final["task"], "--report", final["report"],
            "--operation-key", final["step_operation_key"], "--runtime-request", str(request_file),
            "--execution-token-file", str(token_file)]
    for _ in range(2):
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["workflow_receipt"] == response.json()["result"]["workflow_receipt"]
        assert headers["X-Workflow-Execution-Token"] not in result.output
    assert set(cli.commands) == {"step", "history"}


def test_old_terminal_record_is_not_retroactively_sealed(bridge, monkeypatch, supervisor_llm):
    _, final, lookup, headers, _ = complete(bridge, monkeypatch, supervisor_llm)
    with SAUnitOfWork() as uow:
        history = uow.step_history.get_by_step_operation_key(final["step_operation_key"])
        response = dict(history.supervisor_response)
        response.pop("single_task_terminal_receipt")
        response.pop("workflow_receipt")
        uow.step_history.update_supervisor_response(history.id, response)
        row = uow.session.get(m.TaskStepHistoryEntry, history.id)
        evaluation = dict(history.evaluation_snapshot)
        evaluation.pop("contract_fingerprint_state")
        row.evaluation_snapshot = canonical_json(evaluation)
    assert bridge.post(READBACK, json=lookup, headers=headers).status_code == 409
    assert bridge.post(API + "step", json=final, headers=headers).status_code == 409
    with SAUnitOfWork() as uow:
        assert uow.step_history.get_by_step_operation_key(final["step_operation_key"]).supervisor_response == response


def test_legacy_done_history_is_unchanged_and_not_a_single_task_receipt(monkeypatch):
    from tests.test_runtime_api import _namespace

    monkeypatch.setattr(config, "CATALOG_VARIANT", "legacy")
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"developer": "r" * 40}))
    config.get_settings.cache_clear()
    _namespace("DEV", "workflow-developer", "DEV")
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_cli_command("workflow-developer")
        mode = uow.workflows.get_mode_by_key(namespace.workflow_id, "assigned")
        phase = uow.phases.list(namespace.workflow_id, mode_id=mode.id)[0]
        task_id = uow.tasks.create({"project_id": namespace.id, "workflow_id": namespace.workflow_id,
                                    "mode_id": mode.id, "task_key": "DEV-7", "current_phase_id": phase.id,
                                    "status": "done", "assignment_revision": 1,
                                    "assignment_operation_key": "legacy:assignment"})
        uow.session.add(m.TaskRuntimeAssignment(operation_key="legacy:assignment", task_id=task_id,
                        project_id=namespace.id, workflow_id=namespace.workflow_id, mode_id=mode.id,
                        cycle_number=0, assignment_revision=1, payload="{}"))
        uow.record_step(task_id=task_id, phase_id=phase.id, verdict="pass", worker_report="Original legacy report",
                        covered_item_ids=[], missing_item_ids=[], blocker_messages=[], evaluation_snapshot={},
                        supervisor_response={"complete": True, "status": "done"})
    with SAUnitOfWork() as uow:
        before = [row.to_dict() for row in uow.step_history.list(task_id=task_id)]
    with TestClient(create_app()) as client:
        response = client.post(READBACK, json={**PROFILE, "task": "DEV-7", "step_operation_key": "legacy:terminal",
                               "session_run_id": SESSION, "single_task_context_sha256": "0" * 64}, headers=RUNNER)
        assert response.status_code == 409, response.text
    with SAUnitOfWork() as uow:
        assert [row.to_dict() for row in uow.step_history.list(task_id=task_id)] == before
