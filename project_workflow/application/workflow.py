"""Application services — use cases."""
from __future__ import annotations
from typing import Any
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork

class WorkflowService:
    """Use cases for workflow templates."""
    DEFAULT_PHASE_NAME = 'Новая фаза'

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_workflow(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        wid = self._uow.workflows.create(payload)
        if not payload.get('_skip_default_phase'):
            default_phase = {'workflow_id': wid, 'code': f'wf-{wid}-default', 'name': self.DEFAULT_PHASE_NAME, 'description': '', 'min_time_min': 0, 'phase_order': 1, 'agent_id': None, 'next_recommendation': None, 'parallel_with': None, 'rollback_target': None, 'execution_type': 'sync', 'is_seed_managed': False}
            self._uow.phases.create(default_phase)
        workflow = self._uow.workflows.get_by_id(wid)
        if not workflow:
            raise RuntimeError('Workflow creation failed')
        self._uow.commit()
        return workflow.to_dict()

    def get_or_create_smoke_workflow(self) -> dict[str, Any]:
        from project_workflow import config
        wf = self._uow.workflows.get_by_name(config.SMOKE_WORKFLOW_NAME)
        if wf:
            return wf.to_dict()
        wf_dict = self.create_workflow({
            "name": config.SMOKE_WORKFLOW_NAME,
            "description": "Smoke test workflow",
            "_skip_default_phase": True,
        })
        return wf_dict

    def list_workflows(self) -> list[dict[str, Any]]:
        return [w.to_dict() for w in self._uow.workflows.list()]

    def get_workflow(self, workflow_id: int) -> dict[str, Any] | None:
        w = self._uow.workflows.get_by_id(workflow_id)
        return w.to_dict() if w else None

    def get_workflow_by_name(self, name: str) -> dict[str, Any] | None:
        wf = self._uow.workflows.get_by_name(name)
        return wf.to_dict() if wf else None

    def update_workflow(self, workflow_id: int, data: dict[str, Any]) -> None:
        self._uow.workflows.update(workflow_id, data)
        self._uow.commit()
        return None

    def delete_workflow(self, workflow_id: int) -> None:
        projects = self._uow.projects.list()
        for project in projects:
            if project.workflow_id == workflow_id:
                raise ConflictError('Workflow has linked projects and cannot be deleted')
        self._uow.workflows.delete(workflow_id)
        self._uow.commit()
        return None

    def ensure_default_exists(self) -> dict[str, Any]:
        wf = self._uow.workflows.ensure_default_exists()
        result = wf.to_dict()
        return result
