"""SQLAlchemy repository implementations."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session, joinedload

from project_workflow.domain import Phase
from project_workflow.domain.exceptions import LastPhaseError, NotFoundError
from project_workflow.domain.repositories import PhaseRepository
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.converters import _row_to_phase


class SAPhaseRepository(PhaseRepository):
    """SQLAlchemy implementation of PhaseRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self, workflow_id: int | None = None) -> Sequence[Phase]:
        stmt = select(m.Phase).options(joinedload(m.Phase.workflow)).order_by(m.Phase.workflow_id, m.Phase.phase_order)
        if workflow_id is not None:
            stmt = stmt.where(m.Phase.workflow_id == workflow_id)
        rows = self._session.execute(stmt.execution_options(populate_existing=True)).scalars().all()
        return [_row_to_phase(r) for r in rows]

    def get_by_id(self, phase_id: int) -> Phase | None:
        row = self._session.get(m.Phase, phase_id)
        return _row_to_phase(row) if row else None

    def get_by_code(self, workflow_id: int, code: str) -> Phase | None:
        row = self._session.execute(
            select(m.Phase).where(m.Phase.workflow_id == workflow_id, m.Phase.code == code)
        ).scalar_one_or_none()
        return _row_to_phase(row) if row else None

    def create(self, data: dict[str, Any]) -> int:
        item = m.Phase(
            workflow_id=data["workflow_id"],
            code=data["code"],
            name=data["name"],
            description=data.get("description"),
            phase_order=data["phase_order"],
            agent_id=data.get("agent_id"),
            parallel_with_phase_id=data.get("parallel_with_phase_id"),
            rollback_target_phase_id=data.get("rollback_target_phase_id"),
            execution_type=data.get("execution_type", "sync"),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, phase_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.Phase, phase_id)
        if row is None:
            raise NotFoundError(f"Фаза {phase_id} не найдена")
        for key, val in data.items():
            if key in {"id", "workflow_id"}:
                continue
            if hasattr(row, key):
                setattr(row, key, val)

    def delete(self, phase_id: int) -> None:
        row = self._session.get(m.Phase, phase_id)
        if row is None:
            raise NotFoundError(f"Фаза {phase_id} не найдена")
        remaining = (
            self._session.execute(
                select(m.Phase).where(
                    m.Phase.workflow_id == row.workflow_id,
                    m.Phase.id != phase_id,
                )
            )
            .scalars()
            .all()
        )
        if not remaining:
            raise LastPhaseError("Нельзя удалить единственную фазу воркфлоу")
        # Cascade delete content rows explicitly (mirror ON DELETE CASCADE).
        for child_class in (m.PhaseInstruction, m.PhaseCheck, m.PhaseEvidenceRequirement):
            self._session.execute(
                text(f"DELETE FROM {child_class.__tablename__} WHERE phase_id = :pid"),
                {"pid": phase_id},
            )
        self._session.delete(row)

    def shift_orders(self, workflow_id: int, start_order: int, delta: int = 1) -> None:
        offset = self.get_next_order(workflow_id) + 1000
        self._session.execute(
            text(
                "UPDATE phases SET phase_order = phase_order + :offset "
                "WHERE workflow_id = :wid AND phase_order >= :start"
            ),
            {"offset": offset, "wid": workflow_id, "start": start_order},
        )
        self._session.execute(
            text(
                "UPDATE phases SET phase_order = phase_order - :offset + :delta "
                "WHERE workflow_id = :wid AND phase_order >= :shifted_start"
            ),
            {
                "offset": offset,
                "delta": delta,
                "wid": workflow_id,
                "shifted_start": start_order + offset,
            },
        )

    def get_next_order(self, workflow_id: int) -> int:
        max_order = self._session.execute(
            select(m.Phase.phase_order).where(m.Phase.workflow_id == workflow_id).order_by(m.Phase.phase_order.desc())
        ).scalar()
        return (max_order or 0) + 1

    def reference_kinds(self, phase_id: int) -> set[str]:
        row = self._session.get(m.Phase, phase_id)
        if row is None:
            raise NotFoundError(f"Фаза {phase_id} не найдена")

        kinds: set[str] = set()
        current_task = self._session.execute(
            select(m.Task.id)
            .join(m.Project, m.Task.project_id == m.Project.id)
            .where(
                m.Project.workflow_id == row.workflow_id,
                m.Task.current_phase_id == phase_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if current_task is not None:
            kinds.add("текущая задача")

        history = self._session.execute(
            select(m.TaskPhaseEvent.id).where(m.TaskPhaseEvent.phase_id == phase_id).limit(1)
        ).scalar_one_or_none()
        if history is not None:
            kinds.add("история задачи")

        run = self._session.execute(
            select(m.TaskStepHistoryEntry.id)
            .where(
                or_(
                    m.TaskStepHistoryEntry.phase_id == phase_id,
                    m.TaskStepHistoryEntry.next_phase_id == phase_id,
                    m.TaskStepHistoryEntry.rollback_phase_id == phase_id,
                )
            )
            .limit(1)
        ).scalar_one_or_none()
        if run is not None:
            kinds.add("проверка Supervisor")

        catalog_link = self._session.execute(
            select(m.Phase.id)
            .where(
                m.Phase.workflow_id == row.workflow_id,
                m.Phase.id != phase_id,
                or_(
                    m.Phase.parallel_with_phase_id == phase_id,
                    m.Phase.rollback_target_phase_id == phase_id,
                ),
            )
            .limit(1)
        ).scalar_one_or_none()
        if catalog_link is not None:
            kinds.add("ссылка фазы")
        return kinds

    def has_agent_reference(self, agent_id: int) -> bool:
        phase_id = self._session.execute(
            select(m.Phase.id).where(m.Phase.agent_id == agent_id).limit(1)
        ).scalar_one_or_none()
        return phase_id is not None

    def workflow_ids_for_agent(self, agent_id: int) -> Sequence[int]:
        rows = self._session.execute(
            select(m.Phase.workflow_id)
            .where(m.Phase.agent_id == agent_id)
            .distinct()
            .order_by(m.Phase.workflow_id)
        ).scalars()
        return [int(workflow_id) for workflow_id in rows]

    def resequence(self, workflow_id: int) -> None:
        rows = list(
            self._session.execute(
                select(m.Phase.id)
                .where(m.Phase.workflow_id == workflow_id)
                .order_by(m.Phase.phase_order, m.Phase.id)
            ).scalars()
        )
        if not rows:
            return
        offset = len(rows) + 1000
        self._session.execute(
            text("UPDATE phases SET phase_order = phase_order + :offset WHERE workflow_id = :wid"),
            {"offset": offset, "wid": workflow_id},
        )
        for order, phase_id in enumerate(rows, 1):
            self._session.execute(
                text("UPDATE phases SET phase_order = :order WHERE id = :phase_id"),
                {"order": order, "phase_id": phase_id},
            )
        self._session.flush()
        self._session.expire_all()

    def reorder(self, workflow_id: int, orders: Sequence[tuple[int, int]]) -> None:
        if not orders:
            return
        offset = self.get_next_order(workflow_id) + len(orders) + 1000
        self._session.execute(
            text(
                "UPDATE phases SET phase_order = phase_order + :offset "
                "WHERE workflow_id = :wid"
            ),
            {"offset": offset, "wid": workflow_id},
        )
        for phase_id, phase_order in orders:
            self._session.execute(
                text(
                    "UPDATE phases SET phase_order = :phase_order "
                    "WHERE id = :phase_id AND workflow_id = :workflow_id"
                ),
                {
                    "phase_order": phase_order,
                    "phase_id": phase_id,
                    "workflow_id": workflow_id,
                },
            )
        self._session.flush()
        self._session.expire_all()

    def get_checks(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.PhaseCheck).where(m.PhaseCheck.phase_id == phase_id).order_by(m.PhaseCheck.id)
        ).scalars().all()
        return [{"id": r.id, "phase_id": r.phase_id, "description": r.description} for r in rows]

    def get_evidence(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.PhaseEvidenceRequirement)
            .where(m.PhaseEvidenceRequirement.phase_id == phase_id)
            .order_by(m.PhaseEvidenceRequirement.id)
        ).scalars().all()
        return [{"id": r.id, "phase_id": r.phase_id, "description": r.description} for r in rows]

    def set_checks(self, phase_id: int, items: builtins.list[dict[str, Any]]) -> None:
        self._session.execute(sa_delete(m.PhaseCheck).where(m.PhaseCheck.phase_id == phase_id))
        for item in items:
            self._session.add(m.PhaseCheck(phase_id=phase_id, description=item.get("description", "")))

    def set_evidence(self, phase_id: int, items: builtins.list[dict[str, Any]]) -> None:
        self._session.execute(
            sa_delete(m.PhaseEvidenceRequirement).where(m.PhaseEvidenceRequirement.phase_id == phase_id)
        )
        for item in items:
            self._session.add(
                m.PhaseEvidenceRequirement(phase_id=phase_id, description=item.get("description", ""))
            )


