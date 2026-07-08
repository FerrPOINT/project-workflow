"""SQLAlchemy repository implementations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from project_workflow.domain import Project
from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.repositories import ProjectRepository
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.converters import _row_to_project


class SAProjectRepository(ProjectRepository):
    """SQLAlchemy implementation of ProjectRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self) -> Sequence[Project]:
        rows = self._session.execute(select(m.Project)).scalars().all()
        return [_row_to_project(r) for r in rows]

    def get_by_id(self, project_id: int) -> Project | None:
        row = self._session.get(m.Project, project_id)
        return _row_to_project(row) if row else None

    def get_by_code(self, code: str) -> Project | None:
        row = self._session.execute(select(m.Project).where(m.Project.code == code)).scalar_one_or_none()
        return _row_to_project(row) if row else None

    def create(self, data: dict[str, Any]) -> int:
        prefixes = data.get("key_prefixes", [])
        item = m.Project(
            workflow_id=data["workflow_id"],
            code=data["code"],
            name=data["name"],
            key_prefixes=json.dumps([str(p) for p in prefixes], ensure_ascii=False),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, project_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.Project, project_id)
        if row is None:
            raise NotFoundError(f"Project {project_id} not found")
        if "workflow_id" in data:
            row.workflow_id = data["workflow_id"]
        if "code" in data:
            row.code = data["code"]
        if "name" in data:
            row.name = data["name"]
        if "key_prefixes" in data:
            prefixes = data["key_prefixes"]
            row.key_prefixes = json.dumps([str(p) for p in prefixes], ensure_ascii=False)

    def delete(self, project_id: int) -> None:
        row = self._session.get(m.Project, project_id)
        if row is None:
            raise NotFoundError(f"Project {project_id} not found")
        self._session.delete(row)

    def match_by_task_key(self, task_key: str) -> Project | None:
        for project in self.list():
            for prefix in project.key_prefixes:
                import re

                if re.match(rf"^{re.escape(prefix)}-[0-9]+$", task_key):
                    return project
        return None


