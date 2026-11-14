"""Background admission and immutable cursor around the existing Supervisor engine."""
import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from project_workflow import config
from project_workflow.application.catalog_publication import read_revision
from project_workflow.domain.background import BackgroundConclusion, BackgroundFence, BackgroundStep
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.background_admission import RunAdmission, RunIdentity
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def task_key(run_id: str) -> str:
    # This is the Workflow cursor's local key, never a Tracker task or binding.
    return "BG-" + run_id.replace("-", "").upper()


def _version(uow: SAUnitOfWork, task: Any) -> int:
    rows = uow.step_history.list(task_id=task.id, mode_id=task.mode_id, cycle_number=0, limit=1)
    if not rows:
        return 1
    metadata = rows[0].to_dict().get("evaluation_snapshot", {}).get("background")
    if not isinstance(metadata, dict) or type(metadata.get("result_version")) is not int:
        raise ConflictError("Background operation ledger required")
    return metadata["result_version"]


def _assignment(uow: SAUnitOfWork, task: Any, admission: RunIdentity) -> None:
    row = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
        m.TaskRuntimeAssignment.task_id == task.id,
        m.TaskRuntimeAssignment.operation_key == task.assignment_operation_key))
    if row is None or json.loads(row.payload) != {"mode": "background", "admission": admission.identity()}:
        raise ConflictError("Saved background admission changed")
    if (row.project_id != task.project_id or row.workflow_id != task.workflow_id
            or row.mode_id != task.mode_id or row.cycle_number != task.cycle_number
            or row.assignment_revision != task.assignment_revision):
        raise ConflictError("Background cursor no longer matches its saved admission")


def _catalog(uow: SAUnitOfWork, admission: RunIdentity):
    context = admission.context
    namespace = uow.projects.get_by_id(int(context.namespace_id))
    workflow = uow.workflows.lock(int(context.workflow_id))
    if (namespace is None or workflow is None or namespace.id is None or workflow.id is None
            or namespace.code != context.profession
            or not uow.workflows.belongs_to_profession(workflow.id, namespace.id)
            or workflow.key != f"fleet:background:{context.profession.lower()}"):
        raise ConflictError("Background profession/workflow ownership changed")
    publication = read_revision(uow, workflow, context.catalog_version)
    if publication["content_sha256"] != admission.workflow_revision:
        raise ConflictError("Background publication hash changed")
    modes = uow.workflows.list_modes(workflow.id, catalog_version=context.catalog_version)
    if (len(modes) != 1 or modes[0].key != "research" or modes[0].execution_scopes != ["background"]
            or modes[0].tech_workspace_policy != "forbidden"):
        raise ConflictError("Background-only research mode required")
    return workflow, modes[0]


def _task(uow: SAUnitOfWork, admission: RunIdentity, *, create: bool):
    uow.lock_catalog_state(shared=True)
    workflow, mode = _catalog(uow, admission)
    namespace = int(admission.context.namespace_id)
    key = task_key(admission.run_id)
    task = uow.tasks.get_by_key(key, project_id=namespace)
    if task is None:
        if not create:
            raise NotFoundError("Background execution not started")
        phases = uow.phases.list(workflow.id, mode_id=mode.id)
        if not phases:
            raise ConflictError("Background publication has no phases")
        operation = f"background:{admission.run_id}"
        task_id = uow.tasks.create({"project_id": namespace, "workflow_id": workflow.id,
            "task_key": key, "mode_id": mode.id, "cycle_number": 0,
            "current_phase_id": phases[0].id, "status": "active", "assignment_revision": 1,
            "assignment_operation_key": operation})
        uow.session.add(m.TaskRuntimeAssignment(operation_key=operation, task_id=task_id,
            project_id=namespace, workflow_id=workflow.id, mode_id=mode.id,
            cycle_number=0, assignment_revision=1,
            payload=json.dumps({"mode": "background", "admission": admission.identity()})))
        uow.session.flush()
        task = uow.tasks.get_by_id(task_id)
    if task is None or task.id is None:
        raise ConflictError("Background cursor disappeared")
    task = uow.tasks.lock(task.id)
    if task is None or task.workflow_id != workflow.id or task.mode_id != mode.id or task.cycle_number != 0:
        raise ConflictError("Background workflow cursor changed")
    _assignment(uow, task, admission)
    return task


