"""Durable Base terminal receipts embedded in the accepted step ledger."""

import hashlib
import re
from typing import Any

from project_workflow.application.base_admission import assert_base_step
from project_workflow.application.pm_execution import PMExecutionService
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.runtime_assignment import RuntimeStepFence, payload_sha256
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import PromptBuilder, ResponseParser
from project_workflow.supervisor.evaluate import _fingerprint_contract_state, _report_fingerprint

RECEIPT_CONTRACT = "base-sdlc/workflow-terminal-receipt/v1"


def _coverage_ids(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item or item != item.strip() for item in value
    ) or len(value) != len(set(value)):
        raise ConflictError("Terminal evaluator IDs must be nonempty and unique")
    return value


def _validate_frozen_evaluation(step: dict[str, Any], evaluation: dict[str, Any]) -> list[str]:
    contract, evaluator = evaluation.get("contract_snapshot"), evaluation.get("raw_evaluator")
    if not isinstance(contract, dict) or not isinstance(evaluator, dict):
        raise ConflictError("Terminal accepted evaluator/contract is missing")
    items = contract.get("evaluation_items")
    if not isinstance(items, list) or not items or not all(
        isinstance(item, dict) and set(item) == {"id", "text"}
        and isinstance(item["text"], str) and item["text"].strip() for item in items
    ):
        raise ConflictError("Terminal evaluator contract items are invalid")
    item_ids = _coverage_ids([item["id"] for item in items])
    covered = _coverage_ids(step.get("covered_item_ids"))
    fingerprints = [evaluation.get(key) for key in ("contract_fingerprint", "evaluated_contract_fingerprint")]
    state = evaluation.get("contract_fingerprint_state")
    if any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None for value in fingerprints):
        raise ConflictError("Terminal frozen contract fingerprints are missing or invalid")
    if not isinstance(state, dict) or set(state) != {
        "prompt_version", "contract", "evaluation_items", "previously_covered_ids",
        "delegation_allowed", "group", "transition_routes", "phase_graph",
    }:
        raise ConflictError("Terminal frozen fingerprint inputs are missing or invalid")
    try:
        parsed = ResponseParser.parse(evaluator, required_item_ids=item_ids)
        fingerprint = _fingerprint_contract_state(state)
        report_fingerprint = _report_fingerprint(step["task_id"], step["worker_report"], fingerprint)
    except (TypeError, ValueError):
        raise ConflictError("Terminal frozen evaluator/fingerprint proof is invalid") from None
    if (
        fingerprints != [fingerprint, fingerprint] or step.get("replay_fingerprint") != report_fingerprint
        or state["prompt_version"] != evaluation.get("prompt_version")
        or state["prompt_version"] != PromptBuilder.PROMPT_VERSION
        or state["contract"] != {key: value for key, value in contract.items() if key != "evaluation_items"}
        or state["evaluation_items"] != items
        or parsed.verdict != "PASS" or parsed.covered != covered
        or evaluation.get("covered_item_ids") != covered or set(covered) != set(item_ids)
    ):
        raise ConflictError("Terminal frozen contract/report/coverage proof mismatch")
    return covered


