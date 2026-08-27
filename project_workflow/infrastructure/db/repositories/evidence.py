"""SQLAlchemy repository implementations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.repositories import PhaseEvidenceRequirementRepository
from project_workflow.infrastructure.db import models as m


class SAPhaseEvidenceRequirementRepository(PhaseEvidenceRequirementRepository):

    def __init__(self, session: Session):
        self._session = session

    def list(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.PhaseEvidenceRequirement)
            .where(m.PhaseEvidenceRequirement.phase_id == phase_id)
            .order_by(m.PhaseEvidenceRequirement.id)
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
            select(m.PhaseEvidenceRequirement)
            .where(m.PhaseEvidenceRequirement.phase_id.in_(phase_ids))
            .order_by(m.PhaseEvidenceRequirement.phase_id, m.PhaseEvidenceRequirement.id)
        ).scalars().all()
        for row in rows:
            result.setdefault(int(row.phase_id), []).append(
                {"id": row.id, "phase_id": row.phase_id, "description": row.description}
            )
        return result

    def create(self, phase_id: int, data: dict[str, Any]) -> int:
        item = m.PhaseEvidenceRequirement(phase_id=phase_id, description=data["description"])
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, evidence_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.PhaseEvidenceRequirement, evidence_id)
        if row is None:
            raise NotFoundError(f"Требование подтверждения {evidence_id} не найдено")
        row.description = data["description"]
        self._session.flush()

    def delete(self, evidence_id: int) -> None:
        row = self._session.get(m.PhaseEvidenceRequirement, evidence_id)
        if row is None:
            raise NotFoundError(f"Требование подтверждения {evidence_id} не найдено")
        self._session.delete(row)
        self._session.flush()

    def delete_for_phase(self, phase_id: int) -> None:
        self._session.execute(
            text("DELETE FROM phase_evidence_requirements WHERE phase_id = :pid"),
            {"pid": phase_id},
        )


