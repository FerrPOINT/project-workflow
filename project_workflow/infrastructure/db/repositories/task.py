"""SQLAlchemy repository implementations."""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from project_workflow.domain import Task
from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.repositories import TaskRepository
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.converters import _iso, _row_to_task


class SATaskRepository(TaskRepository):
    """SQLAlchemy implementation of TaskRepository."""

    def __init__(self, session: Session):
        self._session = session

    def get_by_key(self, task_key: str) -> Task | None:
        with self._session.no_autoflush:
            row = self._session.execute(
                select(m.Task)
                .options(joinedload(m.Task.workflow).selectinload(m.Workflow.phases))
                .where(m.Task.task_key == task_key)
            ).scalar_one_or_none()
        if row is None:
            return None
        return _row_to_task(row)

    def get_by_id(self, task_id: int) -> Task | None:
        with self._session.no_autoflush:
            row = self._session.execute(
                select(m.Task)
                .options(joinedload(m.Task.workflow).selectinload(m.Workflow.phases))
                .where(m.Task.id == task_id)
            ).scalar_one_or_none()
        if row is None:
            return None
        return _row_to_task(row)

    def lock(self, task_id: int) -> Task | None:
        with self._session.no_autoflush:
            row = self._session.execute(
                select(m.Task).where(m.Task.id == task_id).with_for_update()
            ).scalar_one_or_none()
        return _row_to_task(row) if row else None

    def list(self) -> Sequence[Task]:
        with self._session.no_autoflush:
            stmt = (
                select(m.Task)
                .options(joinedload(m.Task.workflow).selectinload(m.Workflow.phases))
                .order_by(m.Task.id.desc())
            )
            rows = self._session.execute(stmt).scalars().all()
        return [_row_to_task(r) for r in rows]

    def list_by_project(self, project_id: int) -> Sequence[Task]:
        with self._session.no_autoflush:
            rows = self._session.execute(
                select(m.Task)
                .options(joinedload(m.Task.workflow).selectinload(m.Workflow.phases))
                .where(m.Task.project_id == project_id)
                .order_by(m.Task.id)
            ).scalars().all()
        return [_row_to_task(row) for row in rows]

    def create(self, data: dict[str, Any]) -> int:
        workflow_id = data.get("workflow_id")
        if not isinstance(workflow_id, int) or isinstance(workflow_id, bool) or workflow_id <= 0:
            raise ValueError("workflow_id задачи должен быть положительным целым числом")
        item = m.Task(
            project_id=data["project_id"],
            workflow_id=workflow_id,
            task_key=data["task_key"],
            title=data.get("title"),
            description=data.get("description"),
            current_phase=data["current_phase"],
            status=data.get("status", "active"),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, task_id: int, data: dict[str, Any]) -> None:
        with self._session.no_autoflush:
            row = self._session.get(m.Task, task_id)
        if row is None:
            raise NotFoundError(f"Задача {task_id} не найдена")
        for key, val in data.items():
            if key in {"id", "project_id", "workflow_id"}:
                continue
            if hasattr(row, key):
                setattr(row, key, val)
        if data:
            row.updated_at = datetime.datetime.now(datetime.timezone.utc)

    def update_if_state(
        self,
        task_id: int,
        expected_phase: str,
        expected_status: str,
        data: dict[str, Any],
    ) -> bool:
        values = {key: value for key, value in data.items() if key not in {"id", "project_id", "workflow_id"}}
        values["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        result = self._session.execute(
            update(m.Task)
            .where(
                m.Task.id == task_id,
                m.Task.current_phase == expected_phase,
                m.Task.status == expected_status,
            )
            .values(**values)
        )
        return getattr(result, "rowcount", 0) == 1

    def add_history(self, task_id: int, phase_id: int, status: str) -> None:
        completed_at = datetime.datetime.now(datetime.timezone.utc) if status == "done" else None
        # Check pending objects first to avoid duplicate inserts inside the same session.
        for obj in self._session.new:
            if isinstance(obj, m.TaskHistory) and obj.task_id == task_id and obj.phase_id == phase_id:
                obj.status = status
                obj.completed_at = completed_at
                return
        with self._session.no_autoflush:
            existing = self._session.execute(
                select(m.TaskHistory).where(
                    m.TaskHistory.task_id == task_id,
                    m.TaskHistory.phase_id == phase_id,
                )
            ).scalar_one_or_none()
        if existing:
            existing.status = status
            existing.completed_at = completed_at
        else:
            self._session.add(
                m.TaskHistory(
                    task_id=task_id,
                    phase_id=phase_id,
                    status=status,
                    completed_at=completed_at,
                )
            )

    def get_history(self, task_id: int) -> Sequence[dict[str, Any]]:
        with self._session.no_autoflush:
            rows = self._session.execute(
                select(m.TaskHistory)
                .where(m.TaskHistory.task_id == task_id)
                .order_by(m.TaskHistory.id)
            ).scalars().all()
        return [
            {
                "id": r.id,
                "task_id": r.task_id,
                "phase_id": r.phase_id,
                "status": r.status,
                "completed_at": _iso(r.completed_at),
            }
            for r in rows
        ]

    def get_history_batch(self, task_ids: Sequence[int]) -> Mapping[int, Sequence[dict[str, Any]]]:
        if not task_ids:
            return {}
        with self._session.no_autoflush:
            rows = (
                self._session.execute(
                    select(m.TaskHistory)
                    .where(m.TaskHistory.task_id.in_(task_ids))
                    .order_by(m.TaskHistory.task_id, m.TaskHistory.id)
                )
                .scalars()
                .all()
            )
        result: dict[int, list[dict[str, Any]]] = {tid: [] for tid in task_ids}
        for r in rows:
            entry = {
                "id": r.id,
                "task_id": r.task_id,
                "phase_id": r.phase_id,
                "status": r.status,
                "completed_at": _iso(r.completed_at),
            }
            result.setdefault(r.task_id, []).append(entry)
        return result

    def delete(self, task_id: int) -> None:
        with self._session.no_autoflush:
            row = self._session.get(m.Task, task_id)
        if row is None:
            raise ValueError(f"Задача {task_id} не найдена")
        self._session.execute(sa_delete(m.TaskHistory).where(m.TaskHistory.task_id == task_id))
        self._session.delete(row)
        self._session.flush()