def _terminal_evidence(
    uow: SAUnitOfWork, step_operation_key: str, *, fence: RuntimeStepFence | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    history = uow.step_history.get_by_step_operation_key(step_operation_key)
    if history is None:
        raise NotFoundError("Accepted terminal step not found")
    task_row = uow.tasks.lock(history.task_id)
    assignment_row = uow.tasks.get_assignment_by_operation_key(history.assignment_operation_key or "")
    if task_row is None or assignment_row is None:
        raise ConflictError("Terminal assignment/cursor missing")
    task, assignment, step = task_row.to_dict(), assignment_row.to_dict(), history.to_dict()
    admission = assignment["payload"].get("base_admission")
    if admission is None:
        raise ConflictError("Terminal receipt requires a Base assignment")
    if (
        assignment["payload_sha256"] != payload_sha256(assignment["payload"])
        or any(
            assignment.get(key) != assignment["payload"].get(key)
            for key in (
                "role_key", "workflow_key", "mode_key", "execution_scope", "cycle_number", "attempt_number",
                "assignment_ref", "work_item_revision", "stage_revision", "decomposition_revision_ref",
                "workspace_revision", "workspace_generation", "lease_generation", "exact_input_refs",
            )
        )
        or not assignment["bind_operation_key"] or not step["created_at"]
        or any(
            not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
            for value in (
                assignment["payload_sha256"], assignment["bind_request_sha256"], step["request_sha256"],
                step["replay_fingerprint"],
            )
        )
    ):
        raise ConflictError("Terminal assignment/bind/report ledger pins missing or mismatched")
    run = {
        "hermes_run_ref": assignment["hermes_run_ref"],
        "binding_ref": assignment["binding_ref"],
        "assignment_revision": assignment["assignment_revision"],
        "run_sequence": assignment["payload"].get("run_sequence", 0),
    }
    pm = PMExecutionService(uow)
    execution = pm.supervisor_binding(history.task_id, fence)
    if execution is not None:
        pm_run = pm.run(execution)
        run.update(
            hermes_run_ref=pm_run.run_ref, binding_ref=pm_run.binding_ref,
            execution_ref=execution.execution_ref, execution_version=execution.version,
            execution_fence=execution.fence, session_run_id=pm_run.session_run_id,
        )
    expected_task = {
        "assignment_operation_key": assignment["operation_key"],
        "assignment_revision": assignment["assignment_revision"],
        "project_id": assignment["project_id"], "workflow_id": assignment["workflow_id"],
        "mode_id": assignment["mode_id"], "mode_key": assignment["mode_key"],
        "cycle_number": assignment["cycle_number"], "status": "done",
        "current_phase_id": step["phase_id"],
    }
    expected_step = {
        "task_id": assignment["task_id"], "workflow_id": assignment["workflow_id"],
        "mode_id": assignment["mode_id"], "mode_key": assignment["mode_key"],
        "cycle_number": assignment["cycle_number"], "attempt_number": assignment["attempt_number"],
        "role_key": assignment["role_key"], "assignment_revision": assignment["assignment_revision"],
        "assignment_ref": assignment["assignment_ref"], "binding_ref": run["binding_ref"],
        "hermes_run_ref": run["hermes_run_ref"], "verdict": "pass",
        "next_phase_id": None, "rollback_phase_id": None,
    }
    if any(task.get(key) != value for key, value in expected_task.items()) or any(
        step.get(key) != value for key, value in expected_step.items()
    ):
        raise ConflictError("Terminal receipt assignment/run/cursor is stale or incomplete")
    phases = list(uow.phases.list(workflow_id=assignment["workflow_id"], mode_id=assignment["mode_id"]))
    if len(phases) != 3 or phases[-1].id != step["phase_id"]:
        raise ConflictError("Accepted report is not the terminal candidate phase")
    assert_base_step(
        uow, task, assignment, config_ref=admission["config_ref"], config_sha256=admission["config_sha256"],
    )
    response, evaluation = step["supervisor_response"], step["evaluation_snapshot"]
    if not isinstance(response, dict) or not isinstance(evaluation, dict):
        raise ConflictError("Terminal evaluator/response evidence is invalid")
    contract, evaluator = evaluation.get("contract_snapshot"), evaluation.get("raw_evaluator")
    if not isinstance(contract, dict) or not isinstance(evaluator, dict):
        raise ConflictError("Terminal accepted evaluator/contract is missing")
    _validate_frozen_evaluation(step, evaluation)
    if (
        not step["worker_report"].strip() or response.get("verdict") != "PASS"
        or response.get("status") != "done" or response.get("retryable") is not False
        or response.get("missing") != [] or response.get("blockers") != []
        or step["missing_item_ids"] or step["blocker_messages"]
        or evaluator.get("verdict") != "PASS"
        or not step["replay_fingerprint"]
    ):
        raise ConflictError("Terminal receipt requires a successful accepted evaluator report")
    expected_response = {
        "assignment_revision": assignment["assignment_revision"],
        "assignment_operation_key": assignment["operation_key"],
        "assignment_ref": assignment["assignment_ref"], "binding_ref": run["binding_ref"],
        "hermes_run_ref": run["hermes_run_ref"], "mode_key": assignment["mode_key"],
        "cycle_number": assignment["cycle_number"], "attempt_number": assignment["attempt_number"],
        "binding_state": "bound", "current_phase_code": phases[-1].code,
        "phase_code": phases[-1].code, "next_phase_code": None,
    }
    if any(response.get(key) != value for key, value in expected_response.items()):
        raise ConflictError("Accepted terminal response fence mismatch")
    events = [
        event.to_dict() for event in uow.tasks.list_phase_events(
            history.task_id, mode_id=assignment["mode_id"], cycle_number=assignment["cycle_number"],
        )
        if event.step_history_id == history.id and event.event_type == "completed"
        and event.phase_id == history.phase_id
    ]
    if len(events) != 1 or not events[0]["id"]:
        raise ConflictError("Terminal cursor has no exact accepted completion event")
    return task, assignment, step, run, events[0]


def build_terminal_receipt(
    uow: SAUnitOfWork, step_operation_key: str, *, fence: RuntimeStepFence,
) -> dict[str, Any]:
    """Called inside the existing report/cursor transaction, before its commit."""
    task, assignment, step, run, event = _terminal_evidence(uow, step_operation_key, fence=fence)
    return _receipt(task, assignment, step, run, event)


def _receipt(
    task: dict[str, Any], assignment: dict[str, Any], step: dict[str, Any],
    run: dict[str, Any], event: dict[str, Any],
) -> dict[str, Any]:
    response = {key: value for key, value in step["supervisor_response"].items() if key != "base_terminal_receipt"}
    response["complete"] = True
    cursor = {
        "revision": event["id"], "history_id": step["id"], "workflow_id": step["workflow_id"],
        "mode_id": step["mode_id"], "phase_id": step["phase_id"],
        "phase_code": response["current_phase_code"], "status": "done",
        "assignment_revision": step["assignment_revision"], "cycle_number": step["cycle_number"],
    }
    receipt = {
        "contract": RECEIPT_CONTRACT, "owner": "project-workflow",
        "receipt_ref": f"workflow-terminal:{step['step_operation_key']}", "complete": True,
        "task_key": task["task_key"], "business_task_ref": assignment["business_task_ref"],
        "root_task_ref": assignment["root_task_ref"], "work_item_ref": assignment["work_item_ref"],
        "work_item_revision": assignment["work_item_revision"], "stage_revision": assignment["stage_revision"],
        "decomposition_revision_ref": assignment["decomposition_revision_ref"],
        "workflow_key": assignment["workflow_key"], "role_key": assignment["role_key"],
        "mode_key": assignment["mode_key"], "execution_scope": assignment["execution_scope"],
        "cycle_number": assignment["cycle_number"], "attempt_number": assignment["attempt_number"],
        "assignment_ref": assignment["assignment_ref"], "assignment_revision": assignment["assignment_revision"],
        "assignment_operation_key": assignment["operation_key"], "assignment_sha256": assignment["payload_sha256"],
        "bind_operation_key": assignment["bind_operation_key"],
        "bind_request_sha256": assignment["bind_request_sha256"],
        "binding_assignment_revision": assignment["assignment_revision"],
        "concrete_agent_ref": assignment["concrete_agent_ref"],
        "binding_ref": run["binding_ref"], "hermes_run_ref": run["hermes_run_ref"],
        "run": {**run, "identity_sha256": payload_sha256(run)},
        "workspace_revision": assignment["workspace_revision"],
        "workspace_generation": assignment["workspace_generation"], "lease_generation": assignment["lease_generation"],
        "exact_input_refs_sha256": payload_sha256(assignment["exact_input_refs"]),
        "base_admission": assignment["payload"]["base_admission"],
        "step_operation_key": step["step_operation_key"], "request_sha256": step["request_sha256"],
        "worker_report_sha256": hashlib.sha256(step["worker_report"].encode("utf-8")).hexdigest(),
        "evaluation_sha256": payload_sha256(step["evaluation_snapshot"]),
        "accepted_response_sha256": payload_sha256(response),
        "cursor": {**cursor, "sha256": payload_sha256(cursor)}, "created_at": step["created_at"],
    }
    return {**receipt, "receipt_sha256": payload_sha256(receipt)}


def read_terminal_receipt(uow: SAUnitOfWork, step_operation_key: str) -> dict[str, Any]:
    """Only return the durable receipt; never manufacture one during lookup."""
    task, assignment, step, run, event = _terminal_evidence(uow, step_operation_key)
    stored = step["supervisor_response"].get("base_terminal_receipt")
    if not isinstance(stored, dict) or step["supervisor_response"].get("complete") is not True:
        raise ConflictError("Durable terminal workflow receipt missing")
    if stored != _receipt(task, assignment, step, run, event):
        raise ConflictError("Durable terminal workflow receipt mismatch")
    return stored
