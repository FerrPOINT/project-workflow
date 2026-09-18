"""SQLAlchemy workflow-mode repository."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from project_workflow.domain import WorkflowMode
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import WorkflowModeRepository
from project_workflow.infrastructure.db import models as m


def _to_domain(row: m.WorkflowMode) -> WorkflowMode:
    return WorkflowMode(
        id=row.id,
        workflow_id=row.workflow_id,
        key=row.key,
        name=row.name,
        mode_order=row.mode_order,
    )


class SAWorkflowModeRepository(WorkflowModeRepository):
    def __init__(self, session: Session):
        self._session = session

    def list(self, workflow_id: int) -> Sequence[WorkflowMode]:
        rows = self._session.execute(
            select(m.WorkflowMode)
            .where(m.WorkflowMode.workflow_id == workflow_id)
            .order_by(m.WorkflowMode.mode_order, m.WorkflowMode.id)
        ).scalars().all()
        return [_to_domain(row) for row in rows]

    def get_by_id(self, mode_id: int) -> WorkflowMode | None:
        row = self._session.get(m.WorkflowMode, mode_id)
        return _to_domain(row) if row else None

    def get_by_key(self, workflow_id: int, key: str) -> WorkflowMode | None:
        row = self._session.execute(
            select(m.WorkflowMode).where(
                m.WorkflowMode.workflow_id == workflow_id,
                m.WorkflowMode.key == key,
            )
        ).scalar_one_or_none()
        return _to_domain(row) if row else None

    def create(self, data: dict[str, Any]) -> int:
        workflow_id = int(data["workflow_id"])
        order = data.get("mode_order")
        if order is None:
            maximum = self._session.execute(
                select(func.max(m.WorkflowMode.mode_order)).where(m.WorkflowMode.workflow_id == workflow_id)
            ).scalar()
            order = int(maximum or 0) + 1
        row = m.WorkflowMode(
            workflow_id=workflow_id,
            key=str(data["key"]),
            name=str(data.get("name") or data["key"]),
            mode_order=int(order),
        )
        self._session.add(row)
        self._session.flush()
        return int(row.id)

    def update(self, mode_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.WorkflowMode, mode_id)
        if row is None:
            raise NotFoundError(f"Workflow mode {mode_id} not found")
        for key in ("key", "name", "mode_order"):
            if key in data:
                setattr(row, key, data[key])

    def delete(self, mode_id: int) -> None:
        row = self._session.get(m.WorkflowMode, mode_id)
        if row is None:
            raise NotFoundError(f"Workflow mode {mode_id} not found")
        count = self._session.execute(
            select(func.count()).select_from(m.WorkflowMode).where(m.WorkflowMode.workflow_id == row.workflow_id)
        ).scalar_one()
        if count <= 1:
            raise ConflictError("Cannot delete the only mode of a workflow")
        if row.phases:
            raise ConflictError("Workflow mode has phases and cannot be deleted")
        self._session.delete(row)

    def ensure_default(self, workflow_id: int) -> WorkflowMode:
        existing = self.get_by_key(workflow_id, "default")
        if existing:
            return existing
        mode_id = self.create(
            {"workflow_id": workflow_id, "key": "default", "name": "Default", "mode_order": 1}
        )
        created = self.get_by_id(mode_id)
        if created is None:
            raise RuntimeError("Failed to create default workflow mode")
        return created
