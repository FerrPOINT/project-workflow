"""SQLAlchemy repository implementations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.repositories import PhaseCheckRepository
from project_workflow.infrastructure.db import models as m


class SAPhaseCheckRepository(PhaseCheckRepository):

    def __init__(self, session: Session):
        self._session = session

    def list(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.PhaseCheck).where(m.PhaseCheck.phase_id == phase_id).order_by(m.PhaseCheck.id)
        ).scalars().all()
        return [
            {
                "id": r.id,
                "phase_id": r.phase_id,
                "description": r.description,
            }
            for r in rows
        ]

    def list_for_phases(self, phase_ids: Sequence[int]) -> Mapping[int, Sequence[dict[str, Any]]]:
        result: dict[int, list[dict[str, Any]]] = {phase_id: [] for phase_id in phase_ids}
        if not phase_ids:
            return result
        rows = self._session.execute(
            select(m.PhaseCheck)
            .where(m.PhaseCheck.phase_id.in_(phase_ids))
            .order_by(m.PhaseCheck.phase_id, m.PhaseCheck.id)
        ).scalars().all()
        for row in rows:
            result.setdefault(int(row.phase_id), []).append(
                {"id": row.id, "phase_id": row.phase_id, "description": row.description}
            )
        return result

    def create(self, phase_id: int, data: dict[str, Any]) -> int:
        item = m.PhaseCheck(phase_id=phase_id, description=data["description"])
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, check_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.PhaseCheck, check_id)
        if row is None:
            raise NotFoundError(f"Проверка {check_id} не найдена")
        row.description = data["description"]
        self._session.flush()

    def delete(self, check_id: int) -> None:
        row = self._session.get(m.PhaseCheck, check_id)
        if row is None:
            raise NotFoundError(f"Проверка {check_id} не найдена")
        self._session.delete(row)
        self._session.flush()


