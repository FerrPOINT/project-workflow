"""SQLAlchemy repository implementations."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from project_workflow.domain import Task
from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.repositories import TaskRepository
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.converters import _iso, _row_to_task

logger = logging.getLogger(__name__)
class SATaskRepository(TaskRepository):
    """SQLAlchemy implementation of TaskRepository."""

    def __init__(self, session: Session):
        self._session = session

    def get_by_key(self, task_key: str) -> Task | None:
        with self._session.no_autoflush:
            row = self._session.execute(select(m.Task).where(m.Task.task_key == task_key)).scalar_one_or_none()
        if row is None:
            return None
        try:
            project_id = row.project_id
            project_id = int(project_id)
        except (ValueError, TypeError) as exc:
            logger.warning("Failed to cast task project_id: %s", exc)
            project_id = 0
        return Task(
            id=row.id,
            project_id=project_id,
            task_key=row.task_key,
            title=row.title or "",
            description=row.description or "",
            current_phase=row.current_phase or "-1",
            current_phase_name="",
            status=row.status or "active",
            created_at=_iso(row.created_at),
            updated_at=_iso(row.updated_at),
        )

    def get_by_id(self, task_id: int) -> Task | None:
        with self._session.no_autoflush:
            row = self._session.get(m.Task, task_id)
        if row is None:
            return None
        return _row_to_task(row)

    def list(self) -> Sequence[Task]:
        with self._session.no_autoflush:
            rows = self._session.execute(select(m.Task).order_by(m.Task.id.desc())).scalars().all()
        return [_row_to_task(r) for r in rows]

    def create(self, data: dict[str, Any]) -> int:
        item = m.Task(
            project_id=data["project_id"],
            task_key=data["task_key"],
            title=data.get("title"),
            description=data.get("description"),
            current_phase=data.get("current_phase", "-1"),
            status=data.get("status", "active"),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, task_id: int, data: dict[str, Any]) -> None:
        with self._session.no_autoflush:
            row = self._session.get(m.Task, task_id)
        if row is None:
            raise NotFoundError(f"Task {task_id} not found")
        for key, val in data.items():
            if hasattr(row, key):
                setattr(row, key, val)

    def update_if_state(
        self,
        task_id: int,
        expected_phase: str,
        expected_status: str,
        data: dict[str, Any],
    ) -> bool:
        result = self._session.execute(
            update(m.Task)
            .where(
                m.Task.id == task_id,
                m.Task.current_phase == expected_phase,
                m.Task.status == expected_status,
            )
            .values(**data)
        )
        return getattr(result, "rowcount", 0) == 1

    def add_history(self, task_id: int, phase_id: int, status: str) -> None:
        # Check pending objects first to avoid duplicate inserts inside the same session.
        for obj in self._session.new:
            if isinstance(obj, m.TaskHistory) and obj.task_id == task_id and obj.phase_id == phase_id:
                obj.status = status
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
        else:
            self._session.add(m.TaskHistory(task_id=task_id, phase_id=phase_id, status=status))

    def get_history(self, task_id: int) -> Sequence[dict[str, Any]]:
        with self._session.no_autoflush:
            rows = self._session.execute(select(m.TaskHistory).where(m.TaskHistory.task_id == task_id)).scalars().all()
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
                self._session.execute(select(m.TaskHistory).where(m.TaskHistory.task_id.in_(task_ids))).scalars().all()
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
            raise ValueError(f"Task {task_id} not found")
        self._session.execute(sa_delete(m.TaskHistory).where(m.TaskHistory.task_id == task_id))
        self._session.delete(row)
        self._session.flush()


