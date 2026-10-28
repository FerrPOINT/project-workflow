"""Business execution on existing assignment and step history ledgers."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from project_workflow.domain.configured_cli import (
    PROTOCOL,
    ConfiguredArtifactReadback,
    ConfiguredAssignment,
    ConfiguredCliFence,
    ConfiguredStep,
    ConfiguredTerminalReadback,
    ConfiguredTerminalResponse,
)
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.domain.single_task_profile import CATALOG_SHA256, MANIFEST_SHA256
from project_workflow.infrastructure import configured_cli_tracker, namespace_auth
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import observe_installation
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.supervisor.evidence import validate_frozen_evaluation
from project_workflow.supervisor.types import VERDICT_LABELS


def _catalog(uow: SAUnitOfWork, namespace_id: int, *, workflow_key: str | None = None,
             workflow_id: int | None = None, mode_key: str | None = None,
             execution: bool = False) -> tuple[Any, Any, Any]:
    uow.lock_catalog_state(shared=True)
    project = uow.projects.get_by_id(namespace_id)
    if project is None:
        raise NotFoundError("Namespace not found")
    selected = (uow.workflows.get_by_id(workflow_id) if workflow_id is not None and not execution else
                next((w for w in uow.workflows.list_by_profession(namespace_id)
                     if (workflow_key is not None and w.key == workflow_key)
                     or (workflow_id is not None and w.id == workflow_id)), None))
    if selected is None or selected.id is None:
        raise ConflictError("Workflow must belong to the assigned profession")
    workflow = uow.workflows.lock(selected.id)
    if (workflow is None or workflow.id is None or workflow.key is None
            or execution and not uow.workflows.belongs_to_profession(workflow.id, namespace_id)):
        raise ConflictError("Profession workflow changed during admission")
    mode = uow.workflows.get_mode_by_key(workflow.id, mode_key) if mode_key is not None else None
    if mode_key is not None and mode is None:
        raise ConflictError("Installed profession mode required")
    if execution and workflow.key.startswith("single-task-v1:"):
        installed = observe_installation(uow)
        if execution and (installed.instruction_manifest_sha256 != MANIFEST_SHA256
                          or installed.workflow_catalog_sha256 != CATALOG_SHA256):
            raise ConflictError(
                "Current configured instruction catalog required; retained native profiles are read only")
        if not any(int(b.namespace_id) == namespace_id and int(b.workflow_id) == workflow.id
                   for b in installed.bindings):
            raise ConflictError("Installed profession/workflow required")
    return project, workflow, mode


def _stored_row(uow: SAUnitOfWork, task: str, namespace_id: int, *,
                execution_ref: str | None = None, execution: bool = False) -> tuple[Any, Any, dict[str, Any], Any]:
    found = uow.tasks.get_by_key(task, project_id=namespace_id)
    if found is None or found.id is None:
        raise NotFoundError("Configured task not enrolled")
    _, workflow, _ = _catalog(uow, namespace_id, workflow_id=found.workflow_id, execution=execution)
    current = uow.tasks.lock(found.id)
    if current is None:
        raise ConflictError("Configured task changed during admission")
    query = select(m.TaskRuntimeAssignment).where(m.TaskRuntimeAssignment.task_id == current.id)
    if execution_ref is None:
        assignment = uow.session.scalar(query.where(
            m.TaskRuntimeAssignment.operation_key == current.assignment_operation_key))
    else:
        assignment = next((row for row in uow.session.scalars(query.order_by(
            m.TaskRuntimeAssignment.id.desc())).yield_per(32)
            if json.loads(row.payload).get("execution_ref") == execution_ref), None)
    if assignment is None:
        raise ConflictError("Current configured assignment missing")
    payload = json.loads(assignment.payload)
    if (current.workflow_id != workflow.id or assignment.workflow_id != workflow.id
            or assignment.project_id != namespace_id or assignment.task_id != current.id
            or execution_ref is None and (assignment.assignment_revision != current.assignment_revision
                                          or assignment.mode_id != current.mode_id
                                          or assignment.cycle_number != current.cycle_number)):
        raise ConflictError("Stored assignment custody changed")
    return current, assignment, payload, workflow


def _configured_row(uow: SAUnitOfWork, task: str, namespace_id: int,
                    stored: tuple[Any, Any, dict[str, Any], Any]) -> tuple[Any, Any, dict[str, Any]]:
    current, assignment, payload, workflow = stored
    request = ConfiguredAssignment.model_validate(payload.get("request"))
    mode = uow.workflows.get_mode(assignment.mode_id, workflow.id)
    if (payload.get("interaction_protocol") != PROTOCOL or request.task != task
            or request.namespace_id != namespace_id or request.operation_key != assignment.operation_key
            or request.workflow_key != workflow.key
            or mode is None or mode.key != request.mode_key
            or assignment.payload_sha256 is not None or assignment.hermes_run_ref is not None
            or assignment.bind_operation_key is not None):
        raise ConflictError("Configured assignment custody changed")
    return current, assignment, payload


def _row(uow: SAUnitOfWork, task: str, namespace_id: int, *,
         execution_ref: str | None = None, execution: bool = False) -> tuple[Any, Any, dict[str, Any]]:
    return _configured_row(uow, task, namespace_id, _stored_row(uow, task, namespace_id,
                                                               execution_ref=execution_ref, execution=execution))


def _legacy_cursor(uow: SAUnitOfWork, stored: tuple[Any, Any, dict[str, Any], Any]) -> dict[str, Any]:
    """Decode the retired assignment only for history/CAS adoption, never execution.

    Tracker proves the new current assignment. Native quiescence belongs to the
    cutover/Fleet gate, not to a second Workflow execution/bind protocol.
    """
    current, assignment, payload, workflow = stored
    mode = uow.workflows.get_mode(assignment.mode_id, workflow.id)
    if (payload.get("interaction_protocol") is not None
            or not isinstance(payload.get("single_task_context"), dict)
            or assignment.payload_sha256 != payload_sha256(payload)
            or payload.get("task_key") != current.task_key or payload.get("project_id") != current.project_id
            or payload.get("workflow_id") != current.workflow_id or payload.get("workflow_key") != workflow.key
            or payload.get("business_task_ref") != assignment.business_task_ref
            or payload.get("root_task_ref") != assignment.root_task_ref
            or assignment.business_task_ref != assignment.root_task_ref
            or payload.get("role_key") != assignment.role_key
            or workflow.key != f"single-task-v1:{assignment.role_key}"
            or payload.get("assignment_ref") != assignment.assignment_ref
            or mode is None or payload.get("mode_key") != mode.key):
        raise ConflictError("Unrecognized historical single-task assignment")
    last = _records(uow, current.id, limit=1)
    # Both terms are monotonic retained Workflow ledger coordinates. This CAS
    # token is unrelated to Tracker's fencing counter or the old native fence.
    version = current.assignment_revision + (last[0].id if last else 0)
    return {"interaction_protocol": PROTOCOL, "task": current.task_key, "namespace_id": current.project_id,
            "version": version, "legacy_read_only": True, "records": []}


def enroll(uow: SAUnitOfWork, request: ConfiguredAssignment) -> dict[str, Any]:
    from project_workflow.interfaces.cli.core import _require_valid_key

    _require_valid_key(request.task)
    project, workflow, mode = _catalog(uow, request.namespace_id,
                                     workflow_key=request.workflow_key, mode_key=request.mode_key, execution=True)
    saved = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
        m.TaskRuntimeAssignment.operation_key == request.operation_key,
    ))
    if saved is not None:
        payload = json.loads(saved.payload)
        if payload.get("request") != request.model_dump(mode="json"):
            raise ConflictError("Enrollment operation key payload conflict")
        _, current, _ = _row(uow, request.task, request.namespace_id)
        if current.id != saved.id:
            raise ConflictError("Enrollment superseded")
        original = payload.get("enrollment_result")
        if not isinstance(original, dict):
            raise ConflictError("Historical enrollment has no original cursor; use history readback")
        return original
    configured_cli_tracker.assignment(request.model_dump(mode="json"))
    phases = list(uow.phases.list(workflow.id, mode_id=mode.id))
    if not phases:
        raise ConflictError("Assigned mode has no initial phase")
    previous = uow.tasks.get_by_key(request.task, project_id=project.id)
    cycle, revision, initial_version, history_after_id = 0, 1, 1, 0
    if previous is None:
        # Old technical assignments used their own SDLC ordinal, whereas new
        # tasks may use a root key. Never silently start phase one under another
        # key and leave the real unfinished task behind. Tracker's cutover must
        # retain the profession's existing key before authorizing enrollment.
        retained = uow.session.scalar(select(m.TaskRuntimeAssignment).join(
            m.Task, m.Task.id == m.TaskRuntimeAssignment.task_id).where(
                m.TaskRuntimeAssignment.project_id == project.id,
                m.TaskRuntimeAssignment.business_task_ref == request.business_task_ref,
                m.Task.assignment_operation_key == m.TaskRuntimeAssignment.operation_key,
            ).order_by(m.TaskRuntimeAssignment.id.desc()).limit(1))
        if retained is not None:
            raise ConflictError("Retained business task uses another Workflow key; reconcile the verified Tracker key")
        if request.expected_version != 0:
            raise ConflictError("Initial enrollment requires expected_version=0")
        task_id = uow.tasks.create({"project_id": project.id, "workflow_id": workflow.id, "mode_id": mode.id,
            "task_key": request.task, "current_phase_id": phases[0].id, "cycle_number": cycle,
            "status": "active", "assignment_operation_key": request.operation_key, "assignment_revision": revision})
    else:
        stored = _stored_row(uow, request.task, request.namespace_id)
        legacy = stored[2].get("interaction_protocol") != PROTOCOL
        if legacy:
            current, assignment, old, _ = stored
            current_version = _legacy_cursor(uow, stored)["version"]
            accepted = {"assignment_ref": assignment.assignment_ref, "business_task_ref": assignment.business_task_ref,
                        "role_key": assignment.role_key}
        else:
            current, _, old = _configured_row(uow, request.task, request.namespace_id, stored)
            accepted = old["request"]
            current_version = version(uow, current.id, old)
        if (request.expected_version != current_version
                or not legacy and request.assignment_version <= accepted["assignment_version"]
                or request.assignment_ref == accepted["assignment_ref"]
                or request.business_task_ref != accepted["business_task_ref"]
                or request.role_key != accepted["role_key"]
                or current.status != "done" and mode.id != current.mode_id):
            raise ConflictError("Replacement requires a newer verified assignment and the current Workflow version")
        task_id, revision = current.id, current.assignment_revision + 1
        cycle = current.cycle_number + int(current.status == "done")
        initial_version = current_version + 1
        last = _records(uow, task_id, limit=1)
        history_after_id = last[0].id if last else 0
        phase_id = phases[0].id if current.status == "done" else current.current_phase_id
        if phase_id is None:
            raise ConflictError("Current Workflow phase missing")
        uow.tasks.update(task_id, {"mode_id": mode.id, "cycle_number": cycle,
            "current_phase_id": phase_id,
            "status": "active", "assignment_operation_key": request.operation_key, "assignment_revision": revision})
        uow.tasks.record_phase_event(task_id, phase_id,
                                    "entered" if current.status == "done" else "resumed")
    payload = {"interaction_protocol": PROTOCOL, "execution_ref": str(uuid4()),
               "initial_version": initial_version, "history_after_id": history_after_id,
               "request": request.model_dump(mode="json")}
    result = cursor(uow, uow.tasks.get_by_id(task_id), payload)
    payload["enrollment_result"] = result
    # Existing nullable metadata family; do not fabricate any native binding columns.
    uow.session.add(m.TaskRuntimeAssignment(operation_key=request.operation_key, task_id=task_id,
        project_id=project.id, workflow_id=workflow.id, mode_id=mode.id, cycle_number=cycle,
        assignment_revision=revision, payload=canonical_json(payload)))
    uow.session.flush()
    uow.commit()
    return result


def _records(uow: SAUnitOfWork, task_id: int, *, limit: int = 200, cycle: int | None = None,
             after_id: int = 0, before_id: int | None = None) -> list[Any]:
    query = select(m.TaskStepHistoryEntry).where(m.TaskStepHistoryEntry.task_id == task_id,
                                               m.TaskStepHistoryEntry.id > after_id)
    if cycle is not None:
        query = query.where(m.TaskStepHistoryEntry.cycle_number == cycle)
    if before_id is not None:
        query = query.where(m.TaskStepHistoryEntry.id < before_id)
    return list(uow.session.scalars(query.order_by(m.TaskStepHistoryEntry.id.desc()).limit(limit)))


def _history_page(uow: SAUnitOfWork, task_id: int, n: int, before: int | None) -> dict[str, Any]:
    rows = _records(uow, task_id, limit=n + 1, before_id=before)
    return {"records": [{"history_id": row.id, "worker_report": row.worker_report,
                         "result": json.loads(row.supervisor_response)} for row in rows[:n]],
            "next_before": rows[n - 1].id if len(rows) > n else None}


def _evaluation(row: m.TaskStepHistoryEntry) -> dict[str, Any]:
    value = json.loads(row.evaluation_snapshot)
    if not isinstance(value, dict) or not isinstance(value.get("configured_cli"), dict):
        raise ConflictError("Configured evaluation ledger is invalid")
    return value


def version(uow: SAUnitOfWork, task_id: int, payload: dict[str, Any]) -> int:
    current = uow.tasks.get_by_id(task_id)
    if current is None:
        raise ConflictError("Current Workflow task missing")
    rows = _records(uow, task_id, limit=1, cycle=current.cycle_number, after_id=payload.get("history_after_id", 0))
    if not rows:
        return payload.get("initial_version", 1)
    metadata = _evaluation(rows[0])["configured_cli"]
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


def _assignment(principal: namespace_auth.NamespacePrincipal, payload: dict[str, Any], *,
                allow_completed_read: bool = False) -> None:
    if principal.subject != payload["request"]["machine_subject"]:
        raise namespace_auth.NamespaceAuthError(403)
    configured_cli_tracker.assignment(payload["request"], allow_completed_read=allow_completed_read)


def authorize(authorization: str | None, payload: dict[str, Any], *, write: bool) -> None:
    _assignment(_principal(authorization, write=write), payload)


def _replay(uow: SAUnitOfWork, fence: ConfiguredCliFence) -> dict[str, Any] | None:
    row = uow.session.scalar(select(m.TaskStepHistoryEntry).where(
        m.TaskStepHistoryEntry.task_id == fence.task_id,
        m.TaskStepHistoryEntry.replay_fingerprint == fence.operation_fingerprint,
    ))
    if row is None:
        return None
    metadata = _evaluation(row)["configured_cli"]
    if (metadata.get("request_sha256") != fence.request_sha256
            or metadata.get("execution_ref") != fence.enrollment["execution_ref"]):
        raise ConflictError("Configured operation key payload conflict")
    saved = json.loads(row.supervisor_response)
    if saved.get("complete") is True:
        _terminal_proof(row, fence.enrollment, saved)
    return saved


def step(uow: SAUnitOfWork, command: ConfiguredStep, authorization: str | None) -> dict[str, Any]:
    from project_workflow.supervisor import SupervisorEngine

    principal = _principal(authorization, write=command.report is not None)
    task, assignment, payload = _row(uow, command.task, command.namespace_id, execution=True)
    _assignment(principal, payload, allow_completed_read=task.status == "done")
    fence = ConfiguredCliFence(task.id, task.project_id, task.workflow_id, task.mode_id, task.cycle_number,
        task.assignment_revision, task.assignment_operation_key, payload_sha256(payload), task.current_phase_id,
        task.status, version(uow, task.id, payload), command, payload, authorization or "")
    if command.report is not None:
        replay = _replay(uow, fence)
        if replay is not None:
            return {"ok": True, "exit_code": 0, "result": replay, "output": replay.get("instructions", "")}
        if command.expected_version != fence.version or task.status == "done":
            raise ConflictError("Configured expected_version does not match current cursor")
    engine = SupervisorEngine(command.task, uow=uow, project_id=task.project_id,
                              create_if_missing=False, runtime_fence=fence)
    phase = engine.phase_map.get(engine.current_phase_code or "")
    final_pm = False
    if payload["request"]["role_key"] == "project_manager" and phase is not None:
        group = engine.contract_builder.get_parallel_group(phase) if phase.execution_type == "parallel" else [phase]
        final_pm = engine._resolve_transition(phase, "pass", group)[0] is None
    if command.report is not None and final_pm:
        confirmed = confirmation(payload)
        if (command.requirements_revision != confirmed["revision"]
                or command.requirements_sha256 != confirmed["content_hash"]):
            raise ConflictError("Final report must name the exact confirmed requirements revision/hash")
        fence = replace(fence, confirmation=confirmed)
        engine.runtime_fence = fence
    elif command.requirements_revision is not None:
        raise ConflictError("Requirements evidence is only accepted for the final PM report")
    if command.report is None:
        instructions = engine.format_current_phase_instructions()
        result = {**cursor(uow, task, payload), "instructions": instructions,
                  "phase_contract": engine.get_phase_contract(), "complete": task.status == "done"}
        if final_pm and task.status != "done":
            result["report_parameters"] = ["--requirements-revision", "--requirements-sha256"]
        if task.status == "done":
            final_row = _records(uow, task.id, limit=1)[0]
            saved = json.loads(final_row.supervisor_response)
            _terminal_proof(final_row, payload, saved)
            for key in ("terminal_receipt", "workflow_receipt", "completion_instructions"):
                if key in saved:
                    result[key] = saved[key]
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
    if not uow.workflows.belongs_to_profession(fence.workflow_id, fence.namespace_id):
        raise ConflictError("Workflow left the profession during evaluation")
    task = uow.tasks.get_by_id(fence.task_id)
    if task is None:
        raise ConflictError("Configured task disappeared before commit")
    result.update(cursor(uow, task, fence.enrollment))
    result["version"] = fence.version + 1
    result["complete"] = task.status == "done"
    if task.status == "done":
        if result.get("verdict") != "PASS" or result.get("missing") or result.get("blockers"):
            raise ConflictError("Terminal configured report is not a complete PASS")
        is_pm = fence.enrollment["request"]["role_key"] == "project_manager"
        observed = confirmation(fence.enrollment) if is_pm else None
        if is_pm and (fence.confirmation is None or observed != fence.confirmation):
            raise ConflictError("Owner confirmation changed during evaluation")
        receipt = {"interaction_protocol": PROTOCOL, "execution_ref": fence.enrollment["execution_ref"],
            "task": task.task_key, "tracker_task_id": fence.enrollment["request"]["tracker_task_id"],
            "namespace_id": task.project_id, "concrete_agent_ref": result["concrete_agent_ref"],
            "assignment_ref": result["assignment_ref"], "operation_key": fence.request.operation_key,
            "assignment_version": fence.enrollment["request"]["assignment_version"],
            "tracker_execution_id": fence.enrollment["request"]["tracker_execution_id"],
            "machine_subject": fence.enrollment["request"]["machine_subject"],
            "request_sha256": fence.request_sha256, "result_version": fence.version + 1,
            "requirements_revision": observed["revision"] if observed else None,
            "requirements_sha256": observed["content_hash"] if observed else None,
            "owner_subject": fence.enrollment["request"]["owner_subject"],
            "confirmation_id": observed["id"] if observed else None,
            "history_id": history_id, "status": "done"}
        result["terminal_receipt"] = receipt
        result["workflow_receipt"] = {"reference": f"workflow-configured-cli:{receipt['execution_ref']}:{history_id}",
                                      "sha256": payload_sha256(receipt)}
        from project_workflow.infrastructure.single_task_delivery_instructions import completion_instruction

        result["completion_instructions"] = completion_instruction(fence.enrollment["request"]["role_key"])
    uow.step_history.update_supervisor_response(history_id, result)


def confirmation(payload: dict[str, Any]) -> dict[str, Any]:
    """Read actual Tracker latest revision and its saved owner confirmation at a fixed root."""
    return configured_cli_tracker.confirmation(payload["request"])


def history(uow: SAUnitOfWork, task: str, namespace_id: int, authorization: str | None, *,
            n: int, execution_ref: str | None, operation_key: str | None, trusted: str | None,
            principal: namespace_auth.NamespacePrincipal | None = None,
            assignment_operation_key: str | None = None, projection: str | None = None,
            before_history_id: int | None = None) -> dict[str, Any]:
    if (type(n) is not int or not 1 <= n <= 200 or before_history_id is not None
            and (type(before_history_id) is not int or not 1 <= before_history_id <= 2**63 - 1)):
        raise ValueError("Invalid bounded history cursor")
    principal = None if trusted else principal or _principal(authorization, write=False)
    stored = _stored_row(uow, task, namespace_id)
    if stored[2].get("interaction_protocol") != PROTOCOL:
        if trusted is None or trusted != stored[1].role_key:
            raise namespace_auth.NamespaceAuthError(403)
        result = _legacy_cursor(uow, stored)
        if assignment_operation_key is not None:
            raise NotFoundError("Configured enrollment operation not found")
        if operation_key is not None or execution_ref is not None:
            raise ConflictError("Retired execution selectors cannot authorize configured operations")
        if projection is not None:
            if projection != "fleet-summary-v1" or before_history_id is not None and before_history_id <= 0:
                raise ConflictError("Invalid history projection selectors")
            summary = history_summary(uow, task, namespace_id, n, before_history_id)
            return {"ok": True, "exit_code": 0, "output": json.dumps(summary["records"], ensure_ascii=False),
                    "result": summary}
        result.update(_history_page(uow, stored[0].id, n, before_history_id))
        return {"ok": True, "exit_code": 0, "result": result}
    current, _, payload = _configured_row(uow, task, namespace_id, stored)
    if trusted is not None and trusted != payload["request"]["role_key"]:
        raise namespace_auth.NamespaceAuthError(403)
    if principal is not None:
        _assignment(principal, payload, allow_completed_read=True)
    if projection is not None:
        if (projection != "fleet-summary-v1" or not 1 <= n <= 200
                or any(value is not None for value in (execution_ref, operation_key, assignment_operation_key))
                or before_history_id is not None and before_history_id <= 0):
            raise ConflictError("Invalid history projection selectors")
        summary = history_summary(uow, task, namespace_id, n, before_history_id)
        return {"ok": True, "exit_code": 0, "output": json.dumps(summary["records"], ensure_ascii=False),
                "result": summary}
    if before_history_id is not None and (operation_key is not None or assignment_operation_key is not None):
        raise ConflictError("History cursor cannot select an operation")
    if assignment_operation_key is not None:
        if operation_key is not None or execution_ref is not None:
            raise ConflictError("Select one operation identity")
        saved = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
            m.TaskRuntimeAssignment.task_id == current.id,
            m.TaskRuntimeAssignment.operation_key == assignment_operation_key))
        if saved is None:
            raise NotFoundError("Enrollment operation not found")
        retained = json.loads(saved.payload)
        original = retained.get("enrollment_result")
        if (retained.get("interaction_protocol") != PROTOCOL or not isinstance(original, dict)
                or retained.get("request", {}).get("namespace_id") != namespace_id):
            raise ConflictError("Historical assignment is not a configured enrollment operation")
        return {"ok": True, "exit_code": 0, "result": {**cursor(uow, current, payload), "records": [],
            "assignment_operation": {"request": retained["request"], "result": original}}}
    if execution_ref is not None and execution_ref != payload["execution_ref"]:
        raise ConflictError("Configured execution changed")
    if operation_key is not None:
        fingerprint = payload_sha256({"protocol": PROTOCOL, "assignment": current.assignment_operation_key,
                                      "operation_key": operation_key})
        rows = list(uow.session.scalars(select(m.TaskStepHistoryEntry).where(
            m.TaskStepHistoryEntry.task_id == current.id, m.TaskStepHistoryEntry.replay_fingerprint == fingerprint)))
        if not rows:
            raise NotFoundError("Configured operation receipt not found")
        page = {"records": [{"history_id": row.id, "worker_report": row.worker_report,
                             "result": json.loads(row.supervisor_response)} for row in rows], "next_before": None}
    else:
        page = _history_page(uow, current.id, n, before_history_id)
    return {"ok": True, "exit_code": 0, "result": {**cursor(uow, current, payload), **page}}


def _terminal_proof(row: m.TaskStepHistoryEntry, payload: dict[str, Any], saved: dict[str, Any]) -> None:
    receipt = saved.get("terminal_receipt")
    if not isinstance(receipt, dict) or row.verdict != "pass":
        raise ConflictError("Retained terminal accepted PASS receipt missing")
    try:
        report = ConfiguredStep.model_validate({
            "interaction_protocol": PROTOCOL, "task": receipt.get("task"),
            "namespace_id": receipt.get("namespace_id"), "operation_key": receipt.get("operation_key"),
            "expected_version": receipt["result_version"] - 1, "report": row.worker_report,
            "requirements_revision": receipt.get("requirements_revision"),
            "requirements_sha256": receipt.get("requirements_sha256"),
        })
        evaluation = _evaluation(row)
    except (KeyError, TypeError, ValueError):
        raise ConflictError("Retained terminal report evidence is invalid") from None
    fingerprint = payload_sha256({"protocol": PROTOCOL, "assignment": payload["request"]["operation_key"],
                                  "operation_key": report.operation_key})
    if payload_sha256(report.model_dump(mode="json")) != receipt.get("request_sha256"):
        raise ConflictError("Retained terminal report differs from the committed request")
    validate_frozen_evaluation({
        "task_id": row.task_id, "worker_report": row.worker_report,
        "covered_item_ids": json.loads(row.covered_item_ids), "replay_fingerprint": row.replay_fingerprint,
    }, evaluation, replay_fingerprint=fingerprint)


def terminal_readback(uow: SAUnitOfWork, command: ConfiguredTerminalReadback) -> dict[str, Any]:
    """Return only a retained terminal operation, not current authority or a fabricated result."""
    current, assignment, payload = _row(uow, command.task, command.namespace_id,
                                      execution_ref=command.execution_ref)
    fingerprint = payload_sha256({"protocol": PROTOCOL, "assignment": assignment.operation_key,
                                  "operation_key": command.operation_key})
    row = uow.session.execute(select(m.TaskStepHistoryEntry).where(
        m.TaskStepHistoryEntry.task_id == current.id,
        m.TaskStepHistoryEntry.replay_fingerprint == fingerprint,
    )).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Configured operation receipt not found")
    saved = json.loads(row.supervisor_response)
    if (saved.get("complete") is not True or saved.get("status") != "done"
            or row.cycle_number != assignment.cycle_number or row.mode_id != assignment.mode_id):
        raise ConflictError("Configured operation is not terminal")
    _terminal_proof(row, payload, saved)
    result = ConfiguredTerminalResponse.model_validate({"ok": True, "complete": True,
        "receipt": saved.get("terminal_receipt"), "workflow_receipt": saved.get("workflow_receipt")})
    receipt = result.receipt.model_dump(mode="json")
    metadata = _evaluation(row)["configured_cli"]
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
    if enrollment["role_key"] == "project_manager" and (not isinstance(frozen, dict) or frozen.get("stage") != "Draft"
            or frozen.get("id") != receipt["confirmation_id"]
            or frozen.get("revision") != receipt["requirements_revision"]
            or frozen.get("content_hash") != receipt["requirements_sha256"]
            or frozen.get("owner_subject") != receipt["owner_subject"]):
        raise ConflictError("Retained terminal evidence differs from the committed confirmation")
    if enrollment["role_key"] != "project_manager" and (frozen is not None or receipt["confirmation_id"] is not None
            or receipt["requirements_revision"] is not None or receipt["requirements_sha256"] is not None):
        raise ConflictError("Non-PM terminal receipt cannot assert owner confirmation")
    return result.model_dump(mode="json")


def artifact_readback(uow: SAUnitOfWork, command: ConfiguredArtifactReadback, role: str) -> dict[str, Any]:
    """Resolve the already published artifact, without caller-supplied receipt fields."""
    match = re.fullmatch(r"workflow-configured-cli:([0-9a-f-]{36}):([1-9][0-9]{0,18})",
                         command.workflow_receipt.reference)
    if match is None:
        raise ConflictError("Invalid Workflow artifact reference")
    row = uow.session.get(m.TaskStepHistoryEntry, int(match[2]))
    if row is None:
        raise NotFoundError("Workflow artifact not found")
    saved = ConfiguredTerminalResponse.model_validate({"ok": True, "complete": True,
        "receipt": json.loads(row.supervisor_response).get("terminal_receipt"),
        "workflow_receipt": json.loads(row.supervisor_response).get("workflow_receipt")})
    if saved.workflow_receipt != command.workflow_receipt or saved.receipt.execution_ref != match[1]:
        raise ConflictError("Workflow artifact identity/hash differs")
    _, _, payload = _row(uow, saved.receipt.task, saved.receipt.namespace_id,
                         execution_ref=saved.receipt.execution_ref)
    if payload["request"]["role_key"] != role:
        raise namespace_auth.NamespaceAuthError(403)
    selector = ConfiguredTerminalReadback.model_validate({
        key: saved.receipt.model_dump(mode="json")[key] for key in ConfiguredTerminalReadback.model_fields})
    return terminal_readback(uow, selector)


def history_summary(
    uow: SAUnitOfWork, task_key: str, namespace_id: int, n: int, before: int | None,
) -> dict[str, Any]:
    entries = uow.step_history.list(
        task_key=task_key, project_id=namespace_id, limit=n + 1, before_history_id=before,
    )
    phase_ids = {
        phase_id for entry in entries[:n]
        for phase_id in (entry.phase_id, entry.next_phase_id, entry.rollback_phase_id)
        if phase_id is not None
    }
    phases = {phase_id: uow.phases.get_by_id(phase_id) for phase_id in phase_ids}
    records: list[dict[str, Any]] = []
    for entry in entries[:n]:
        phase = phases.get(entry.phase_id)
        next_phase = phases.get(entry.next_phase_id) if entry.next_phase_id is not None else None
        rollback = phases.get(entry.rollback_phase_id) if entry.rollback_phase_id is not None else None
        if not isinstance(entry.supervisor_response, dict):
            raise ConflictError("Stored history summary response is invalid")
        status = entry.supervisor_response.get("status")
        retryable = entry.supervisor_response.get("retryable")
        if (entry.id is None or entry.id <= 0 or phase is None or entry.verdict not in VERDICT_LABELS
            or (status is not None and status not in ("active", "blocked", "done"))
            or (retryable is not None and type(retryable) is not bool)
            or (entry.next_phase_id is not None and next_phase is None)
            or (entry.rollback_phase_id is not None and rollback is None)):
            raise ConflictError("Stored history summary fields are invalid")
        records.append({
            "history_id": str(entry.id), "step_operation_key": entry.step_operation_key or (
                entry.evaluation_snapshot.get("configured_cli", {}).get("operation_key")),
            "phase_code": phase.code, "verdict": entry.verdict, "status": status,
            "retryable": retryable,
            "next_phase_code": next_phase.code if next_phase else None,
            "rollback_phase_code": rollback.code if rollback else None, "created_at": entry.created_at,
        })
    return {"projection": "fleet-summary-v1", "task_key": task_key, "count": len(records),
            "records": records, "next_before": records[-1]["history_id"] if len(entries) > n else None}
