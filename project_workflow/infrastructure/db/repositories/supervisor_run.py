"""SQLAlchemy repository implementations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from project_workflow.domain import SupervisorRun
from project_workflow.domain.repositories import SupervisorRunRepository
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.converters import _row_to_supervisor_run


class SASupervisorRunRepository(SupervisorRunRepository):
    """SQLAlchemy implementation of SupervisorRunRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(
        self,
        task_id: int | None = None,
        task_key: str | None = None,
        limit: int = 200,
    ) -> Sequence[SupervisorRun]:
        stmt = select(m.SupervisorRun).order_by(m.SupervisorRun.id.desc()).limit(limit)
        if task_id is not None:
            stmt = stmt.where(m.SupervisorRun.task_id == task_id)
        if task_key is not None:
            stmt = stmt.join(m.Task, m.SupervisorRun.task_id == m.Task.id).where(m.Task.task_key == task_key)
        rows = self._session.execute(stmt).scalars().all()
        return [_row_to_supervisor_run(r) for r in rows]

    def latest_for_tasks(self, task_ids: Sequence[int]) -> Sequence[SupervisorRun]:
        if not task_ids:
            return []
        # PostgreSQL/CTE-compatible: select the latest run per task_id using ROW_NUMBER().
        cte = (
            select(
                m.SupervisorRun,
                (
                    func.row_number().over(partition_by=m.SupervisorRun.task_id, order_by=m.SupervisorRun.id.desc())
                ).label("rn"),
            )
            .where(m.SupervisorRun.task_id.in_(task_ids))
            .cte("latest_runs")
        )
        aliased_run = aliased(m.SupervisorRun, cte)
        stmt = select(aliased_run).where(cte.c.rn == 1)
        rows = self._session.execute(stmt).scalars().all()
        return [_row_to_supervisor_run(r) for r in rows]

    def create(self, data: dict[str, Any]) -> int:
        item = m.SupervisorRun(
            task_id=data["task_id"],
            phase_id=data["phase_id"],
            verdict=data["verdict"],
            report=data.get("report", ""),
            covered=json.dumps(data.get("covered", []), ensure_ascii=False),
            missing=json.dumps(data.get("missing", []), ensure_ascii=False),
            blockers=json.dumps(data.get("blockers", []), ensure_ascii=False),
            next_phase_id=data.get("next_phase_id"),
            rollback_phase_id=data.get("rollback_phase_id"),
            context_snapshot=json.dumps(data.get("context_snapshot", {}), ensure_ascii=False),
            response=json.dumps(data.get("response", {}), ensure_ascii=False),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)


