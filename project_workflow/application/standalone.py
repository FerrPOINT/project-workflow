"""Local admission and operation ledger around the shared phase evaluator."""

import json
from typing import Any

from sqlalchemy import select

from project_workflow.config import get_settings
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.domain.standalone import StandaloneFence, StandaloneStep
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def validate_database(uow: SAUnitOfWork) -> None:
    if get_settings().PROJECT_WORKFLOW_MODE != "standalone":
        raise ConflictError("Standalone execution is not enabled")
    if uow.session.scalar(select(m.PMNamespaceOwnership.ownership_ref).limit(1)) is not None:
        raise ConflictError("Platform-owned namespaces cannot be opened without authentication")
    if uow.session.scalar(select(m.ResourceExecutionContext.id).limit(1)) is not None:
        raise ConflictError("Platform execution contexts require platform mode")
    if uow.session.scalar(select(m.TaskRuntimeAssignment.id).where(
        m.TaskRuntimeAssignment.business_task_ref.is_not(None)
        | m.TaskRuntimeAssignment.concrete_agent_ref.is_not(None)
        | m.TaskRuntimeAssignment.binding_ref.is_not(None)).limit(1)) is not None:
        raise ConflictError("Platform assignments cannot be opened without authentication")


def _rows(uow: SAUnitOfWork, task: Any, *, limit: int | None = None):
    return uow.step_history.list(task_id=task.id, mode_id=task.mode_id,
                                 cycle_number=task.cycle_number, limit=limit)


def version(uow: SAUnitOfWork, task: Any) -> int:
    rows = _rows(uow, task, limit=1)
    if not rows:
        return 1
    metadata = rows[0].to_dict().get("evaluation_snapshot", {}).get("standalone")
    if not isinstance(metadata, dict) or type(metadata.get("result_version")) is not int:
        raise ConflictError("Current standalone operation ledger required")
    return metadata["result_version"]


def _task(uow: SAUnitOfWork, key: str, namespace: int):
    task = uow.tasks.get_by_key(key, project_id=namespace)
    if task is None:
        raise NotFoundError("Standalone task not started")
    if task.id is None:
        raise ConflictError("Standalone task has no stored identity")
    workflow_id = task.workflow_id
    if uow.workflows.lock(workflow_id) is None:
        raise ConflictError("Standalone workflow disappeared")
    task = uow.tasks.lock(task.id)
    if task is None:
        raise ConflictError("Standalone task disappeared")
    if task.workflow_id != workflow_id:
        raise ConflictError("Standalone task workflow changed during admission")
    assignment = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
        m.TaskRuntimeAssignment.task_id == task.id,
        m.TaskRuntimeAssignment.operation_key == task.assignment_operation_key))
    if assignment is None or json.loads(assignment.payload).get("mode") != "standalone":
        raise ConflictError("Explicit standalone start required")
    if (assignment.project_id != task.project_id or assignment.workflow_id != task.workflow_id
            or assignment.mode_id != task.mode_id or assignment.cycle_number != task.cycle_number
            or assignment.assignment_revision != task.assignment_revision):
        raise ConflictError("Standalone task no longer matches its accepted start")
    return task


def cursor(uow: SAUnitOfWork, task: Any) -> dict[str, Any]:
    phase = uow.phases.get_by_id(task.current_phase_id)
    return {"interaction_protocol": "configured-cli-v1", "execution_mode": "standalone",
            "task": task.task_key, "namespace_id": task.project_id,
            "workflow_id": task.workflow_id, "mode_id": task.mode_id,
            "version": version(uow, task), "phase_code": phase.code if phase else None,
            "status": task.status, "complete": task.status == "done"}


def start(uow: SAUnitOfWork, command: StandaloneStep) -> dict[str, Any]:
    from project_workflow.interfaces.cli.core import _require_valid_key

    _require_valid_key(command.task)
    if command.workflow_id is None or command.mode_key is None:
        raise ValueError("Explicit workflow and mode required")
    uow.lock_catalog_state(shared=True)
    saved = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
        m.TaskRuntimeAssignment.operation_key == command.operation_key))
    request = command.model_dump(mode="json")
    if saved is not None:
        payload = json.loads(saved.payload)
        if payload.get("mode") != "standalone" or payload.get("request") != request:
            raise ConflictError("Start operation key payload conflict")
        return payload["result"]
    project = uow.projects.lock(command.namespace_id)
    workflow = uow.workflows.lock(command.workflow_id)
    if project is None or workflow is None or project.workflow_id != workflow.id:
        raise ConflictError("Explicit namespace/workflow selection does not match")
    if workflow.key and workflow.key.startswith(("single-task-v1:", "hermes-sdlc", "base-sdlc")):
        raise ConflictError("Platform catalog requires platform admission")
    mode = uow.workflows.get_mode_by_key(workflow.id, command.mode_key)
    if mode is None:
        raise NotFoundError("Selected workflow mode not found")
    phases = uow.phases.list(workflow.id, mode_id=mode.id)
    if not phases:
        raise ConflictError("Selected mode has no phases")
    if uow.tasks.get_by_key(command.task, project_id=project.id) is not None:
        raise ConflictError("Task already exists; start never resets an execution")
    task_id = uow.tasks.create({"project_id": project.id, "workflow_id": workflow.id,
        "task_key": command.task, "mode_id": mode.id, "cycle_number": 0,
        "current_phase_id": phases[0].id, "status": "active", "assignment_revision": 1,
        "assignment_operation_key": command.operation_key})
    task = uow.tasks.get_by_id(task_id)
    result = cursor(uow, task)
    uow.session.add(m.TaskRuntimeAssignment(operation_key=command.operation_key,
        task_id=task_id, project_id=project.id, workflow_id=workflow.id,
        mode_id=mode.id, cycle_number=0, assignment_revision=1,
        payload=json.dumps({"mode": "standalone", "request": request, "result": result})))
    uow.commit()
    return result


