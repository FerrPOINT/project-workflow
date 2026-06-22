"""Application services — use cases."""
from __future__ import annotations

from typing import Any, List, cast

from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork


class TaskService:
    """Use cases for tasks."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._uow:
            tid = self._uow.tasks.create(data)
            task = self._uow.tasks.get_by_id(tid)
            if not task:
                raise RuntimeError("Task creation failed")
            return task.to_dict()

    def get_task_by_key(self, task_key: str) -> dict[str, Any] | None:
        with self._uow:
            t = self._uow.tasks.get_by_key(task_key)
            return t.to_dict() if t else None

    def update_task(self, task_id: int, data: dict[str, Any]) -> None:
        with self._uow:
            self._uow.tasks.update(task_id, data)

    def add_history(self, task_id: int, phase_id: int, status: str) -> None:
        with self._uow:
            self._uow.tasks.add_history(task_id, phase_id, status)

