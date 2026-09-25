"""SQLAlchemy repository implementations."""

from __future__ import annotations

import datetime
import logging
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
            mode_id=row.mode_id,
            mode_key=row.mode.key if row.mode else "default",
            cycle_number=row.cycle_number,
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
            stmt = (
                select(m.Task)
                .options(
                    joinedload(m.Task.mode),
                    joinedload(m.Task.project).joinedload(m.Project.workflow).selectinload(m.Workflow.phases),
                )
                .order_by(m.Task.id.desc())
            )
            rows = self._session.execute(stmt).scalars().all()
        return [_row_to_task(r) for r in rows]

    def create(self, data: dict[str, Any]) -> int:
        if {"mode_id", "mode_key", "cycle_number"}.intersection(data):
            raise ValueError("Task mode/cycle are backend-pinned and cannot be caller-selected")
        project = self._session.get(m.Project, data["project_id"])
        if project is None:
            raise ValueError(f"Project {data['project_id']} not found")
        default_mode_id = self._session.execute(
            select(m.WorkflowMode.id).where(
                m.WorkflowMode.workflow_id == project.workflow_id,
                m.WorkflowMode.key == "default",
            )
        ).scalar_one_or_none()
        if default_mode_id is None:
            raise RuntimeError(f"Workflow {project.workflow_id} has no default mode")
        item = m.Task(
            project_id=data["project_id"],
            mode_id=int(default_mode_id),
            cycle_number=0,
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
            if key in {"id", "project_id", "mode_id", "cycle_number"}:
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
        if {"mode_id", "mode_key", "cycle_number"}.intersection(data):
            raise ValueError("Task mode/cycle require the backend-pinned cursor operation")
        values = dict(data)
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

    def pin_execution_cursor(
        self,
        task_id: int,
        *,
        mode_id: int,
        cycle_number: int,
        current_phase: str,
    ) -> None:
        if cycle_number < 0:
            raise ValueError("Execution cycle must be non-negative")
        task = self._session.get(m.Task, task_id)
        mode = self._session.get(m.WorkflowMode, mode_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        if mode is None or mode.workflow_id != task.project.workflow_id:
            raise ValueError("Backend-pinned mode must belong to the task workflow")
        phase = self._session.execute(
            select(m.Phase).where(
                m.Phase.workflow_id == mode.workflow_id,
                m.Phase.mode_id == mode_id,
                m.Phase.code == current_phase,
            )
        ).scalar_one_or_none()
        if phase is None:
            raise ValueError("Execution phase must belong to the backend-pinned mode")
        task.mode_id = mode_id
        task.cycle_number = cycle_number
        task.current_phase = current_phase
        task.updated_at = datetime.datetime.now(datetime.timezone.utc)

    def add_history(self, task_id: int, phase_id: int | str, status: str) -> None:
        task = self._session.get(m.Task, task_id)
        if task is None:
            raise NotFoundError("Task or phase not found")
        phase: m.Phase | None = None
        if isinstance(phase_id, str):
            phase = self._session.execute(
                select(m.Phase).where(
                    m.Phase.workflow_id == task.project.workflow_id,
                    m.Phase.mode_id == task.mode_id,
                    m.Phase.code == phase_id,
                )
            ).scalar_one_or_none()
            if phase is None and phase_id.isdigit():
                phase = self._session.get(m.Phase, int(phase_id))
        else:
            phase = self._session.get(m.Phase, phase_id)
        if phase is None:
            raise NotFoundError("Task or phase not found")
        resolved_phase_id = int(phase.id)
        if phase.mode_id != task.mode_id:
            raise ValueError("History phase must belong to the task's backend-pinned mode")
        completed_at = datetime.datetime.now(datetime.timezone.utc) if status == "done" else None
        # Check pending objects first to avoid duplicate inserts inside the same session.
        for obj in self._session.new:
            if (
                isinstance(obj, m.TaskHistory)
                and obj.task_id == task_id
                and obj.mode_id == task.mode_id
                and obj.cycle_number == task.cycle_number
                and obj.phase_id == resolved_phase_id
            ):
                obj.status = status
                obj.completed_at = completed_at
                return
        with self._session.no_autoflush:
            existing = self._session.execute(
                select(m.TaskHistory).where(
                    m.TaskHistory.task_id == task_id,
                    m.TaskHistory.mode_id == task.mode_id,
                    m.TaskHistory.cycle_number == task.cycle_number,
                    m.TaskHistory.phase_id == resolved_phase_id,
                )
            ).scalar_one_or_none()
        if existing:
            existing.status = status
            existing.completed_at = completed_at
        else:
            self._session.add(
                m.TaskHistory(
                    task_id=task_id,
                    phase_id=resolved_phase_id,
                    mode_id=task.mode_id,
                    cycle_number=task.cycle_number,
                    status=status,
                    completed_at=completed_at,
                )
            )

    def get_history(self, task_id: int) -> Sequence[dict[str, Any]]:
        with self._session.no_autoflush:
            rows = (
                self._session.execute(
                    select(m.TaskHistory).where(m.TaskHistory.task_id == task_id).order_by(m.TaskHistory.id)
                )
                .scalars()
                .all()
            )
        return [
            {
                "id": r.id,
                "task_id": r.task_id,
                "phase_id": r.phase_id,
                "mode_id": r.mode_id,
                "cycle_number": r.cycle_number,
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
                "mode_id": r.mode_id,
                "cycle_number": r.cycle_number,
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