def _cursor(uow: SAUnitOfWork, task: Any, admission: RunIdentity) -> dict:
    phase = uow.phases.get_by_id(task.current_phase_id)
    conclusion = None
    if task.status == "done":
        latest = uow.step_history.list(task_id=task.id, mode_id=task.mode_id, cycle_number=0, limit=1)
        if not latest:
            raise ConflictError("Completed research conclusion missing")
        metadata = latest[0].to_dict().get("evaluation_snapshot", {}).get("background", {})
        conclusion = BackgroundConclusion.model_validate(metadata.get("research_result")).model_dump(mode="json")
    return {"interaction_protocol": "configured-cli-v1", "execution_mode": "background",
            "run_id": admission.run_id, "project_id": admission.project_id, "session_id": admission.session_id,
            "task": task.task_key, "namespace_id": task.project_id, "workflow_id": task.workflow_id,
            "mode_id": task.mode_id, "version": _version(uow, task),
            "phase_code": phase.code if phase else None, "status": task.status,
            "complete": task.status == "done", "concrete_agent_ref": admission.agent_id,
            "workflow_revision": admission.workflow_revision, "research_result": conclusion}


def check_fence(uow: SAUnitOfWork, fence: BackgroundFence) -> None:
    fence.authority_check()
    task = uow.tasks.get_by_id(fence.task_id)
    fence.assert_task(task.to_dict() if task else None)
    if task is None or _version(uow, task) != fence.version:
        raise ConflictError("Background operation version changed")


def prepare_history(fence: BackgroundFence, data: dict) -> None:
    data["replay_fingerprint"] = fence.operation_fingerprint
    data["evaluation_snapshot"]["background"] = {"run_id": fence.request.run_id,
        "operation_key": fence.request.operation_key, "request_sha256": fence.request_sha256,
        "result_version": fence.version + 1,
        "research_result": (fence.request.research_result.model_dump(mode="json")
                            if fence.request.research_result is not None else None)}


def finish_history(uow: SAUnitOfWork, fence: BackgroundFence, history_id: int, result: dict) -> None:
    task = uow.tasks.get_by_id(fence.task_id)
    if task is None:
        raise ConflictError("Background cursor disappeared before commit")
    row = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
        m.TaskRuntimeAssignment.task_id == task.id,
        m.TaskRuntimeAssignment.operation_key == task.assignment_operation_key))
    if row is None:
        raise ConflictError("Background admission disappeared before commit")
    admission = RunIdentity.model_validate(json.loads(row.payload)["admission"])
    result.update(_cursor(uow, task, admission))
    result["version"] = fence.version + 1
    uow.step_history.update_supervisor_response(history_id, result)


