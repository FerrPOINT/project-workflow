"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.validation import get_project_for_task_key
from project_workflow.workflow_contract import PinnedWorkflowContract


class TaskService:
    """Use cases for tasks."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        if "mode_id" in payload or "mode_key" in payload or "cycle_number" in payload:
            raise ValueError("Task mode/cycle are backend-pinned and cannot be caller-selected")
        if "project_id" not in payload or payload["project_id"] is None:
            project = get_project_for_task_key(self._uow, payload.get("task_key", ""))
            if project is None:
                raise ValueError(f"No project is configured for task key {payload.get('task_key', '')!r}")
            payload["project_id"] = project["id"]
        tid = self._uow.tasks.create(payload)
        task = self._uow.tasks.get_by_id(tid)
        if not task:
            raise RuntimeError("Task creation failed")
        self._uow.commit()
        return task.to_dict()

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        t = self._uow.tasks.get_by_id(task_id)
        return t.to_dict() if t else None

    def get_task_by_key(self, task_key: str) -> dict[str, Any] | None:
        t = self._uow.tasks.get_by_key(task_key)
        return t.to_dict() if t else None

    def update_task(self, task_id: int, data: dict[str, Any]) -> None:
        if {"mode_id", "mode_key", "cycle_number"}.intersection(data):
            raise ValueError("Task mode/cycle are backend-pinned and cannot be caller-selected")
        self._uow.tasks.update(task_id, data)
        self._uow.commit()
        return None

    def activate_pinned_execution(
        self,
        task_id: int,
        contract: PinnedWorkflowContract,
        *,
        cycle_number: int,
    ) -> dict[str, Any]:
        """Apply a validated backend assignment to the local execution cursor.

        This is deliberately not exposed by the UI API and persists no copy of
        the Business assignment, queue, lease, session or run binding.
        """

        task = self._uow.tasks.get_by_id(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        project = self._uow.projects.get_by_id(task.project_id)
        workflow = self._uow.workflows.get_by_id(project.workflow_id) if project else None
        if workflow is None or workflow.name != contract.workflow:
            raise ValueError("Pinned workflow does not match the task project")
        mode = self._uow.workflows.get_mode_by_key(workflow.id or 0, contract.mode)
        if mode is None or mode.id is None:
            raise ValueError("Pinned workflow mode is not configured")
        phases = self._uow.phases.list(workflow.id, mode.id)
        if not phases:
            raise ValueError("Pinned workflow mode has no phases")
        first_phase = min(phases, key=lambda item: item.phase_order)
        self._uow.tasks.pin_execution_cursor(
            task_id,
            mode_id=mode.id,
            cycle_number=cycle_number,
            current_phase=first_phase.code,
        )
        self._uow.commit()
        activated = self._uow.tasks.get_by_id(task_id)
        if activated is None:
            raise RuntimeError("Pinned execution cursor disappeared")
        return activated.to_dict()

    def list_tasks(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._uow.tasks.list()]

    def add_history(self, task_id: int, phase_id: int | str, status: str) -> None:
        self._uow.tasks.add_history(task_id, phase_id, status)
        self._uow.commit()
        return None

    def delete_task(self, task_id: int) -> None:
        self._uow.tasks.delete(task_id)
        self._uow.commit()
        return None


__all__ = ["TaskService"]
