"""SQLAlchemy persistence for evaluated CLI ``step`` records."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from project_workflow.domain import TaskStepHistoryEntry
from project_workflow.domain.repositories import TaskStepHistoryRepository
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.converters import _row_to_step_history


def _json_string_list(value: Any, field_name: str) -> str:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{field_name} должен быть массивом строк")
    return json.dumps(value, ensure_ascii=False)


def _json_object(value: Any, field_name: str) -> str:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} должен быть объектом")
    return json.dumps(value, ensure_ascii=False)


class SATaskStepHistoryRepository(TaskStepHistoryRepository):
    def __init__(self, session: Session):
        self._session = session

    def list(
        self,
        task_id: int | None = None,
        task_key: str | None = None,
        phase_id: int | None = None,
        limit: int | None = 200,
    ) -> Sequence[TaskStepHistoryEntry]:
        stmt = select(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id.desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        if task_id is not None:
            stmt = stmt.where(m.TaskStepHistoryEntry.task_id == task_id)
        if task_key is not None:
            stmt = stmt.join(m.Task, m.TaskStepHistoryEntry.task_id == m.Task.id).where(
                m.Task.task_key == task_key
            )
        if phase_id is not None:
            stmt = stmt.where(m.TaskStepHistoryEntry.phase_id == phase_id)
        rows = self._session.execute(stmt).scalars().all()
        return [_row_to_step_history(row) for row in rows]

    def latest_for_tasks(self, task_ids: Sequence[int]) -> Sequence[TaskStepHistoryEntry]:
        if not task_ids:
            return []
        cte = (
            select(
                m.TaskStepHistoryEntry,
                func.row_number()
                .over(
                    partition_by=m.TaskStepHistoryEntry.task_id,
                    order_by=m.TaskStepHistoryEntry.id.desc(),
                )
                .label("rn"),
            )
            .where(m.TaskStepHistoryEntry.task_id.in_(task_ids))
            .cte("latest_step_history")
        )
        history_entry = aliased(m.TaskStepHistoryEntry, cte)
        rows = self._session.execute(select(history_entry).where(cte.c.rn == 1)).scalars().all()
        return [_row_to_step_history(row) for row in rows]

    def get_by_fingerprint(
        self, task_id: int, phase_id: int, replay_fingerprint: str
    ) -> TaskStepHistoryEntry | None:
        row = self._session.execute(
            select(m.TaskStepHistoryEntry).where(
                m.TaskStepHistoryEntry.task_id == task_id,
                m.TaskStepHistoryEntry.phase_id == phase_id,
                m.TaskStepHistoryEntry.replay_fingerprint == replay_fingerprint,
            )
        ).scalar_one_or_none()
        return _row_to_step_history(row) if row is not None else None

    def create(self, data: dict[str, Any]) -> int:
        task_workflow_id = self._session.execute(
            select(m.Task.workflow_id).where(m.Task.id == data["task_id"])
        ).scalar_one_or_none()
        if task_workflow_id is None:
            raise ValueError("Задача для записи step не найдена")
        phase_ids = {
            phase_id
            for field in ("phase_id", "next_phase_id", "rollback_phase_id")
            if (phase_id := data.get(field)) is not None
        }
        workflow_ids = set(
            self._session.execute(
                select(m.Phase.workflow_id).where(m.Phase.id.in_(phase_ids))
            ).scalars()
        )
        if workflow_ids != {task_workflow_id}:
            raise ValueError("Запись step может ссылаться только на фазы воркфлоу задачи")
        item = m.TaskStepHistoryEntry(
            task_id=data["task_id"],
            phase_id=data["phase_id"],
            verdict=data["verdict"],
            worker_report=data["worker_report"],
            covered_item_ids=_json_string_list(data["covered_item_ids"], "covered_item_ids"),
            missing_item_ids=_json_string_list(data["missing_item_ids"], "missing_item_ids"),
            blocker_messages=_json_string_list(data["blocker_messages"], "blocker_messages"),
            next_phase_id=data.get("next_phase_id"),
            rollback_phase_id=data.get("rollback_phase_id"),
            replay_fingerprint=data.get("replay_fingerprint"),
            evaluation_snapshot=_json_object(data["evaluation_snapshot"], "evaluation_snapshot"),
            supervisor_response=_json_object(data["supervisor_response"], "supervisor_response"),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)