def step(uow: SAUnitOfWork, command: BackgroundStep, admission: RunAdmission,
         authority_check: Callable[[], None]) -> dict:
    from project_workflow.domain.phase_report import PhaseReport
    from project_workflow.supervisor import SupervisorEngine, format_result

    if config.get_settings().PROJECT_WORKFLOW_MODE != "platform":
        raise ConflictError("Background execution requires platform mode")
    if admission.run_id != command.run_id or int(admission.context.namespace_id) != command.namespace_id:
        raise ConflictError("Background invocation identity changed")
    task = _task(uow, admission, create=command.report is None)
    fence = BackgroundFence(task.id, task.project_id, task.workflow_id, task.mode_id,
        task.cycle_number, task.assignment_revision, task.assignment_operation_key,
        task.current_phase_id, task.status, _version(uow, task), command, authority_check)
    if command.report is not None:
        saved = uow.session.scalar(select(m.TaskStepHistoryEntry).where(
            m.TaskStepHistoryEntry.task_id == task.id,
            m.TaskStepHistoryEntry.replay_fingerprint == fence.operation_fingerprint))
        if saved is not None:
            metadata = json.loads(saved.evaluation_snapshot)["background"]
            if metadata["request_sha256"] != fence.request_sha256:
                raise ConflictError("Background operation key payload conflict")
            return {"ok": True, "exit_code": 0, "result": json.loads(saved.supervisor_response)}
        if command.expected_version != fence.version or task.status == "done":
            raise ConflictError("Background report requires the current active version")
        phases = uow.phases.list(task.workflow_id, mode_id=task.mode_id)
        final = bool(phases and task.current_phase_id == phases[-1].id)
        if final != (command.research_result is not None):
            raise ValueError("Only the final phase requires an explicit research_result")
        PhaseReport.parse(command.report)
    engine = SupervisorEngine(task.task_key, uow=uow, create_if_missing=False,
                              project_id=task.project_id, runtime_fence=fence)
    if command.report is None:
        result = {**_cursor(uow, task, admission), "instructions": engine.format_current_phase_instructions(),
                  "phase_contract": engine.get_phase_contract()}
        authority_check()
        uow.commit()
    else:
        result = engine.evaluate(command.report)
        if "version" not in result:
            raise ConflictError("Background operation did not commit; read its original key")
    return {"ok": True, "exit_code": 0, "result": result,
            "output": format_result(result) if "verdict" in result else result.get("instructions", "")}


def history(uow: SAUnitOfWork, admission: RunIdentity, *, n: int = 200,
            operation_key: str | None = None, before_history_id: int | None = None) -> dict:
    if config.get_settings().PROJECT_WORKFLOW_MODE != "platform":
        raise ConflictError("Background execution requires platform mode")
    if not 1 <= n <= 200 or operation_key is not None and before_history_id is not None:
        raise ValueError("Invalid background history selector")
    task = _task(uow, admission, create=False)
    result = _cursor(uow, task, admission)
    if operation_key is not None:
        fingerprint = payload_sha256(
            {"mode": "background", "run_id": admission.run_id, "operation_key": operation_key})
        saved = uow.session.scalar(select(m.TaskStepHistoryEntry).where(
            m.TaskStepHistoryEntry.task_id == task.id, m.TaskStepHistoryEntry.replay_fingerprint == fingerprint))
        if saved is None:
            raise NotFoundError("Background operation not found")
        return {"ok": True, "exit_code": 0, "result": json.loads(saved.supervisor_response)}
    query = select(m.TaskStepHistoryEntry).where(m.TaskStepHistoryEntry.task_id == task.id)
    if before_history_id is not None:
        query = query.where(m.TaskStepHistoryEntry.id < before_history_id)
    rows = list(uow.session.scalars(query.order_by(m.TaskStepHistoryEntry.id.desc()).limit(n + 1)))
    selected = rows[:n]
    names = {phase.id: phase.name for phase in uow.phases.list(task.workflow_id, mode_id=task.mode_id)}
    result.update(records=[{"history_id": row.id, "phase_name": names[row.phase_id], "verdict": row.verdict,
                            "worker_report": row.worker_report,
                            "result": json.loads(row.supervisor_response)} for row in selected],
                  next_before=selected[-1].id if len(rows) > n and selected else None)
    return {"ok": True, "exit_code": 0, "result": result}


def archived_history(uow: SAUnitOfWork, run_id: str, *, n: int, before_history_id: int | None) -> dict:
    """Registered Fleet reads saved history; it does not renew a research grant."""
    row = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
        m.TaskRuntimeAssignment.operation_key == f"background:{run_id}"))
    if row is None:
        raise NotFoundError("Background execution not started")
    payload = json.loads(row.payload)
    if set(payload) != {"mode", "admission"} or payload["mode"] != "background":
        raise ConflictError("Background assignment required")
    admission = RunIdentity.model_validate(payload["admission"])
    if admission.run_id != run_id:
        raise ConflictError("Background history identity changed")
    result = history(uow, admission, n=n, before_history_id=before_history_id)
    result["result"]["project_id"] = admission.project_id
    return result
