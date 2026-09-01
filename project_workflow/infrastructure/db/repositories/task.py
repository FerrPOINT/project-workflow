"""SQLAlchemy repository implementations."""

from __future__ import annotations

import datetime
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from project_workflow.domain import Task, TaskPhaseEvent
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import TaskRepository
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.converters import _row_to_phase_event, _row_to_task


class SATaskRepository(TaskRepository):
    """SQLAlchemy implementation of TaskRepository."""

    def __init__(self, session: Session):
        self._session = session

    def get_by_key(
        self,
        task_key: str,
        workflow_id: int | None = None,
        project_id: int | None = None,
    ) -> Task | None:
        with self._session.no_autoflush:
            stmt = (
                select(m.Task)
                .options(joinedload(m.Task.workflow).selectinload(m.Workflow.phases))
                .where(m.Task.task_key == task_key)
            )
            if project_id is not None:
                stmt = stmt.where(m.Task.project_id == project_id)
            if workflow_id is not None:
                stmt = stmt.where(m.Task.workflow_id == workflow_id)
            rows = self._session.execute(stmt.order_by(m.Task.project_id, m.Task.id)).scalars().all()
        if not rows:
            return None
        if project_id is None and len(rows) > 1:
            raise ConflictError(f"Задача {task_key!r} доступна через несколько неймспейсов; укажите wrapper-команду")
        return _row_to_task(rows[0])

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
            current_phase_id=data["current_phase_id"],
            status=data.get("status", "active"),
        )
        self._session.add(item)
        self._session.flush()
        self.record_phase_event(int(item.id), item.current_phase_id, "entered")
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
        expected_phase_id: int,
        expected_status: str,
        data: dict[str, Any],
    ) -> bool:
        values = {key: value for key, value in data.items() if key not in {"id", "project_id", "workflow_id"}}
        values["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        result = self._session.execute(
            update(m.Task)
            .where(
                m.Task.id == task_id,
                m.Task.current_phase_id == expected_phase_id,
                m.Task.status == expected_status,
            )
            .values(**values)
        )
        return getattr(result, "rowcount", 0) == 1

    def record_phase_event(
        self,
        task_id: int,
        phase_id: int,
        event_type: str,
        step_history_id: int | None = None,
    ) -> None:
        task_workflow_id = self._session.execute(
            select(m.Task.workflow_id).where(m.Task.id == task_id)
        ).scalar_one_or_none()
        phase_workflow_id = self._session.execute(
            select(m.Phase.workflow_id).where(m.Phase.id == phase_id)
        ).scalar_one_or_none()
        if task_workflow_id is None:
            raise NotFoundError(f"Задача {task_id} не найдена")
        if phase_workflow_id != task_workflow_id:
            raise ValueError("Событие фазы должно принадлежать воркфлоу задачи")
        if step_history_id is not None:
            owner_task_id = self._session.execute(
                select(m.TaskStepHistoryEntry.task_id).where(
                    m.TaskStepHistoryEntry.id == step_history_id
                )
            ).scalar_one_or_none()
            if owner_task_id != task_id:
                raise ValueError("Событие фазы и запись step должны принадлежать одной задаче")
        self._session.add(
            m.TaskPhaseEvent(
                task_id=task_id,
                workflow_id=task_workflow_id,
                phase_id=phase_id,
                step_history_id=step_history_id,
                event_type=event_type,
            )
        )

    def list_phase_events(self, task_id: int) -> Sequence[TaskPhaseEvent]:
        with self._session.no_autoflush:
            rows = self._session.execute(
                select(m.TaskPhaseEvent)
                .where(m.TaskPhaseEvent.task_id == task_id)
                .order_by(m.TaskPhaseEvent.id)
            ).scalars().all()
        return [_row_to_phase_event(row) for row in rows]

    def list_phase_events_batch(self, task_ids: Sequence[int]) -> Mapping[int, Sequence[TaskPhaseEvent]]:
        if not task_ids:
            return {}
        with self._session.no_autoflush:
            rows = (
                self._session.execute(
                    select(m.TaskPhaseEvent)
                    .where(m.TaskPhaseEvent.task_id.in_(task_ids))
                    .order_by(m.TaskPhaseEvent.task_id, m.TaskPhaseEvent.id)
                )
                .scalars()
                .all()
            )
        result: dict[int, list[TaskPhaseEvent]] = {tid: [] for tid in task_ids}
        for r in rows:
            result.setdefault(r.task_id, []).append(_row_to_phase_event(r))
        return result

