"""Application services — use cases."""

from __future__ import annotations

from typing import Any

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork


class WorkflowService:
    """Use cases for workflow templates."""

    DEFAULT_PHASE_NAME = "Новая фаза"

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_workflow(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        try:
            wid = self._uow.workflows.create(payload)
            default_phase = {
                "workflow_id": wid,
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

    def update_workflow(self, workflow_id: int, data: dict[str, Any]) -> None:
        workflow = self._uow.workflows.lock(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Воркфлоу {workflow_id} не найден")
        payload = dict(data)
        self._uow.workflows.update(workflow_id, payload)
        self._uow.commit()
        return None

    def delete_workflow(self, workflow_id: int) -> None:
        workflow = self._uow.workflows.lock(workflow_id)
        if workflow is None:
            raise NotFoundError(f"Воркфлоу {workflow_id} не найден")
        if workflow.is_default:
            raise ConflictError("Воркфлоу по умолчанию нельзя удалить")
        if any(project.workflow_id == workflow_id for project in self._uow.projects.list()):
            raise ConflictError("Воркфлоу используется, поэтому удалить его нельзя")
        starter_code = f"wf-{workflow_id}-default"
        if any(phase.code != starter_code for phase in self._uow.phases.list(workflow_id)):
            raise ConflictError("Воркфлоу содержит дополнительные фазы, поэтому удалить его нельзя")
        self._uow.workflows.delete(workflow_id)
        self._uow.commit()
        return None
