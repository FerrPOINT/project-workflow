"""SQLAlchemy repository implementations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from project_workflow.domain.repositories import CheckRepository
from project_workflow.infrastructure.db import models as m


class SACheckRepository(CheckRepository):
    """SQLAlchemy implementation of CheckRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.Check).where(m.Check.phase_id == phase_id).order_by(m.Check.id)
        ).scalars().all()
        return [
            {
                "id": r.id,
                "phase_id": r.phase_id,
                "description": r.description,
            }
            for r in rows
        ]

    def create(self, phase_id: int, data: dict[str, Any]) -> int:
        item = m.Check(phase_id=phase_id, description=data["description"])
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def delete_for_phase(self, phase_id: int) -> None:
        self._session.execute(
            text("DELETE FROM checks WHERE phase_id = :pid"),
            {"pid": phase_id},
        )


