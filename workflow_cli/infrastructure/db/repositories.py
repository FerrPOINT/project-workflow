"""SQLAlchemy repository implementations."""
from __future__ import annotations

import json
from typing import Any, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from workflow_cli.domain import Agent, Phase, Project, SupervisorRun, Task, Workflow
from workflow_cli.domain.exceptions import ConflictError, LastPhaseError, NotFoundError
from workflow_cli.domain.repositories import (
    AgentRepository,
    PhaseRepository,
    ProjectRepository,
    SupervisorRunRepository,
    TaskRepository,
    WorkflowRepository,
)
from workflow_cli.infrastructure.db import models as m


def _row_to_phase(row: m.Phase) -> Phase:
    return Phase(
        id=row.id,
        workflow_id=row.workflow_id,
        code=row.code,
        name=row.name,
        description=row.description or "",
        min_time_min=row.min_time_min or 0,
        phase_order=row.phase_order,
        agent_id=row.agent_id,
        next_recommendation=row.next_recommendation or "",
        parallel_with=row.parallel_with,
        rollback_target=row.rollback_target,
        execution_type=row.execution_type or "sync",
        is_seed_managed=bool(row.is_seed_managed),
        workflow_name=row.workflow.name if row.workflow else None,
    )


def _row_to_workflow(row: m.Workflow) -> Workflow:
    return Workflow(
        id=row.id,
        name=row.name,
        description=row.description or "",
        is_default=bool(row.is_default),
    )


def _row_to_project(row: m.Project) -> Project:
    raw = row.key_patterns or "[]"
    try:
        patterns = json.loads(raw) if isinstance(raw, str) else []
    except Exception:
        patterns = []
    return Project(
        id=row.id,
        workflow_id=row.workflow_id,
        code=row.code,
        name=row.name,
        key_patterns=[str(p) for p in patterns],
        workflow_name=row.workflow.name if row.workflow else None,
    )


