"""Immutable single-task completion receipts on the existing step ledger."""

import hashlib
from typing import Any

from project_workflow.application.base_terminal import _validate_frozen_evaluation
from project_workflow.application.single_task_runtime import current_binding
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.runtime_assignment import RuntimeStepFence, payload_sha256
from project_workflow.domain.single_task_runtime import SingleTaskTerminalReceipt, SingleTaskTerminalResponse
from project_workflow.infrastructure.db.uow import SAUnitOfWork

_RESULT_FIELDS = (
    "verdict", "status", "complete", "retryable", "phase_code", "current_phase_code",
    "next_phase_code", "rollback_phase_code", "assignment_operation_key", "assignment_revision",
    "assignment_ref", "binding_ref", "hermes_run_ref", "binding_state", "mode_key",
    "cycle_number", "attempt_number", "single_task_context_sha256",
)
_BIND_FIELDS = (
    "project_id", "task_key", "role_key", "bind_operation_key", "assignment_operation_key",
    "assignment_revision", "assignment_ref", "binding_ref", "hermes_run_ref", "mode_key",
    "cycle_number", "attempt_number", "expected_binding_state", "concrete_agent_ref",
    "instruction_profile", "instruction_manifest_sha256", "session_run_id",
)


def _body(
    uow: SAUnitOfWork, operation_key: str, *, fence: RuntimeStepFence | None = None,
) -> dict[str, Any]:
    history = uow.step_history.get_by_step_operation_key(operation_key)
    if history is None:
        raise NotFoundError("Accepted terminal step not found")
    task_row = uow.tasks.lock(history.task_id)
    assignment_row = uow.tasks.get_assignment_by_operation_key(history.assignment_operation_key or "")
    if task_row is None or assignment_row is None:
        raise ConflictError("Terminal task/assignment missing")
    task, assignment, step = task_row.to_dict(), assignment_row.to_dict(), history.to_dict()
    if assignment.get("role_key") not in {"analyst", "architect", "developer", "reviewer", "tester", "devops"}:
        raise ConflictError("Terminal delivery receipt requires a non-PM single-task assignment")
    binding = current_binding(uow, assignment)
    digest = payload_sha256(binding)
    evaluation, response = step["evaluation_snapshot"], step["supervisor_response"]
    expected_task = {
        "project_id": assignment["project_id"], "workflow_id": assignment["workflow_id"],
        "assignment_operation_key": assignment["operation_key"],
        "assignment_revision": assignment["assignment_revision"],
        "mode_id": assignment["mode_id"], "mode_key": assignment["mode_key"],
        "cycle_number": assignment["cycle_number"], "status": "done", "current_phase_id": step["phase_id"],
    }
    expected_step = {key: assignment[key] for key in (
        "task_id", "workflow_id", "mode_id", "mode_key", "cycle_number", "attempt_number", "role_key",
        "assignment_revision", "assignment_ref", "binding_ref", "hermes_run_ref",
    )}
    expected_step.update(assignment_operation_key=assignment["operation_key"], verdict="pass",
                         next_phase_id=None, rollback_phase_id=None)
    phases = list(uow.phases.list(workflow_id=assignment["workflow_id"], mode_id=assignment["mode_id"]))
    if (any(task.get(k) != v for k, v in expected_task.items())
        or any(step.get(k) != v for k, v in expected_step.items())
        or len(phases) != 3 or phases[-1].id != step["phase_id"]
        or not isinstance(evaluation, dict) or not isinstance(response, dict)
        or evaluation.get("single_task_binding") != binding
        or evaluation.get("single_task_context_sha256") != digest):
        raise ConflictError("Terminal assignment/run/phase is incomplete, stale or mismatched")
    if fence is not None:
        fence.assert_history(step)
    _validate_frozen_evaluation(step, evaluation)
    expected_response = {key: assignment[key] for key in (
        "assignment_revision", "assignment_ref", "binding_ref", "hermes_run_ref", "mode_key",
        "cycle_number", "attempt_number",
    )}
    expected_response.update(assignment_operation_key=assignment["operation_key"], verdict="PASS", status="done",
                             binding_state="bound", phase_code=phases[-1].code, current_phase_code=phases[-1].code,
                             next_phase_code=None, rollback_phase_code=None, single_task_context_sha256=digest,
                             retryable=False, missing=[], blockers=[])
    if (any(response.get(k) != v for k, v in expected_response.items())
        or not set(_RESULT_FIELDS) <= response.keys()
        or step["missing_item_ids"] or step["blocker_messages"] or not step["worker_report"].strip()):
        raise ConflictError("Terminal report/evaluator result is not an accepted complete PASS")
    events = [event for event in uow.tasks.list_phase_events(
        history.task_id, mode_id=assignment["mode_id"], cycle_number=assignment["cycle_number"],
    ) if event.step_history_id == history.id and event.phase_id == history.phase_id and event.event_type == "completed"]
    if len(events) != 1 or not events[0].id:
        raise ConflictError("Terminal history has no exact completion event")
    # Canonicalize the same stored bytes on build/read; no dynamic text redaction.
    accepted = {k: v for k, v in response.items() if k not in {"workflow_receipt", "single_task_terminal_receipt"}}
    accepted["complete"] = True
    public_binding = {
        "request": {k: binding["request"][k] for k in _BIND_FIELDS}, "context": binding["context"],
        "task_ref": binding["task_ref"], "root_ref": binding["root_ref"],
        "assignment_sha256": binding["assignment_sha256"],
    }
    return SingleTaskTerminalReceipt.model_validate({
        "schema": "single-task-sdlc/workflow-terminal-receipt/v1",
        "reference": f"workflow-terminal:single-task-v1:{assignment['project_id']}:{step['id']}", "complete": True,
        "binding": public_binding, "single_task_context_sha256": digest,
        "assignment_sha256": assignment["payload_sha256"],
        "cursor": {"task_key": task["task_key"], "namespace_id": assignment["project_id"],
                   "workflow_id": step["workflow_id"], "mode_id": step["mode_id"], "phase_id": step["phase_id"],
                   "phase_code": phases[-1].code, "status": "done", "history_id": step["id"],
                   "completion_event_id": events[0].id},
        "step": {"operation_key": operation_key, "request_sha256": step["request_sha256"],
                 "worker_report_sha256": hashlib.sha256(step["worker_report"].encode("utf-8")).hexdigest(),
                 "evaluation_sha256": payload_sha256(evaluation)},
        "result": {k: accepted[k] for k in _RESULT_FIELDS}, "accepted_response_sha256": payload_sha256(accepted),
    }).model_dump(mode="json", by_alias=True)


def build_terminal_receipt(uow: SAUnitOfWork, operation_key: str, *, fence: RuntimeStepFence) -> dict[str, Any]:
    """Called only inside the existing completion transaction."""
    body = _body(uow, operation_key, fence=fence)
    return {"receipt": body, "workflow_receipt": {"reference": body["reference"], "sha256": payload_sha256(body)}}


def read_terminal_receipt(uow: SAUnitOfWork, operation_key: str) -> dict[str, Any]:
    """Validate persisted evidence; never mint a receipt on lookup."""
    body = _body(uow, operation_key)
    history = uow.step_history.get_by_step_operation_key(operation_key)
    if history is None:
        raise NotFoundError("Accepted terminal step not found")
    response = history.supervisor_response
    artifact = {"reference": body["reference"], "sha256": payload_sha256(body)}
    if (response.get("complete") is not True or response.get("single_task_terminal_receipt") != body
        or response.get("workflow_receipt") != artifact):
        raise ConflictError("Durable terminal receipt is missing or mismatched")
    return SingleTaskTerminalResponse.model_validate({
        "ok": True, "complete": True, "receipt": response["single_task_terminal_receipt"],
        "workflow_receipt": response["workflow_receipt"],
    }).model_dump(mode="json", by_alias=True)
