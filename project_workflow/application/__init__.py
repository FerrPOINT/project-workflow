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

    def delete_workflow(self, workflow_id: int) -> None:
        with self._uow:
            # Mirror legacy WorkflowDB behaviour: cascade-delete phases (including
            # the last one) and then the workflow, but block on linked projects.
            projects = self._uow.projects.list()
            for project in projects:
                if project.workflow_id == workflow_id:
                    raise ConflictError("Workflow has linked projects and cannot be deleted")
            self._uow.workflows.delete(workflow_id)

    def ensure_default_exists(self) -> dict[str, Any]:
        with self._uow:
            wf = self._uow.workflows.ensure_default_exists()
            result = wf.to_dict()
            return result


class PhaseServiceApp:
    """Use cases for phases."""

    DEFAULT_PHASE_NAME = "Новая фаза"

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def _generate_code(self, workflow_id: int, order: int) -> str:
        prefix = "ui-phase-"
        existing = self._uow.phases.list(workflow_id)
        max_num = 0
        for phase in existing:
            if phase.code.startswith(prefix):
                suffix = phase.code[len(prefix):]
                try:
                    max_num = max(max_num, int(suffix))
                except ValueError:
                    pass
        return f"{prefix}{max_num + 1}"

    def create_phase(self, data: dict[str, Any]) -> dict[str, Any]:
        workflow_id = data["workflow_id"]
        with self._uow:
            order = data.get("phase_order")
            if order is None:
                order = self._uow.phases.get_next_order(workflow_id)
            else:
                order = int(order)
                existing = self._uow.phases.list(workflow_id)
                if any(p.phase_order == order for p in existing):
                    self._uow.phases.shift_orders(workflow_id, order, delta=1)

            phase_data = {
                "workflow_id": workflow_id,
                "code": data.get("code") or self._generate_code(workflow_id, order),
                "name": data.get("name", self.DEFAULT_PHASE_NAME),
                "description": data.get("description", ""),
                "execution_type": data.get("execution_type", "sync"),
                "phase_order": order,
                "agent_id": data.get("agent_id"),
                "next_recommendation": data.get("next_recommendation"),
                "parallel_with": data.get("parallel_with"),
                "rollback_target": data.get("rollback_target"),
                "is_seed_managed": data.get("is_seed_managed", False),
                "min_time_min": data.get("min_time_min", 0),
            }
            pid = self._uow.phases.create(phase_data)
            phase = self._uow.phases.get_by_id(pid)
            if not phase:
                raise RuntimeError("Phase creation failed")
            return phase.to_dict()

    def list_phases(self, workflow_id: int | None = None) -> list[dict[str, Any]]:
        with self._uow:
            return [p.to_dict() for p in self._uow.phases.list(workflow_id)]

    def get_phase(self, phase_id: int) -> dict[str, Any] | None:
        with self._uow:
            p = self._uow.phases.get_by_id(phase_id)
            return p.to_dict() if p else None

    def update_phase(self, phase_id: int, data: dict[str, Any]) -> None:
        with self._uow:
            self._uow.phases.update(phase_id, data)

    def delete_phase(self, phase_id: int) -> None:
        with self._uow:
            self._uow.phases.delete(phase_id)


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


class TaskService:
    """Use cases for tasks."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_task(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._uow:
            tid = self._uow.tasks.create(data)
            task = self._uow.tasks.get_by_id(tid)
            if not task:
                raise RuntimeError("Task creation failed")
            return task.to_dict()

    def get_task_by_key(self, task_key: str) -> dict[str, Any] | None:
        with self._uow:
            t = self._uow.tasks.get_by_key(task_key)
            return t.to_dict() if t else None

    def update_task(self, task_id: int, data: dict[str, Any]) -> None:
        with self._uow:
            self._uow.tasks.update(task_id, data)

    def add_history(self, task_id: int, phase_id: int, status: str) -> None:
        with self._uow:
            self._uow.tasks.add_history(task_id, phase_id, status)


class AgentService:
    """Use cases for agents."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_agent(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._uow:
            aid = self._uow.agents.create(data)
            agent = self._uow.agents.get_by_id(aid)
            if not agent:
                raise RuntimeError("Agent creation failed")
            return agent.to_dict()

    def list_agents(self) -> list[dict[str, Any]]:
        with self._uow:
            return [a.to_dict() for a in self._uow.agents.list()]

    def get_agent(self, agent_id: int) -> dict[str, Any] | None:
        with self._uow:
            a = self._uow.agents.get_by_id(agent_id)
            return a.to_dict() if a else None

    def update_agent(self, agent_id: int, data: dict[str, Any]) -> None:
        with self._uow:
            self._uow.agents.update(agent_id, data)

    def delete_agent(self, agent_id: int) -> None:
        with self._uow:
            self._uow.agents.delete(agent_id)
