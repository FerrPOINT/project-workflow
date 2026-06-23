"""Application services — use cases."""
from __future__ import annotations
from typing import Any
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork

class ProjectService:
    """Use cases for projects."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_project(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        if 'workflow_id' not in payload or payload['workflow_id'] is None:
            default_wf = self._uow.workflows.ensure_default_exists()
            payload['workflow_id'] = default_wf.id if default_wf else None
        if 'name' not in payload or not payload['name']:
            payload['name'] = payload['code']
        if 'key_prefixes' not in payload:
            payload['key_prefixes'] = [payload['code']]
        pid = self._uow.projects.create(payload)
        project = self._uow.projects.get_by_id(pid)
        if not project:
            raise RuntimeError('Project creation failed')
        self._uow.commit()
        return project.to_dict()

    def list_projects(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self._uow.projects.list()]

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        p = self._uow.projects.get_by_id(project_id)
        return p.to_dict() if p else None

    def update_project(self, project_id: int, data: dict[str, Any]) -> None:
        self._uow.projects.update(project_id, data)
        self._uow.commit()
        return None

    def delete_project(self, project_id: int) -> None:
        tasks = self._uow.tasks.list()
        for task in tasks:
            if task.project_id == project_id:
                raise ConflictError('Project has linked tasks and cannot be deleted')
        self._uow.projects.delete(project_id)
        self._uow.commit()
        return None
