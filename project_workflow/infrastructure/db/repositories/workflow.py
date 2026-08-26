"""SQLAlchemy repository implementations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from project_workflow.domain import Workflow
from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.repositories import WorkflowRepository
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.converters import _row_to_workflow


class SAWorkflowRepository(WorkflowRepository):
    """SQLAlchemy implementation of WorkflowRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self) -> Sequence[Workflow]:
        rows = self._session.execute(select(m.Workflow).order_by(m.Workflow.id)).scalars().all()
        return [_row_to_workflow(r) for r in rows]

    def get_by_id(self, workflow_id: int) -> Workflow | None:
        row = self._session.get(m.Workflow, workflow_id)
        if row is None:
            return None
        return _row_to_workflow(row)

    def get_default(self) -> Workflow | None:
        row = self._session.execute(select(m.Workflow).where(m.Workflow.is_default == 1)).scalar_one_or_none()
        return _row_to_workflow(row) if row else None

    def lock(self, workflow_id: int) -> Workflow | None:
        row = self._session.execute(
            select(m.Workflow).where(m.Workflow.id == workflow_id).with_for_update()
        ).scalar_one_or_none()
        return _row_to_workflow(row) if row else None

    def create(self, data: dict[str, Any]) -> int:
        item = m.Workflow(
            name=data["name"],
            description=data.get("description", ""),
            is_default=1 if data.get("is_default") else 0,
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, workflow_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.Workflow, workflow_id)
        if row is None:
            raise NotFoundError(f"Воркфлоу {workflow_id} не найден")
        if "name" in data:
            row.name = data["name"]
        if "description" in data:
            row.description = data["description"]
        if "is_default" in data:
            row.is_default = 1 if data["is_default"] else 0

    def delete(self, workflow_id: int) -> None:
        row = self._session.get(m.Workflow, workflow_id)
        if row is None:
            raise NotFoundError(f"Воркфлоу {workflow_id} не найден")
        self._session.delete(row)

    def ensure_default_exists(self, name: str) -> Workflow:
        existing = self.get_default()
        if existing:
            return existing
        new_id = self.create({"name": name, "is_default": True})
        created = self.get_by_id(new_id)
        if created is None:
            raise RuntimeError(f"Не удалось создать воркфлоу по умолчанию {name}")
        return created


