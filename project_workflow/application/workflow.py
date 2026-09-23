"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.runtime_assignment import normalize_role_key


class WorkflowService:
    """Use cases for workflow templates."""

    DEFAULT_PHASE_NAME = "Новая фаза"

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_workflow(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        try:
            wid = self._uow.workflows.create(payload)
            default_mode = self._uow.workflows.get_mode_by_key(wid, "default")
            if default_mode is None or default_mode.id is None:
                raise RuntimeError("Не удалось создать режим по умолчанию")
            mode_id = default_mode.id
            default_phase = {
                "workflow_id": wid,
                "mode_id": mode_id,
                "code": f"wf-{wid}-default",
                "name": self.DEFAULT_PHASE_NAME,
                "description": "",
                "phase_order": 1,
                "agent_id": None,
                "parallel_with_phase_id": None,
                "rollback_target_phase_id": None,
                "execution_type": "sync",
            }
            self._uow.phases.create(default_phase)
            workflow = self._uow.workflows.get_by_id(wid)
            if not workflow:
                raise RuntimeError("Не удалось создать воркфлоу")
            self._uow.commit()
            return workflow.to_dict()
        except Exception:
            self._uow.rollback()
            raise

    def list_workflows(self) -> list[dict[str, Any]]:
        return [w.to_dict() for w in self._uow.workflows.list()]

    def get_workflow(self, workflow_id: int) -> dict[str, Any] | None:
        w = self._uow.workflows.get_by_id(workflow_id)
        return w.to_dict() if w else None

    def list_modes(self, workflow_id: int) -> list[dict[str, Any]]:
        if self._uow.workflows.get_by_id(workflow_id) is None:
            raise NotFoundError(f"Воркфлоу {workflow_id} не найден")
        return [mode.to_dict() for mode in self._uow.workflows.list_modes(workflow_id)]

    def create_mode(self, workflow_id: int, data: dict[str, Any]) -> dict[str, Any]:
        workflow = self._uow.workflows.lock(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Воркфлоу {workflow_id} не найден")
        payload = dict(data)
        payload["workflow_id"] = workflow_id
        if payload.get("role_key") is not None:
            payload["role_key"] = normalize_role_key(payload["role_key"])
        if "mode_order" not in payload:
            payload["mode_order"] = len(self._uow.workflows.list_modes(workflow_id)) + 1
        mode_id = self._uow.workflows.create_mode(payload)
        mode = self._uow.workflows.get_mode(mode_id, workflow_id)
        if mode is None:
            raise RuntimeError("Не удалось создать режим воркфлоу")
        self._uow.commit()
        return mode.to_dict()

    def update_workflow(self, workflow_id: int, data: dict[str, Any]) -> None:
        workflow = self._uow.workflows.lock(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Воркфлоу {workflow_id} не найден")
        try:
            payload = dict(data)
            self._uow.workflows.update(workflow_id, payload)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return None

    def delete_workflow(self, workflow_id: int) -> None:
        workflow = self._uow.workflows.lock(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Воркфлоу {workflow_id} не найден")
        try:
            if workflow.is_default:
                raise ConflictError("Воркфлоу по умолчанию нельзя удалить")

            fallback = self._uow.workflows.get_default()
            if fallback is None or fallback.id is None:
                raise ConflictError("Нельзя удалить воркфлоу без воркфлоу по умолчанию")

            projects = [project for project in self._uow.projects.list() if project.workflow_id == workflow_id]
            project_ids: list[int] = []
            for project in projects:
                project_id = project.id
                if project_id is None:
                    raise ConflictError("Неймспейс воркфлоу повреждён")
                if self._uow.tasks.list_by_project(project_id):
                    raise ConflictError("Воркфлоу содержит задачи; сначала перенесите или удалите их")
                project_ids.append(project_id)

            phases = [
                phase
                for mode in self._uow.workflows.list_modes(workflow_id)
                if mode.id is not None
                for phase in self._uow.phases.list(workflow_id, mode_id=mode.id)
            ]
            for phase in phases:
                if phase.id is None:
                    raise ConflictError("Фаза воркфлоу повреждена")
                self._uow.phases.update(
                    phase.id,
                    {"parallel_with_phase_id": None, "rollback_target_phase_id": None},
                )
            for project_id in project_ids:
                self._uow.projects.update(project_id, {"workflow_id": fallback.id})

            self._uow.workflows.delete(workflow_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return None
