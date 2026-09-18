"""Fail-closed execution cursor for backend-owned Hermes assignments.

Business owns the Task and stage.  This service stores only the technical
phase cursor for one role namespace.  The caller cannot select a mode through
the model-facing command: the adapter resolves and forwards the active
assignment on every request.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from project_workflow.domain.repositories import UnitOfWork


class RuntimeAssignmentError(ValueError):
    """Assignment cannot be reconciled with this namespace configuration."""


@dataclass(frozen=True)
class RuntimeAssignment:
    task_id: str
    task_key: str
    title: str
    role: str
    namespace: str
    workflow_name: str
    mode_key: str
    cycle_number: int
    attempt: int
    run_id: str


class RuntimeWorkflowService:
    PROJECT_CODE = "HERMES"

    def __init__(self, uow: UnitOfWork, *, namespace_role: str, namespace_name: str):
        self._uow = uow
        self._namespace_role = namespace_role
        self._namespace_name = namespace_name

    def current(self, assignment: RuntimeAssignment) -> dict[str, Any]:
        task, phases = self._bind(assignment)
        if task.status == "done":
            return self._result(assignment, task, None, complete=True)
        phase = next((item for item in phases if item.code == task.current_phase), None)
        if phase is None:
            raise RuntimeAssignmentError("current phase is not part of the assigned mode")
        return self._result(assignment, task, phase, complete=False)

    def complete_current(
        self,
        assignment: RuntimeAssignment,
        *,
        expected_phase_code: str,
        operation_key: str,
    ) -> dict[str, Any]:
        expected_operation_key = self.operation_key_for(assignment, expected_phase_code)
        if operation_key != expected_operation_key:
            raise RuntimeAssignmentError("operation key does not match the active assignment")
        task, phases = self._bind(assignment)
        if task.status == "done":
            return self._result(assignment, task, None, complete=True)
        if task.current_phase != expected_phase_code:
            if task.id is None:
                raise RuntimeAssignmentError("runtime task has no id")
            completed_phase = next((item for item in phases if item.code == expected_phase_code), None)
            history = self._uow.tasks.get_history(task.id)
            if completed_phase is not None and completed_phase.id is not None and any(
                row["phase_id"] == completed_phase.id
                and row["mode_id"] == task.current_mode_id
                and row["cycle_number"] == assignment.cycle_number
                and row["status"] == "done"
                for row in history
            ):
                current = next((item for item in phases if item.code == task.current_phase), None)
                return self._result(assignment, task, current, complete=False)
            raise RuntimeAssignmentError("expected phase is stale or belongs to another assignment")
        index = next((index for index, item in enumerate(phases) if item.code == task.current_phase), None)
        if index is None:
            raise RuntimeAssignmentError("current phase is not part of the assigned mode")
        phase = phases[index]
        if task.id is None or phase.id is None:
            raise RuntimeAssignmentError("runtime cursor is incomplete")
        self._uow.tasks.add_history(
            task.id,
            phase.id,
            "done",
            mode_id=task.current_mode_id,
            cycle_number=assignment.cycle_number,
        )
        next_phase = phases[index + 1] if index + 1 < len(phases) else None
        if next_phase is None:
            self._uow.tasks.update(task.id, {"status": "done"})
        else:
            if next_phase.id is None:
                raise RuntimeAssignmentError("next phase is incomplete")
            self._uow.tasks.add_history(
                task.id,
                next_phase.id,
                "pending",
                mode_id=task.current_mode_id,
                cycle_number=assignment.cycle_number,
            )
            self._uow.tasks.update(task.id, {"current_phase": next_phase.code, "status": "active"})
        self._uow.commit()
        updated = self._uow.tasks.get_by_id(task.id)
        if updated is None:
            raise RuntimeAssignmentError("runtime cursor disappeared")
        return self._result(assignment, updated, next_phase, complete=next_phase is None)

    @staticmethod
    def operation_key_for(assignment: RuntimeAssignment, phase_code: str) -> str:
        identity = "\0".join(
            (
                assignment.task_id,
                assignment.run_id,
                assignment.mode_key,
                str(assignment.cycle_number),
                phase_code,
            )
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _bind(self, assignment: RuntimeAssignment):
        self._validate(assignment)
        workflow = self._uow.workflows.get_by_name(assignment.workflow_name)
        if workflow is None or workflow.id is None:
            raise RuntimeAssignmentError("assigned workflow is not installed")
        mode = self._uow.workflow_modes.get_by_key(workflow.id, assignment.mode_key)
        if mode is None or mode.id is None:
            raise RuntimeAssignmentError("assigned mode is not installed")
        phases = list(self._uow.phases.list(workflow.id, mode.id))
        if not phases:
            raise RuntimeAssignmentError("assigned mode has no phases")

        project = self._uow.projects.get_by_code(self.PROJECT_CODE)
        if project is None:
            project_id = self._uow.projects.create(
                {
                    "workflow_id": workflow.id,
                    "code": self.PROJECT_CODE,
                    "name": "Hermes runtime cursor",
                    "key_prefixes": [],
                }
            )
            project = self._uow.projects.get_by_id(project_id)
        if project is None or project.id is None or project.workflow_id != workflow.id:
            raise RuntimeAssignmentError("runtime project belongs to another workflow")

        task = self._uow.tasks.get_by_key(assignment.task_id)
        if task is None:
            task_id = self._uow.tasks.create(
                {
                    "project_id": project.id,
                    "task_key": assignment.task_id,
                    "title": assignment.title,
                    "current_phase": phases[0].code,
                    "current_mode_id": mode.id,
                    "cycle_number": assignment.cycle_number,
                    "status": "active",
                }
            )
            if phases[0].id is None:
                raise RuntimeAssignmentError("first phase is incomplete")
            self._uow.tasks.add_history(
                task_id,
                phases[0].id,
                "pending",
                mode_id=mode.id,
                cycle_number=assignment.cycle_number,
            )
            task = self._uow.tasks.get_by_id(task_id)
        elif task.project_id != project.id:
            raise RuntimeAssignmentError("task cursor belongs to another runtime project")
        elif task.current_mode_id != mode.id or task.cycle_number != assignment.cycle_number:
            if task.id is None:
                raise RuntimeAssignmentError("runtime task has no id")
            self._uow.tasks.update(
                task.id,
                {
                    "title": assignment.title,
                    "current_phase": phases[0].code,
                    "current_mode_id": mode.id,
                    "cycle_number": assignment.cycle_number,
                    "status": "active",
                },
            )
            if phases[0].id is None:
                raise RuntimeAssignmentError("first phase is incomplete")
            self._uow.tasks.add_history(
                task.id,
                phases[0].id,
                "pending",
                mode_id=mode.id,
                cycle_number=assignment.cycle_number,
            )
            task = self._uow.tasks.get_by_id(task.id)
        if task is None or task.id is None:
            raise RuntimeAssignmentError("runtime task binding failed")
        self._uow.commit()
        return task, phases

    def _validate(self, assignment: RuntimeAssignment) -> None:
        if assignment.role != self._namespace_role:
            raise RuntimeAssignmentError("assignment role does not match namespace")
        if assignment.namespace != self._namespace_name:
            raise RuntimeAssignmentError("assignment namespace does not match runtime")
        if (
            not assignment.task_id.strip()
            or not assignment.task_key.strip()
            or not assignment.workflow_name.strip()
            or not assignment.mode_key.strip()
        ):
            raise RuntimeAssignmentError("assignment identity is incomplete")
        if assignment.cycle_number < 0 or assignment.attempt < 1 or not assignment.run_id.strip():
            raise RuntimeAssignmentError("assignment execution identity is invalid")

    def _result(self, assignment: RuntimeAssignment, task: Any, phase: Any | None, *, complete: bool) -> dict[str, Any]:
        phase_detail: dict[str, Any] | None = None
        if phase is not None and phase.id is not None:
            phase_detail = {
                "code": phase.code,
                "name": phase.name,
                "description": phase.description or "",
                "instructions": list(self._uow.instructions.list(phase.id)),
                "checks": list(self._uow.phases.get_checks(phase.id)),
                "evidence": list(self._uow.phases.get_evidence(phase.id)),
            }
        return {
            "taskKey": assignment.task_key,
            "workflow": assignment.workflow_name,
            "mode": assignment.mode_key,
            "cycleNumber": assignment.cycle_number,
            "attempt": assignment.attempt,
            "runId": assignment.run_id,
            "status": task.status,
            "complete": complete,
            "phase": phase_detail,
        }


__all__ = ["RuntimeAssignment", "RuntimeAssignmentError", "RuntimeWorkflowService"]
