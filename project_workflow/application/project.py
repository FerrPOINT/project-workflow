"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from project_workflow import config
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork


class ProjectService:
    """Use cases for projects."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    @staticmethod
    def _normalized_prefixes(raw: Any) -> list[str]:
        if not isinstance(raw, list) or any(not isinstance(prefix, str) for prefix in raw):
            raise ValueError("Task key prefixes must be a list of strings")
        if any(not prefix.strip() for prefix in raw):
            raise ValueError("Task key prefixes must not be blank")
        prefixes = [prefix.strip().upper() for prefix in raw]
        if not prefixes:
            raise ValueError("At least one task key prefix is required")
        if len(prefixes) != len(set(prefixes)):
            raise ConflictError("Task key prefixes must be unique inside a project")
        return prefixes

    def _ensure_prefixes_available(self, prefixes: list[str], *, project_id: int | None = None) -> None:
        requested = set(prefixes)
        for project in self._uow.projects.list():
            if project.id == project_id:
                continue
            existing_prefixes = {str(prefix).strip().upper() for prefix in project.key_prefixes}
            overlap = requested.intersection(existing_prefixes)
            if overlap:
                duplicate = sorted(overlap)[0]
                raise ConflictError(
                    f"Task key prefix {duplicate!r} is already assigned to project {project.code!r}"
                )

    @staticmethod
    def _matches_prefix(task_key: str, prefixes: list[str]) -> bool:
        return any(task_key == prefix or task_key.startswith(f"{prefix}-") for prefix in prefixes)

    def create_project(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        self._uow.projects.lock_prefix_namespace()
        if "workflow_id" not in payload or payload["workflow_id"] is None:
            default_wf = self._uow.workflows.ensure_default_exists(config.DEFAULT_WORKFLOW_NAME)
            payload["workflow_id"] = default_wf.id if default_wf else None
        if "name" not in payload or not payload["name"]:
            payload["name"] = payload["code"]
        workflow_id = int(payload["workflow_id"])
        if self._uow.workflows.lock(workflow_id) is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        if "key_prefixes" not in payload:
            raise ValueError("Task key prefixes are required")
        payload["key_prefixes"] = self._normalized_prefixes(payload["key_prefixes"])
        self._ensure_prefixes_available(payload["key_prefixes"])
        if self._uow.projects.get_by_code(payload["code"]):
            raise ConflictError(f"Project code {payload['code']!r} already exists")
        pid = self._uow.projects.create(payload)
        project = self._uow.projects.get_by_id(pid)
        if not project:
            raise RuntimeError("Project creation failed")
        self._uow.commit()
        return project.to_dict()

    def list_projects(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self._uow.projects.list()]

    def get_project(self, project_id: int) -> dict[str, Any] | None:
        p = self._uow.projects.get_by_id(project_id)
        return p.to_dict() if p else None

    def update_project(self, project_id: int, data: dict[str, Any]) -> None:
        payload = dict(data)
        self._uow.projects.lock_prefix_namespace()
        snapshot = self._uow.projects.get_by_id(project_id)
        if snapshot is None:
            raise NotFoundError(f"Project {project_id} not found")
        workflow_ids = {snapshot.workflow_id}
        if "workflow_id" in payload:
            workflow_ids.add(int(payload["workflow_id"]))
        for workflow_id in sorted(workflow_ids):
            if self._uow.workflows.lock(workflow_id) is None:
                raise NotFoundError(f"Workflow {workflow_id} not found")
        existing = self._uow.projects.lock(project_id)
        if existing is None:
            raise NotFoundError(f"Project {project_id} not found")
        if existing.workflow_id != snapshot.workflow_id:
            raise ConflictError("Project workflow changed while the update was waiting for locks")
        if "code" in payload and payload["code"] != existing.code:
            same_code = self._uow.projects.get_by_code(payload["code"])
            if same_code is not None and same_code.id != project_id:
                raise ConflictError(f"Project code {payload['code']!r} already exists")
        project_tasks = list(self._uow.tasks.list_by_project(project_id))
        if "workflow_id" in payload and int(payload["workflow_id"]) != existing.workflow_id:
            if project_tasks:
                raise ConflictError("Project workflow cannot be changed while the project has tasks")
        if "key_prefixes" in payload:
            payload["key_prefixes"] = self._normalized_prefixes(payload["key_prefixes"])
            self._ensure_prefixes_available(payload["key_prefixes"], project_id=project_id)
            inaccessible = [
                task.task_key
                for task in project_tasks
                if not self._matches_prefix(task.task_key, payload["key_prefixes"])
            ]
            if inaccessible:
                raise ConflictError(
                    f"Task key {sorted(inaccessible)[0]!r} would no longer match the project prefixes"
                )
        self._uow.projects.update(project_id, payload)
        self._uow.commit()
        return None

    def delete_project(self, project_id: int) -> None:
        self._uow.projects.lock_prefix_namespace()
        snapshot = self._uow.projects.get_by_id(project_id)
        if snapshot is None:
            raise NotFoundError(f"Project {project_id} not found")
        if self._uow.workflows.lock(snapshot.workflow_id) is None:
            raise NotFoundError(f"Workflow {snapshot.workflow_id} not found")
        existing = self._uow.projects.lock(project_id)
        if existing is None:
            raise NotFoundError(f"Project {project_id} not found")
        if existing.workflow_id != snapshot.workflow_id:
            raise ConflictError("Project workflow changed while deletion was waiting for locks")
        if self._uow.tasks.list_by_project(project_id):
            raise ConflictError("Project has linked tasks and cannot be deleted")
        self._uow.projects.delete(project_id)
        self._uow.commit()
        return None
