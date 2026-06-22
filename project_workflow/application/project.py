"""Application services — use cases."""
from __future__ import annotations

from typing import Any, List, cast

from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork


class ProjectService:
    """Use cases for projects."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_project(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._uow:
            payload = dict(data)
            if "workflow_id" not in payload or payload["workflow_id"] is None:
                default_wf = self._uow.workflows.ensure_default_exists()
                payload["workflow_id"] = default_wf.id
            if "name" not in payload or not payload["name"]:
                payload["name"] = payload["code"]
            pid = self._uow.projects.create(payload)
            project = self._uow.projects.get_by_id(pid)
            if not project:
                raise RuntimeError("Project creation failed")
            return project.to_dict()

    def list_projects(self) -> list[dict[str, Any]]:
        with self._uow:
            return [p.to_dict() for p in self._uow.projects.list()]

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        with self._uow:
            p = self._uow.projects.get_by_id(project_id)
            return p.to_dict() if p else None

    def update_project(self, project_id: int, data: dict[str, Any]) -> None:
        with self._uow:
            self._uow.projects.update(project_id, data)

    def delete_project(self, project_id: int) -> None:
        with self._uow:
            # Mirror WorkflowDB behavior: project with linked tasks cannot be deleted.
            tasks = self._uow.tasks.list()
            for task in tasks:
                if task.project_id == project_id:
                    raise ConflictError("Project has linked tasks and cannot be deleted")
            self._uow.projects.delete(project_id)

