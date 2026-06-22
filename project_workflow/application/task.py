"""Application services — use cases."""
from __future__ import annotations

from typing import Any

from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.validation import get_project_for_task_key


class TaskService:
    """Use cases for tasks."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._uow:
            payload = dict(data)
            if "project_id" not in payload or payload["project_id"] is None:
                project = get_project_for_task_key(self._uow, payload.get("task_key", ""))
                payload["project_id"] = project["id"] if project else None
            tid = self._uow.tasks.create(payload)
            task = self._uow.tasks.get_by_id(tid)
            if not task:
                raise RuntimeError("Task creation failed")
            return task.to_dict()

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self._uow:
            t = self._uow.tasks.get_by_id(task_id)
            return t.to_dict() if t else None

    def get_task_by_key(self, task_key: str) -> dict[str, Any] | None:
        with self._uow:
            t = self._uow.tasks.get_by_key(task_key)
            return t.to_dict() if t else None

    def update_task(self, task_id: int, data: dict[str, Any]) -> None:
        with self._uow:
            self._uow.tasks.update(task_id, data)
            return None

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._uow:
            return [t.to_dict() for t in self._uow.tasks.list()]

    def add_history(self, task_id: int, phase_id: int, status: str) -> None:
        with self._uow:
            self._uow.tasks.add_history(task_id, phase_id, status)
            return None

__all__ = ["TaskService"]
