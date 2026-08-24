"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.validation import get_project_for_task_key


class TaskService:
    """Use cases for tasks."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        if "project_id" not in payload or payload["project_id"] is None:
            resolved_project = get_project_for_task_key(self._uow, payload.get("task_key", ""))
            if resolved_project is None:
                raise ValueError(f"No project is configured for task key {payload.get('task_key', '')!r}")
            payload["project_id"] = resolved_project["id"]
        project_id = int(payload["project_id"])
        project = self._uow.projects.get_by_id(project_id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        if self._uow.workflows.lock(project.workflow_id) is None:
            raise NotFoundError(f"Workflow {project.workflow_id} not found")
        locked_project = self._uow.projects.lock(project_id)
        if locked_project is None:
            raise NotFoundError(f"Project {project_id} not found")
        if locked_project.workflow_id != project.workflow_id:
            raise ConflictError("Project workflow changed while the task was being created")
        raw_task_key = payload.get("task_key")
        if not isinstance(raw_task_key, str) or not raw_task_key.strip():
            raise ValueError("task_key must be a non-blank string")
        task_key = raw_task_key.strip()
        payload["task_key"] = task_key
        if not any(
            task_key == prefix or task_key.startswith(f"{prefix}-")
            for prefix in locked_project.key_prefixes
        ):
            raise ConflictError(
                f"Task key {task_key!r} does not match project {locked_project.code!r} prefixes"
            )
        raw_current_phase = payload.get("current_phase")
        if raw_current_phase in (None, ""):
            phases = list(self._uow.phases.list(workflow_id=locked_project.workflow_id))
            if not phases:
                raise ValueError(f"Workflow {locked_project.workflow_id} has no phases")
            current_phase = phases[0].code
        else:
            if not isinstance(raw_current_phase, str):
                raise ValueError("current_phase must be a phase code string")
            current_phase = raw_current_phase.strip()
            if not current_phase:
                raise ValueError("current_phase must be a non-blank phase code")
        payload["current_phase"] = current_phase
        if self._uow.phases.get_by_code(locked_project.workflow_id, current_phase) is None:
            raise ValueError(
                f"Phase {current_phase!r} not found in workflow {locked_project.workflow_id}"
            )
        if self._uow.tasks.get_by_key(task_key) is not None:
            raise ConflictError(f"Task {task_key!r} already exists")
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

    def list_tasks(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._uow.tasks.list()]

    def delete_task(self, task_id: int) -> None:
        self._uow.tasks.delete(task_id)
        self._uow.commit()
        return None


__all__ = ["TaskService"]