def _row_to_task(row: m.Task) -> Task:
    current_phase = row.current_phase or "-1"
    phase_name = None
    try:
        if current_phase and current_phase != "-1":
            phase = next(
                (p for p in row.project.workflow.phases if str(p.id) == current_phase or p.code == current_phase),
                None,
            )
            phase_name = phase.name if phase else current_phase
    except Exception:
        phase_name = current_phase
    return Task(
        id=row.id,
        project_id=row.project_id,
        task_key=row.task_key,
        title=row.title or "",
        description=row.description or "",
        current_phase=current_phase,
        current_phase_name=phase_name or "",
        status=row.status or "active",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _row_to_agent(row: m.Agent) -> Agent:
    return Agent(
        id=row.id,
        name=row.name,
        description=row.description or "",
    )


def _row_to_supervisor_run(row: m.SupervisorRun) -> SupervisorRun:
    def _parse(raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    def _parse_obj(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    return SupervisorRun(
        id=row.id,
        task_id=row.task_id,
        phase_id=row.phase_id,
        verdict=row.verdict,
        report=row.report or "",
        covered=_parse(row.covered),
        missing=_parse(row.missing),
        blockers=_parse(row.blockers),
        next_phase_id=row.next_phase_id,
        rollback_phase_id=row.rollback_phase_id,
        context_snapshot=_parse_obj(row.context_snapshot),
        response=_parse_obj(row.response),
        created_at=row.created_at,
    )


class SAWorkflowRepository(WorkflowRepository):
    """SQLAlchemy implementation of WorkflowRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self) -> Sequence[Workflow]:
        rows = self._session.execute(select(m.Workflow).order_by(m.Workflow.id)).scalars().all()
        return [_row_to_workflow(r) for r in rows]

    def get_by_id(self, workflow_id: int) -> Workflow | None:
        row = self._session.get(m.Workflow, workflow_id)
        return _row_to_workflow(row) if row else None

    def get_by_name(self, name: str) -> Workflow | None:
        row = self._session.execute(
            select(m.Workflow).where(m.Workflow.name == name)
        ).scalar_one_or_none()
        return _row_to_workflow(row) if row else None

    def get_default(self) -> Workflow | None:
        row = self._session.execute(
            select(m.Workflow).where(m.Workflow.is_default == 1)
        ).scalar_one_or_none()
        return _row_to_workflow(row) if row else None

    def create(self, data: dict[str, Any]) -> int:
        item = m.Workflow(
            name=data["name"],
            description=data.get("description", ""),
            is_default=1 if data.get("is_default") else 0,
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, workflow_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.Workflow, workflow_id)
        if row is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        if "name" in data:
            row.name = data["name"]
        if "description" in data:
            row.description = data["description"]
        if "is_default" in data:
            row.is_default = 1 if data["is_default"] else 0

    def delete(self, workflow_id: int) -> None:
        row = self._session.get(m.Workflow, workflow_id)
        if row is None:
            raise NotFoundError(f"Workflow {workflow_id} not found")
        self._session.delete(row)

    def ensure_default_exists(self, name: str = "Default Workflow") -> Workflow:
        existing = self.get_default()
        if existing:
            return existing
        rows = self.list()
        if rows:
            first = rows[0]
            self.update(first.id, {"is_default": True})
            return self.get_by_id(first.id) or first
        return self.get_by_id(self.create({"name": name, "is_default": True})) or Workflow()


class SAPhaseRepository(PhaseRepository):
    """SQLAlchemy implementation of PhaseRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self, workflow_id: int | None = None) -> Sequence[Phase]:
        stmt = select(m.Phase).order_by(m.Phase.workflow_id, m.Phase.phase_order)
        if workflow_id is not None:
            stmt = stmt.where(m.Phase.workflow_id == workflow_id)
        rows = self._session.execute(stmt).scalars().all()
        return [_row_to_phase(r) for r in rows]

    def get_by_id(self, phase_id: int) -> Phase | None:
        row = self._session.get(m.Phase, phase_id)
        return _row_to_phase(row) if row else None

    def get_by_code(self, code: str) -> Phase | None:
        row = self._session.execute(
            select(m.Phase).where(m.Phase.code == code)
        ).scalar_one_or_none()
        return _row_to_phase(row) if row else None

    def create(self, data: dict[str, Any]) -> int:
        item = m.Phase(
            workflow_id=data["workflow_id"],
            code=data["code"],
            name=data["name"],
            description=data.get("description"),
            min_time_min=data.get("min_time_min", 0),
            phase_order=data["phase_order"],
            agent_id=data.get("agent_id"),
            next_recommendation=data.get("next_recommendation"),
            parallel_with=data.get("parallel_with"),
            rollback_target=data.get("rollback_target"),
            execution_type=data.get("execution_type", "sync"),
            is_seed_managed=1 if data.get("is_seed_managed") else 0,
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, phase_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.Phase, phase_id)
        if row is None:
            raise NotFoundError(f"Phase {phase_id} not found")
        for key, val in data.items():
            if key == "is_seed_managed":
                val = 1 if val else 0
            if hasattr(row, key):
                setattr(row, key, val)

    def delete(self, phase_id: int) -> None:
        row = self._session.get(m.Phase, phase_id)
        if row is None:
            raise NotFoundError(f"Phase {phase_id} not found")
        remaining = self._session.execute(
            select(m.Phase).where(
                m.Phase.workflow_id == row.workflow_id,
                m.Phase.id != phase_id,
            )
        ).scalars().all()
        if not remaining:
            raise LastPhaseError("Cannot delete the last phase of a workflow")
        self._session.delete(row)

    def shift_orders(self, workflow_id: int, start_order: int, delta: int = 1) -> None:
        self._session.execute(
            text("UPDATE phases SET phase_order = phase_order + :delta WHERE workflow_id = :wid AND phase_order >= :start"),
            {"delta": delta, "wid": workflow_id, "start": start_order},
        )

    def get_next_order(self, workflow_id: int) -> int:
        max_order = self._session.execute(
            select(m.Phase.phase_order).where(m.Phase.workflow_id == workflow_id).order_by(m.Phase.phase_order.desc())
        ).scalar()
        return (max_order or 0) + 1

    def get_phases_for_workflow(self, workflow_id: int) -> Sequence[Phase]:
        return self.list(workflow_id=workflow_id)


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
        row = self._session.execute(
            select(m.Project).where(m.Project.code == code)
        ).scalar_one_or_none()
        return _row_to_project(row) if row else None

    def create(self, data: dict[str, Any]) -> int:
        patterns = data.get("key_patterns", [])
        item = m.Project(
            workflow_id=data["workflow_id"],
            code=data["code"],
            name=data["name"],
            key_patterns=json.dumps([str(p) for p in patterns], ensure_ascii=False),
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
        if "key_patterns" in data:
            patterns = data["key_patterns"]
            row.key_patterns = json.dumps([str(p) for p in patterns], ensure_ascii=False)

    def delete(self, project_id: int) -> None:
        row = self._session.get(m.Project, project_id)
        if row is None:
            raise NotFoundError(f"Project {project_id} not found")
        self._session.delete(row)

    def match_by_task_key(self, task_key: str) -> Project | None:
        for project in self.list():
            for pattern in project.key_patterns:
                import re
                if re.match(pattern, task_key):
                    return project
        return None


class SATaskRepository(TaskRepository):
    """SQLAlchemy implementation of TaskRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self) -> Sequence[Task]:
        rows = self._session.execute(select(m.Task).order_by(m.Task.id.desc())).scalars().all()
        return [_row_to_task(r) for r in rows]

    def get_by_id(self, task_id: int) -> Task | None:
        row = self._session.get(m.Task, task_id)
        return _row_to_task(row) if row else None

    def get_by_key(self, task_key: str) -> Task | None:
        row = self._session.execute(
            select(m.Task).where(m.Task.task_key == task_key)
        ).scalar_one_or_none()
        return _row_to_task(row) if row else None

    def create(self, data: dict[str, Any]) -> int:
        item = m.Task(
            project_id=data["project_id"],
            task_key=data["task_key"],
            title=data.get("title"),
            description=data.get("description"),
            current_phase=data.get("current_phase", "-1"),
            status=data.get("status", "active"),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, task_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.Task, task_id)
        if row is None:
            raise NotFoundError(f"Task {task_id} not found")
        for key, val in data.items():
            if hasattr(row, key):
                setattr(row, key, val)

    def add_history(self, task_id: int, phase_id: int, status: str) -> None:
        existing = self._session.execute(
            select(m.TaskHistory).where(
                m.TaskHistory.task_id == task_id,
                m.TaskHistory.phase_id == phase_id,
            )
        ).scalar_one_or_none()
        if existing:
            existing.status = status
        else:
            self._session.add(m.TaskHistory(task_id=task_id, phase_id=phase_id, status=status))

    def get_history(self, task_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.TaskHistory).where(m.TaskHistory.task_id == task_id)
        ).scalars().all()
        return [
            {
                "id": r.id,
                "task_id": r.task_id,
                "phase_id": r.phase_id,
                "status": r.status,
                "completed_at": r.completed_at,
            }
            for r in rows
        ]


class SAAgentRepository(AgentRepository):
    """SQLAlchemy implementation of AgentRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self) -> Sequence[Agent]:
        rows = self._session.execute(select(m.Agent)).scalars().all()
        return [_row_to_agent(r) for r in rows]

    def get_by_id(self, agent_id: int) -> Agent | None:
        row = self._session.get(m.Agent, agent_id)
        return _row_to_agent(row) if row else None

    def create(self, data: dict[str, Any]) -> int:
        item = m.Agent(
            name=data["name"],
            description=data.get("description", ""),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, agent_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.Agent, agent_id)
        if row is None:
            raise NotFoundError(f"Agent {agent_id} not found")
        if "name" in data:
            row.name = data["name"]
        if "description" in data:
            row.description = data["description"]

    def delete(self, agent_id: int) -> None:
        row = self._session.get(m.Agent, agent_id)
        if row is None:
            raise NotFoundError(f"Agent {agent_id} not found")
        self._session.delete(row)


class SASupervisorRunRepository(SupervisorRunRepository):
    """SQLAlchemy implementation of SupervisorRunRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(
        self,
        task_id: int | None = None,
        task_key: str | None = None,
        limit: int = 200,
    ) -> Sequence[SupervisorRun]:
        stmt = select(m.SupervisorRun).order_by(m.SupervisorRun.id.desc()).limit(limit)
        if task_id is not None:
            stmt = stmt.where(m.SupervisorRun.task_id == task_id)
        rows = self._session.execute(stmt).scalars().all()
        return [_row_to_supervisor_run(r) for r in rows]

    def create(self, data: dict[str, Any]) -> int:
        item = m.SupervisorRun(
            task_id=data["task_id"],
            phase_id=data["phase_id"],
            verdict=data["verdict"],
            report=data.get("report", ""),
            covered=json.dumps(data.get("covered", []), ensure_ascii=False),
            missing=json.dumps(data.get("missing", []), ensure_ascii=False),
            blockers=json.dumps(data.get("blockers", []), ensure_ascii=False),
            next_phase_id=data.get("next_phase_id"),
            rollback_phase_id=data.get("rollback_phase_id"),
            context_snapshot=json.dumps(data.get("context_snapshot", {}), ensure_ascii=False),
            response=json.dumps(data.get("response", {}), ensure_ascii=False),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)
