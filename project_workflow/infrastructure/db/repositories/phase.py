"""SQLAlchemy repository implementations."""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, text
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

    def _find_default_mode_id(self, workflow_id: int) -> int | None:
        mode_id = self._session.execute(
            select(m.WorkflowMode.id).where(
                m.WorkflowMode.workflow_id == workflow_id,
                m.WorkflowMode.key == "default",
            )
        ).scalar_one_or_none()
        return int(mode_id) if mode_id is not None else None

    def _default_mode_id(self, workflow_id: int) -> int:
        mode_id = self._find_default_mode_id(workflow_id)
        if mode_id is None:
            raise RuntimeError(f"Workflow {workflow_id} has no default mode")
        return mode_id

    def list(self, workflow_id: int | None = None, mode_id: int | None = None) -> Sequence[Phase]:
        stmt = (
            select(m.Phase)
            .options(joinedload(m.Phase.workflow), joinedload(m.Phase.mode))
            .order_by(m.Phase.workflow_id, m.Phase.phase_order)
        )
        if workflow_id is not None:
            stmt = stmt.where(m.Phase.workflow_id == workflow_id)
            mode_id = mode_id if mode_id is not None else self._find_default_mode_id(workflow_id)
            if mode_id is None:
                return []
        if mode_id is not None:
            stmt = stmt.where(m.Phase.mode_id == mode_id)
        rows = self._session.execute(stmt).scalars().all()
        return [_row_to_phase(r) for r in rows]

    def get_by_id(self, phase_id: int) -> Phase | None:
        row = self._session.get(m.Phase, phase_id)
        return _row_to_phase(row) if row else None

    def get_by_code(
        self,
        code: str,
        workflow_id: int | None = None,
        mode_id: int | None = None,
    ) -> Phase | None:
        stmt = select(m.Phase).where(m.Phase.code == code)
        if workflow_id is not None:
            stmt = stmt.where(m.Phase.workflow_id == workflow_id)
            mode_id = mode_id if mode_id is not None else self._find_default_mode_id(workflow_id)
            if mode_id is None:
                return None
        elif mode_id is None:
            stmt = stmt.join(m.WorkflowMode, m.Phase.mode_id == m.WorkflowMode.id).where(
                m.WorkflowMode.key == "default"
            )
        if mode_id is not None:
            stmt = stmt.where(m.Phase.mode_id == mode_id)
        row = self._session.execute(stmt).scalars().first()
        return _row_to_phase(row) if row else None

    def create(self, data: dict[str, Any]) -> int:
        workflow_id = int(data["workflow_id"])
        mode_id = int(data.get("mode_id") or self._default_mode_id(workflow_id))
        mode = self._session.get(m.WorkflowMode, mode_id)
        if mode is None or mode.workflow_id != workflow_id:
            raise ValueError("Phase mode must belong to its workflow")
        item = m.Phase(
            workflow_id=workflow_id,
            mode_id=mode_id,
            code=data["code"],
            name=data["name"],
            description=data.get("description"),
            min_time_min=data.get("min_time_min", 0),
            phase_order=data["phase_order"],
            agent_id=data.get("agent_id"),
            next_recommendation=data.get("next_recommendation"),
            parallel_with=data.get("parallel_with"),
            rollback_target=data.get("rollback_target"),
            execution_type=data.get("execution_type", "sync"),
            is_seed_managed=1 if data.get("is_seed_managed") else 0,
            is_blocker=1 if data.get("is_blocker") else 0,
            is_delegated=1 if data.get("is_delegated") else 0,
            is_critic=1 if data.get("is_critic") else 0,
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, phase_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.Phase, phase_id)
        if row is None:
            raise NotFoundError(f"Phase {phase_id} not found")
        for key, val in data.items():
            if key in {"id", "workflow_id", "mode_id"}:
                continue
            if key in {"is_seed_managed", "is_blocker", "is_delegated", "is_critic"}:
                val = 1 if val else 0
            if hasattr(row, key):
                setattr(row, key, val)

    def delete(self, phase_id: int) -> None:
        row = self._session.get(m.Phase, phase_id)
        if row is None:
            raise NotFoundError(f"Phase {phase_id} not found")
        remaining = (
            self._session.execute(
                select(m.Phase).where(
                    m.Phase.workflow_id == row.workflow_id,
                    m.Phase.mode_id == row.mode_id,
                    m.Phase.id != phase_id,
                )
            )
            .scalars()
            .all()
        )
        if not remaining:
            raise LastPhaseError("Cannot delete the only phase of a workflow")
        # Cascade delete content rows explicitly (mirror ON DELETE CASCADE).
        for child_class in (m.Instruction, m.Check, m.Evidence):
            self._session.execute(
                text(f"DELETE FROM {child_class.__tablename__} WHERE phase_id = :pid"),
                {"pid": phase_id},
            )
        self._session.delete(row)

    def shift_orders(
        self,
        workflow_id: int,
        start_order: int,
        delta: int = 1,
        mode_id: int | None = None,
    ) -> None:
        mode_id = mode_id if mode_id is not None else self._default_mode_id(workflow_id)
        self._session.execute(
            text(
                "UPDATE phases SET phase_order = phase_order + :delta "
                "WHERE workflow_id = :wid AND mode_id = :mid AND phase_order >= :start"
            ),
            {"delta": delta, "wid": workflow_id, "mid": mode_id, "start": start_order},
        )

    def get_next_order(self, workflow_id: int, mode_id: int | None = None) -> int:
        mode_id = mode_id if mode_id is not None else self._default_mode_id(workflow_id)
        max_order = self._session.execute(
            select(m.Phase.phase_order)
            .where(m.Phase.workflow_id == workflow_id, m.Phase.mode_id == mode_id)
            .order_by(m.Phase.phase_order.desc())
        ).scalar()
        return (max_order or 0) + 1

    def get_checks(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(select(m.Check).where(m.Check.phase_id == phase_id)).scalars().all()
        return [{"id": r.id, "phase_id": r.phase_id, "description": r.description} for r in rows]

    def get_evidence(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(select(m.Evidence).where(m.Evidence.phase_id == phase_id)).scalars().all()
        return [{"id": r.id, "phase_id": r.phase_id, "description": r.description} for r in rows]

    def set_checks(self, phase_id: int, items: builtins.list[dict[str, Any]]) -> None:
        self._session.execute(sa_delete(m.Check).where(m.Check.phase_id == phase_id))
        for item in items:
            self._session.add(m.Check(phase_id=phase_id, description=item.get("description", "")))

    def set_evidence(self, phase_id: int, items: builtins.list[dict[str, Any]]) -> None:
        self._session.execute(sa_delete(m.Evidence).where(m.Evidence.phase_id == phase_id))
        for item in items:
            self._session.add(m.Evidence(phase_id=phase_id, description=item.get("description", "")))
