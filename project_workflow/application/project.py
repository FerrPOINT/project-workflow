"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork


class ProjectService:
    """Use cases for projects."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    @staticmethod
    def _normalized_prefixes(raw: Any) -> list[str]:
        if not isinstance(raw, list) or any(not isinstance(prefix, str) for prefix in raw):
            raise ValueError("Префиксы ключей задач должны быть массивом строк")
        if any(not prefix.strip() for prefix in raw):
            raise ValueError("Префиксы ключей задач не могут быть пустыми")
        prefixes = [prefix.strip().upper() for prefix in raw]
        if not prefixes:
            raise ValueError("Нужен хотя бы один префикс ключа задачи")
        if len(prefixes) != len(set(prefixes)):
            raise ConflictError("Префиксы ключей задач внутри проекта должны быть уникальными")
        return prefixes

    def _ensure_prefixes_available(self, prefixes: list[str], *, project_id: int | None = None) -> None:
        requested = set(prefixes)
        for project in self._uow.projects.list():
            if project.id == project_id:
                continue
            existing_prefixes = {prefix.strip().upper() for prefix in project.key_prefixes}
            overlap = requested.intersection(existing_prefixes)
            if overlap:
                duplicate = sorted(overlap)[0]
                raise ConflictError(
                    f"Префикс ключа задачи {duplicate!r} уже назначен проекту {project.code!r}"
                )

    @staticmethod
    def _matches_prefix(task_key: str, prefixes: list[str]) -> bool:
        return any(task_key == prefix or task_key.startswith(f"{prefix}-") for prefix in prefixes)

    def create_project(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        self._uow.projects.lock_prefix_namespace()
        workflow_id_raw = payload.get("workflow_id")
        if (
            not isinstance(workflow_id_raw, int)
            or isinstance(workflow_id_raw, bool)
            or workflow_id_raw <= 0
        ):
            raise ValueError("workflow_id проекта должен быть положительным целым числом")
        if "name" not in payload or not payload["name"]:
            payload["name"] = payload["code"]
        workflow_id = workflow_id_raw
        if self._uow.workflows.lock(workflow_id) is None:
            raise NotFoundError(f"Воркфлоу {workflow_id} не найден")
        if "key_prefixes" not in payload:
            raise ValueError("Необходимо указать префиксы ключей задач")
        payload["key_prefixes"] = self._normalized_prefixes(payload["key_prefixes"])
        self._ensure_prefixes_available(payload["key_prefixes"])
        if self._uow.projects.get_by_code(payload["code"]):
            raise ConflictError(f"Код проекта {payload['code']!r} уже существует")
        pid = self._uow.projects.create(payload)
        project = self._uow.projects.get_by_id(pid)
        if not project:
            raise RuntimeError("Не удалось создать проект")
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
            raise NotFoundError(f"Проект {project_id} не найден")
        workflow_ids = {snapshot.workflow_id}
        if "workflow_id" in payload:
            workflow_ids.add(int(payload["workflow_id"]))
        for workflow_id in sorted(workflow_ids):
            if self._uow.workflows.lock(workflow_id) is None:
                raise NotFoundError(f"Воркфлоу {workflow_id} не найден")
        existing = self._uow.projects.lock(project_id)
        if existing is None:
            raise NotFoundError(f"Проект {project_id} не найден")
        if existing.workflow_id != snapshot.workflow_id:
            raise ConflictError("Воркфлоу проекта изменился во время ожидания блокировки")
        if "code" in payload and payload["code"] != existing.code:
            same_code = self._uow.projects.get_by_code(payload["code"])
            if same_code is not None and same_code.id != project_id:
                raise ConflictError(f"Код проекта {payload['code']!r} уже существует")
        project_tasks = list(self._uow.tasks.list_by_project(project_id))
        if "workflow_id" in payload and int(payload["workflow_id"]) != existing.workflow_id:
            if project_tasks:
                raise ConflictError("Нельзя сменить воркфлоу проекта, пока в нём есть задачи")
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
                    f"Ключ задачи {sorted(inaccessible)[0]!r} перестанет соответствовать префиксам проекта"
                )
        self._uow.projects.update(project_id, payload)
        self._uow.commit()
        return None

    def delete_project(self, project_id: int) -> None:
        self._uow.projects.lock_prefix_namespace()
        snapshot = self._uow.projects.get_by_id(project_id)
        if snapshot is None:
            raise NotFoundError(f"Проект {project_id} не найден")
        if self._uow.workflows.lock(snapshot.workflow_id) is None:
            raise NotFoundError(f"Воркфлоу {snapshot.workflow_id} не найден")
        existing = self._uow.projects.lock(project_id)
        if existing is None:
            raise NotFoundError(f"Проект {project_id} не найден")
        if existing.workflow_id != snapshot.workflow_id:
            raise ConflictError("Воркфлоу проекта изменился во время ожидания удаления")
        if self._uow.tasks.list_by_project(project_id):
            raise ConflictError("Проект связан с задачами, поэтому удалить его нельзя")
        self._uow.projects.delete(project_id)
        self._uow.commit()
        return None
