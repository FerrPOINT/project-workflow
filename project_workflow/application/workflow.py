"""Application services — use cases."""
from __future__ import annotations

from typing import Any

from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork


class WorkflowService:
    """Use cases for workflow templates."""

    DEFAULT_PHASE_NAME = "Новая фаза"

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_workflow(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._uow:
            wid = self._uow.workflows.create(data)
            if not data.get("_skip_default_phase"):
                default_phase = {
                    "workflow_id": wid,
                    "code": f"wf-{wid}-default",
                    "name": self.DEFAULT_PHASE_NAME,
                    "description": "",
                    "min_time_min": 0,
                    "phase_order": 1,
                    "agent_id": None,
                    "next_recommendation": None,
                    "parallel_with": None,
                    "rollback_target": None,
                    "execution_type": "sync",
                    "is_seed_managed": False,
                }
                self._uow.phases.create(default_phase)
            workflow = self._uow.workflows.get_by_id(wid)
            if not workflow:
                raise RuntimeError("Workflow creation failed")
            return workflow.to_dict()

    def list_workflows(self) -> list[dict[str, Any]]:
        with self._uow:
            return [w.to_dict() for w in self._uow.workflows.list()]

    def get_workflow(self, workflow_id: int) -> dict[str, Any] | None:
        with self._uow:
            w = self._uow.workflows.get_by_id(workflow_id)
            return w.to_dict() if w else None

    def update_workflow(self, workflow_id: int, data: dict[str, Any]) -> None:
        with self._uow:
            self._uow.workflows.update(workflow_id, data)
            return None

    def delete_workflow(self, workflow_id: int) -> None:
        with self._uow:
            # Mirror legacy WorkflowDB behaviour: cascade-delete phases (including
            # the last one) and then the workflow, but block on linked projects.
            projects = self._uow.projects.list()
            for project in projects:
                if project.workflow_id == workflow_id:
                    raise ConflictError("Workflow has linked projects and cannot be deleted")
            self._uow.workflows.delete(workflow_id)
            return None

    def ensure_default_exists(self) -> dict[str, Any]:
        with self._uow:
            wf = self._uow.workflows.ensure_default_exists()
            result = wf.to_dict()
            return result