def check_fence(uow: SAUnitOfWork, fence: StandaloneFence) -> None:
    task = _task(uow, fence.request.task, fence.namespace_id)
    fence.assert_task(task.to_dict())
    if version(uow, task) != fence.version:
        raise ConflictError("Standalone operation version changed")


def prepare_history(fence: StandaloneFence, data: dict[str, Any]) -> None:
    data["replay_fingerprint"] = fence.operation_fingerprint
    data["evaluation_snapshot"]["standalone"] = {
        "operation_key": fence.request.operation_key, "request_sha256": fence.request_sha256,
        "result_version": fence.version + 1}


def finish_history(uow: SAUnitOfWork, fence: StandaloneFence, history_id: int, result: dict[str, Any]) -> None:
    task = uow.tasks.get_by_id(fence.task_id)
    if task is None:
        raise ConflictError("Standalone task disappeared before commit")
    result.update(cursor(uow, task))
    result["version"] = fence.version + 1
    uow.step_history.update_supervisor_response(history_id, result)


def step(uow: SAUnitOfWork, command: StandaloneStep) -> dict[str, Any]:
    from project_workflow.domain.phase_report import PhaseReport
    from project_workflow.supervisor import SupervisorEngine, format_result

    validate_database(uow)
    if command.start:
        result = start(uow, command)
        return {"ok": True, "exit_code": 0, "result": result}
    task = _task(uow, command.task, command.namespace_id)
    if command.report is not None and command.operation_key == task.assignment_operation_key:
        raise ConflictError("Report operation key must differ from the accepted start operation key")
    fence = StandaloneFence(task.id, task.project_id, task.workflow_id, task.mode_id,
        task.cycle_number, task.assignment_revision, task.assignment_operation_key,
        task.current_phase_id, task.status, version(uow, task), command)
    if command.report is not None:
        saved = uow.session.scalar(select(m.TaskStepHistoryEntry).where(
            m.TaskStepHistoryEntry.task_id == task.id,
            m.TaskStepHistoryEntry.replay_fingerprint == fence.operation_fingerprint))
        if saved is not None:
            metadata = json.loads(saved.evaluation_snapshot)["standalone"]
            if metadata["request_sha256"] != fence.request_sha256:
                raise ConflictError("Operation key payload conflict")
            return {"ok": True, "exit_code": 0, "result": json.loads(saved.supervisor_response)}
        if command.expected_version != fence.version or task.status == "done":
            raise ConflictError("Report requires the current active version")
        PhaseReport.parse(command.report)
    engine = SupervisorEngine(command.task, uow=uow, create_if_missing=False,
                              project_id=task.project_id, runtime_fence=fence)
    if command.report is None:
        result = {**cursor(uow, task), "instructions": engine.format_current_phase_instructions(),
                  "phase_contract": engine.get_phase_contract()}
    else:
        result = engine.evaluate(command.report)
        if "version" not in result:
            raise ConflictError("Standalone operation did not commit; read the original operation")
    return {"ok": True, "exit_code": 0, "result": result, "output": format_result(result)
            if "verdict" in result else result.get("instructions", "")}


def history(uow: SAUnitOfWork, task_key: str, namespace: int, *, n: int = 200,
            operation_key: str | None = None, before_history_id: int | None = None) -> dict[str, Any]:
    validate_database(uow)
    if operation_key is not None and before_history_id is not None:
        raise ConflictError("History cursor cannot select an operation")
    task = _task(uow, task_key, namespace)
    if operation_key == task.assignment_operation_key:
        assignment = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
            m.TaskRuntimeAssignment.task_id == task.id,
            m.TaskRuntimeAssignment.operation_key == operation_key))
        if assignment is None:
            raise ConflictError("Standalone start ledger disappeared")
        return {"ok": True, "exit_code": 0, "result": json.loads(assignment.payload)["result"]}
    query = select(m.TaskStepHistoryEntry).where(m.TaskStepHistoryEntry.task_id == task.id)
    if operation_key is not None:
        fingerprint = payload_sha256({"mode": "standalone", "start": task.assignment_operation_key,
                                      "operation_key": operation_key})
        query = query.where(m.TaskStepHistoryEntry.replay_fingerprint == fingerprint)
    if before_history_id is not None:
        query = query.where(m.TaskStepHistoryEntry.id < before_history_id)
    records = list(uow.session.scalars(query.order_by(m.TaskStepHistoryEntry.id.desc()).limit(n + 1)))
    if operation_key is not None and not records:
        raise NotFoundError("Standalone operation receipt not found")
    result = cursor(uow, task)
    result["records"] = [{"history_id": row.id, "worker_report": row.worker_report,
                           "result": json.loads(row.supervisor_response)} for row in records[:n]]
    result["next_before"] = records[n - 1].id if len(records) > n else None
    return {"ok": True, "exit_code": 0, "result": result}
