"""Configured PM business execution on existing assignment and step history ledgers."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from project_workflow.domain.configured_cli import (
    PROTOCOL,
    ConfiguredAssignment,
    ConfiguredCliFence,
    ConfiguredStep,
    ConfiguredTerminalReadback,
    ConfiguredTerminalResponse,
)
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.infrastructure import configured_cli_tracker, namespace_auth
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import observe_installation
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def _catalog(uow: SAUnitOfWork, namespace_id: int) -> tuple[Any, Any, Any]:
    binding = next((b for b in observe_installation(uow).bindings if b.role_key == "project_manager"), None)
    if binding is None or int(binding.namespace_id) != namespace_id:
        raise ConflictError("Installed configured PM namespace required")
    project = uow.projects.get_by_id(namespace_id)
    if project is None:
        raise NotFoundError("Namespace not found")
    workflow = uow.workflows.lock(project.workflow_id)
    mode = uow.workflows.get_mode_by_key(project.workflow_id, "draft")
    if workflow is None or workflow.key != "single-task-v1:project_manager" or mode is None:
        raise ConflictError("Installed PM draft workflow required")
    return project, workflow, mode


def _row(uow: SAUnitOfWork, task: str, namespace_id: int) -> tuple[Any, Any, dict[str, Any]]:
    _catalog(uow, namespace_id)  # Catalog -> workflow -> task, like Supervisor evaluation.
    found = uow.tasks.get_by_key(task, project_id=namespace_id)
    if found is None or found.id is None:
        raise NotFoundError("Configured task not enrolled")
    current = uow.tasks.lock(found.id)
    if current is None:
        raise ConflictError("Configured task changed during admission")
    assignment = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
        m.TaskRuntimeAssignment.operation_key == current.assignment_operation_key,
        m.TaskRuntimeAssignment.task_id == current.id,
    )) if current is not None else None
    if assignment is None:
        raise ConflictError("Current configured assignment missing")
    payload = json.loads(assignment.payload)
    request = ConfiguredAssignment.model_validate(payload.get("request"))
    if (payload.get("interaction_protocol") != PROTOCOL or request.task != task
            or request.namespace_id != namespace_id or request.operation_key != assignment.operation_key
            or assignment.assignment_revision != current.assignment_revision
            or assignment.payload_sha256 is not None or assignment.hermes_run_ref is not None
            or assignment.bind_operation_key is not None):
        raise ConflictError("Configured assignment custody changed")
    return current, assignment, payload


def enroll(uow: SAUnitOfWork, request: ConfiguredAssignment) -> dict[str, Any]:
    from project_workflow.interfaces.cli.core import _require_valid_key

    _require_valid_key(request.task)
    project, workflow, mode = _catalog(uow, request.namespace_id)
    saved = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
        m.TaskRuntimeAssignment.operation_key == request.operation_key,
    ))
    if saved is not None:
        payload = json.loads(saved.payload)
        if payload.get("request") != request.model_dump(mode="json"):
            raise ConflictError("Enrollment operation key payload conflict")
        task, current, current_payload = _row(uow, request.task, request.namespace_id)
        if current.id != saved.id:
            raise ConflictError("Enrollment superseded")
        return cursor(uow, task, current_payload)
    if uow.tasks.get_by_key(request.task, project_id=project.id) is not None:
        raise ConflictError("Configured enrollment requires a new task; legacy tasks are immutable")
    configured_cli_tracker.assignment(request.model_dump(mode="json"))
    phases = list(uow.phases.list(workflow.id, mode_id=mode.id))
    if not phases or phases[0].code != "PM-DRAFT-01":
        raise ConflictError("PM initial phase missing")
    task_id = uow.tasks.create({"project_id": project.id, "workflow_id": workflow.id, "mode_id": mode.id,
        "task_key": request.task, "current_phase_id": phases[0].id, "cycle_number": 0,
        "status": "active", "assignment_operation_key": request.operation_key, "assignment_revision": 1})
    payload = {"interaction_protocol": PROTOCOL, "execution_ref": str(uuid4()),
               "request": request.model_dump(mode="json")}
    # Existing nullable metadata family; do not fabricate any native binding columns.
    uow.session.add(m.TaskRuntimeAssignment(operation_key=request.operation_key, task_id=task_id,
        project_id=project.id, workflow_id=workflow.id, mode_id=mode.id, cycle_number=0,
        assignment_revision=1, payload=canonical_json(payload)))
    uow.session.flush()
    result = cursor(uow, uow.tasks.get_by_id(task_id), payload)
    uow.commit()
    return result


def _records(uow: SAUnitOfWork, task_id: int, *, limit: int = 200) -> list[Any]:
    return list(uow.session.scalars(select(m.TaskStepHistoryEntry).where(
        m.TaskStepHistoryEntry.task_id == task_id,
    ).order_by(m.TaskStepHistoryEntry.id.desc()).limit(limit)))


def version(uow: SAUnitOfWork, task_id: int, payload: dict[str, Any]) -> int:
    rows = _records(uow, task_id, limit=1)
    if not rows:
        return 1
    metadata = json.loads(rows[0].evaluation_snapshot).get("configured_cli", {})
    value = metadata.get("result_version")
    if (type(value) is not int or value < 2 or metadata.get("execution_ref") != payload["execution_ref"]):
        raise ConflictError("Configured step ledger differs from current assignment")
    return value


def cursor(uow: SAUnitOfWork, task: Any, payload: dict[str, Any]) -> dict[str, Any]:
    request = payload["request"]
    phase = uow.phases.get_by_id(task.current_phase_id)
    return {"interaction_protocol": PROTOCOL, "execution_ref": payload["execution_ref"],
        "task": task.task_key, "namespace_id": task.project_id, "concrete_agent_ref": request["concrete_agent_ref"],
        "assignment_ref": request["assignment_ref"], "business_task_ref": request["business_task_ref"],
        "version": version(uow, task.id, payload), "phase_code": phase.code if phase else None,
        "status": task.status, "workflow_id": task.workflow_id, "mode_id": task.mode_id}


def _principal(authorization: str | None, *, write: bool) -> namespace_auth.NamespacePrincipal:
    principal, scopes = namespace_auth.introspect(authorization, require_service_account=True)
    if (f"project-workflow:{'write' if write else 'read'}" not in scopes
            or len(scopes) != len(set(scopes))
            or not set(scopes) <= {"project-workflow:read", "project-workflow:write"}):
        raise namespace_auth.NamespaceAuthError(403)
    return principal


def _assignment(principal: namespace_auth.NamespacePrincipal, payload: dict[str, Any]) -> None:
    if principal.subject != payload["request"]["machine_subject"]:
        raise namespace_auth.NamespaceAuthError(403)
    configured_cli_tracker.assignment(payload["request"])


def authorize(authorization: str | None, payload: dict[str, Any], *, write: bool) -> None:
    _assignment(_principal(authorization, write=write), payload)


def _replay(uow: SAUnitOfWork, fence: ConfiguredCliFence) -> dict[str, Any] | None:
    row = uow.session.scalar(select(m.TaskStepHistoryEntry).where(
        m.TaskStepHistoryEntry.task_id == fence.task_id,
        m.TaskStepHistoryEntry.replay_fingerprint == fence.operation_fingerprint,
    ))
    if row is None:
        return None
    metadata = json.loads(row.evaluation_snapshot).get("configured_cli", {})
    if (metadata.get("request_sha256") != fence.request_sha256
            or metadata.get("execution_ref") != fence.enrollment["execution_ref"]):
        raise ConflictError("Configured operation key payload conflict")
    return json.loads(row.supervisor_response)


def assert_fence(uow: UnitOfWork, task: dict[str, Any], fence: ConfiguredCliFence | None) -> bool:
    assignment = uow.tasks.get_assignment_by_operation_key(task.get("assignment_operation_key") or "")
    payload = assignment.payload if assignment is not None else {}
    if payload.get("interaction_protocol") != PROTOCOL:
        if fence is not None:
            raise ConflictError("Configured protocol cannot authorize legacy tasks")
        return False
    if fence is None or payload != fence.enrollment or payload_sha256(payload) != fence.assignment_sha256:
        raise ConflictError("Configured task requires authenticated configured runtime step")
    fence.assert_task(task)
    if not isinstance(uow, SAUnitOfWork):
        raise ConflictError("Configured step requires the durable business ledger")
    if version(uow, fence.task_id, payload) != fence.version:
        raise ConflictError("Configured expected version changed")
    return True


def step(uow: SAUnitOfWork, command: ConfiguredStep, authorization: str | None) -> dict[str, Any]:
    from project_workflow.supervisor import SupervisorEngine

    principal = _principal(authorization, write=command.report is not None)
    task, assignment, payload = _row(uow, command.task, command.namespace_id)
    _assignment(principal, payload)
    fence = ConfiguredCliFence(task.id, task.project_id, task.workflow_id, task.mode_id, task.cycle_number,
        task.assignment_revision, task.assignment_operation_key, payload_sha256(payload), task.current_phase_id,
        task.status, version(uow, task.id, payload), command, payload, authorization or "")
    if command.report is not None:
        replay = _replay(uow, fence)
        if replay is not None:
            return {"ok": True, "exit_code": 0, "result": replay, "output": replay.get("instructions", "")}
        if command.expected_version != fence.version or task.status == "done":
            raise ConflictError("Configured expected_version does not match current cursor")
    phase = uow.phases.get_by_id(task.current_phase_id)
    if command.report is not None and phase is not None and phase.code == "PM-DRAFT-03":
        confirmed = confirmation(payload)
        if (command.requirements_revision != confirmed["revision"]
                or command.requirements_sha256 != confirmed["content_hash"]):
            raise ConflictError("Final report must name the exact confirmed requirements revision/hash")
        fence = replace(fence, confirmation=confirmed)
    elif command.requirements_revision is not None:
        raise ConflictError("Requirements evidence is only accepted for the final PM report")
    engine = SupervisorEngine(command.task, uow=uow, project_id=task.project_id,
                              create_if_missing=False, runtime_fence=fence)
    if command.report is None:
        instructions = engine.format_current_phase_instructions()
        result = {**cursor(uow, task, payload), "instructions": instructions,
                  "phase_contract": engine.get_phase_contract(), "complete": task.status == "done"}
        if task.status == "done":
            result["terminal_receipt"] = json.loads(_records(uow, task.id, limit=1)[0].supervisor_response)[
                "terminal_receipt"]
        return {"ok": True, "exit_code": 0, "output": result["instructions"], "result": result}
    try:
        result = engine.evaluate(command.report)
    except (ConflictError, ValueError):
        uow.rollback()
        _, _, current_payload = _row(uow, command.task, command.namespace_id)
        authorize(authorization, current_payload, write=True)
        replay = _replay(uow, fence)
        if replay is None:
            raise
        result = replay
    if result.get("interaction_protocol") != PROTOCOL:
        raise ConflictError("Configured step did not commit an operation receipt")
    return {"ok": True, "exit_code": 0, "output": result.get("instructions", ""), "result": result}


def prepare_history(fence: ConfiguredCliFence, run_data: dict[str, Any]) -> None:
    run_data["replay_fingerprint"] = fence.operation_fingerprint
    run_data["evaluation_snapshot"]["configured_cli"] = {
        "execution_ref": fence.enrollment["execution_ref"], "operation_key": fence.request.operation_key,
        "request_sha256": fence.request_sha256, "result_version": fence.version + 1,
        "assignment_sha256": fence.assignment_sha256,
        "confirmation": fence.confirmation,
    }


def finish_history(uow: SAUnitOfWork, fence: ConfiguredCliFence, history_id: int, result: dict[str, Any]) -> None:
    authorize(fence.authorization, fence.enrollment, write=True)
    task = uow.tasks.get_by_id(fence.task_id)
    if task is None:
        raise ConflictError("Configured task disappeared before commit")
    result.update(cursor(uow, task, fence.enrollment))
    result["version"] = fence.version + 1
    result["complete"] = task.status == "done"
    if task.status == "done":
        if result.get("verdict") != "PASS" or result.get("missing") or result.get("blockers"):
            raise ConflictError("Terminal configured report is not a complete PASS")
        observed = confirmation(fence.enrollment)
        if fence.confirmation is None or observed != fence.confirmation:
            raise ConflictError("Owner confirmation changed during evaluation")
        receipt = {"interaction_protocol": PROTOCOL, "execution_ref": fence.enrollment["execution_ref"],
            "task": task.task_key, "tracker_task_id": fence.enrollment["request"]["tracker_task_id"],
            "namespace_id": task.project_id, "concrete_agent_ref": result["concrete_agent_ref"],
            "assignment_ref": result["assignment_ref"], "operation_key": fence.request.operation_key,
            "assignment_version": fence.enrollment["request"]["assignment_version"],
            "tracker_execution_id": fence.enrollment["request"]["tracker_execution_id"],
            "machine_subject": fence.enrollment["request"]["machine_subject"],
            "request_sha256": fence.request_sha256, "result_version": fence.version + 1,
            "requirements_revision": observed["revision"], "requirements_sha256": observed["content_hash"],
            "owner_subject": observed["owner_subject"], "confirmation_id": observed["id"],
            "history_id": history_id, "status": "done"}
        result["terminal_receipt"] = receipt
        result["workflow_receipt"] = {"reference": f"workflow-configured-cli:{receipt['execution_ref']}:{history_id}",
                                      "sha256": payload_sha256(receipt)}
    uow.step_history.update_supervisor_response(history_id, result)


def confirmation(payload: dict[str, Any]) -> dict[str, Any]:
    """Read actual Tracker latest revision and its saved owner confirmation at a fixed root."""
    return configured_cli_tracker.confirmation(payload["request"])


def history(uow: SAUnitOfWork, task: str, namespace_id: int, authorization: str | None, *,
            n: int, execution_ref: str | None, operation_key: str | None, trusted: bool) -> dict[str, Any]:
    principal = None if trusted else _principal(authorization, write=False)
    current, _, payload = _row(uow, task, namespace_id)
    if principal is not None:
        _assignment(principal, payload)
    elif execution_ref is None or operation_key is None:
        raise ConflictError("Trusted receipt readback requires execution_ref and operation_key")
    if execution_ref is not None and execution_ref != payload["execution_ref"]:
        raise ConflictError("Configured execution changed")
    if operation_key is not None:
        fingerprint = payload_sha256({"protocol": PROTOCOL, "assignment": current.assignment_operation_key,
                                      "operation_key": operation_key})
        rows = list(uow.session.scalars(select(m.TaskStepHistoryEntry).where(
            m.TaskStepHistoryEntry.task_id == current.id, m.TaskStepHistoryEntry.replay_fingerprint == fingerprint)))
        if not rows:
            raise NotFoundError("Configured operation receipt not found")
    else:
        rows = _records(uow, current.id, limit=n)
    records = [{"history_id": row.id, "result": json.loads(row.supervisor_response)} for row in rows]
    return {"ok": True, "exit_code": 0, "result": {**cursor(uow, current, payload), "records": records}}


def terminal_readback(uow: SAUnitOfWork, command: ConfiguredTerminalReadback) -> dict[str, Any]:
    """Return only a retained terminal operation, not current authority or a fabricated result."""
    current, _, payload = _row(uow, command.task, command.namespace_id)
    if command.execution_ref != payload["execution_ref"]:
        raise ConflictError("Configured execution changed")
    fingerprint = payload_sha256({"protocol": PROTOCOL, "assignment": current.assignment_operation_key,
                                  "operation_key": command.operation_key})
    row = uow.session.execute(select(m.TaskStepHistoryEntry).where(
        m.TaskStepHistoryEntry.task_id == current.id,
        m.TaskStepHistoryEntry.replay_fingerprint == fingerprint,
    )).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Configured operation receipt not found")
    saved = json.loads(row.supervisor_response)
    if saved.get("complete") is not True or saved.get("status") != "done" or current.status != "done":
        raise ConflictError("Configured operation is not terminal")
    result = ConfiguredTerminalResponse.model_validate({"ok": True, "complete": True,
        "receipt": saved.get("terminal_receipt"), "workflow_receipt": saved.get("workflow_receipt")})
    receipt = result.receipt.model_dump(mode="json")
    metadata = json.loads(row.evaluation_snapshot).get("configured_cli", {})
    enrollment = payload["request"]
    expected_reference = f"workflow-configured-cli:{command.execution_ref}:{row.id}"
    if (any(receipt.get(key) != value for key, value in command.model_dump(mode="json").items())
            or receipt["history_id"] != row.id or receipt["tracker_task_id"] != enrollment["tracker_task_id"]
            or receipt["concrete_agent_ref"] != enrollment["concrete_agent_ref"]
            or receipt["assignment_ref"] != enrollment["assignment_ref"]
            or receipt["assignment_version"] != enrollment["assignment_version"]
            or receipt["tracker_execution_id"] != enrollment["tracker_execution_id"]
            or receipt["machine_subject"] != enrollment["machine_subject"]
            or receipt["owner_subject"] != enrollment["owner_subject"]
            or receipt["request_sha256"] != metadata.get("request_sha256")
            or receipt["result_version"] != metadata.get("result_version")
            or metadata.get("assignment_sha256") != payload_sha256(payload)
            or metadata.get("execution_ref") != command.execution_ref
            or result.workflow_receipt.reference != expected_reference
            or result.workflow_receipt.sha256 != payload_sha256(receipt)):
        raise ConflictError("Retained terminal receipt tuple/hash differs")
    frozen = metadata.get("confirmation")
    if (not isinstance(frozen, dict) or frozen.get("stage") != "Draft"
            or frozen.get("id") != receipt["confirmation_id"]
            or frozen.get("revision") != receipt["requirements_revision"]
            or frozen.get("content_hash") != receipt["requirements_sha256"]
            or frozen.get("owner_subject") != receipt["owner_subject"]):
        raise ConflictError("Retained terminal evidence differs from the committed confirmation")
    return result.model_dump(mode="json")
