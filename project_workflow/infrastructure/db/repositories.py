"""SQLAlchemy repository implementations."""
from __future__ import annotations

import json
from typing import Any, List, Sequence

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from project_workflow.domain import Agent, Phase, Project, SupervisorRun, Task, Workflow
from project_workflow.domain.exceptions import LastPhaseError, NotFoundError
from project_workflow.domain.repositories import (
    AgentRepository,
    CheckRepository,
    EvidenceRepository,
    InstructionRepository,
    PhaseRepository,
    ProjectRepository,
    SupervisorRunRepository,
    TaskRepository,
    WorkflowRepository,
)
from project_workflow.infrastructure.db import models as m


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
    raw = row.key_prefixes or "[]"
    try:
        prefixes = json.loads(raw) if isinstance(raw, str) else []
    except Exception:
        prefixes = []
    return Project(
        id=row.id,
        workflow_id=row.workflow_id,
        code=row.code,
        name=row.name,
        key_prefixes=[str(p) for p in prefixes],
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
        id=getattr(row, "id", None),
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
        if row is None:
            return None
        return _row_to_workflow(row)

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
        # Legacy schema may not have ON DELETE CASCADE on phase/workflow FKs, so
        # delete child phases and their content rows explicitly.
        for child_table in ("instructions", "checks", "evidence"):
            self._session.execute(
                text(f"DELETE FROM {child_table} WHERE phase_id IN (SELECT id FROM phases WHERE workflow_id = :wid)"),
                {"wid": workflow_id},
            )
        self._session.execute(
            text("DELETE FROM phases WHERE workflow_id = :wid"),
            {"wid": workflow_id},
        )
        self._session.delete(row)

    def ensure_default_exists(self, name: str = "Default Workflow") -> Workflow:
        existing = self.get_default()
        if existing:
            return existing
        new_id = self.create({"name": name, "is_default": True})
        created = self.get_by_id(new_id)
        if created is None:
            raise RuntimeError(f"Failed to create default workflow {name}")
        return created


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
            raise LastPhaseError("Cannot delete the only phase of a workflow")
        # Cascade delete content rows explicitly (mirror ON DELETE CASCADE).
        for child_class in (m.Instruction, m.Check, m.Evidence):
            self._session.execute(
                text(f"DELETE FROM {child_class.__tablename__} WHERE phase_id = :pid"),
                {"pid": phase_id},
            )
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

    def get_checks(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.Check).where(m.Check.phase_id == phase_id)
        ).scalars().all()
        return [{"id": r.id, "phase_id": r.phase_id, "description": r.description} for r in rows]

    def get_evidence(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.Evidence).where(m.Evidence.phase_id == phase_id)
        ).scalars().all()
        return [{"id": r.id, "phase_id": r.phase_id, "description": r.description} for r in rows]

    def set_checks(self, phase_id: int, items: List[dict[str, Any]]) -> None:
        self._session.execute(delete(m.Check).where(m.Check.phase_id == phase_id))
        for item in items:
            self._session.add(m.Check(phase_id=phase_id, description=item.get("description", "")))

    def set_evidence(self, phase_id: int, items: List[dict[str, Any]]) -> None:
        self._session.execute(delete(m.Evidence).where(m.Evidence.phase_id == phase_id))
        for item in items:
            self._session.add(m.Evidence(phase_id=phase_id, description=item.get("description", "")))


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
        prefixes = data.get("key_prefixes", [])
        item = m.Project(
            workflow_id=data["workflow_id"],
            code=data["code"],
            name=data["name"],
            key_prefixes=json.dumps([str(p) for p in prefixes], ensure_ascii=False),
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
        if "key_prefixes" in data:
            prefixes = data["key_prefixes"]
            row.key_prefixes = json.dumps([str(p) for p in prefixes], ensure_ascii=False)

    def delete(self, project_id: int) -> None:
        row = self._session.get(m.Project, project_id)
        if row is None:
            raise NotFoundError(f"Project {project_id} not found")
        self._session.delete(row)

    def match_by_task_key(self, task_key: str) -> Project | None:
        for project in self.list():
            for prefix in project.key_prefixes:
                import re
                if re.match(rf"^{re.escape(prefix)}-[0-9]+$", task_key):
                    return project
        return None


class SATaskRepository(TaskRepository):
    """SQLAlchemy implementation of TaskRepository."""

    def __init__(self, session: Session):
        self._session = session

    def get_by_key(self, task_key: str) -> Task | None:
        with self._session.no_autoflush:
            row = self._session.execute(
                select(m.Task).where(m.Task.task_key == task_key)
            ).scalar_one_or_none()
        if row is None:
            return None
        try:
            project_id = row.project_id
            project_id = int(project_id)
        except Exception:
            project_id = 0
        return Task(
            id=row.id,
            project_id=project_id,
            task_key=row.task_key,
            title=row.title or "",
            description=row.description or "",
            current_phase=row.current_phase or "-1",
            current_phase_name="",
            status=row.status or "active",
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def get_by_id(self, task_id: int) -> Task | None:
        with self._session.no_autoflush:
            row = self._session.get(m.Task, task_id)
        if row is None:
            return None
        return _row_to_task(row)

    def list(self) -> Sequence[Task]:
        with self._session.no_autoflush:
            rows = self._session.execute(select(m.Task).order_by(m.Task.id.desc())).scalars().all()
        return [_row_to_task(r) for r in rows]

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
        with self._session.no_autoflush:
            row = self._session.get(m.Task, task_id)
        if row is None:
            raise NotFoundError(f"Task {task_id} not found")
        for key, val in data.items():
            if hasattr(row, key):
                setattr(row, key, val)

    def add_history(self, task_id: int, phase_id: int, status: str) -> None:
        # Check pending objects first to avoid duplicate inserts inside the same session.
        for obj in self._session.new:
            if isinstance(obj, m.TaskHistory) and obj.task_id == task_id and obj.phase_id == phase_id:
                obj.status = status
                return
        with self._session.no_autoflush:
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
        with self._session.no_autoflush:
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

    def delete(self, task_id: int) -> None:
        with self._session.no_autoflush:
            row = self._session.get(m.Task, task_id)
        if row is None:
            raise ValueError(f"Task {task_id} not found")
        self._session.execute(
            delete(m.TaskHistory).where(m.TaskHistory.task_id == task_id)
        )
        self._session.delete(row)
        self._session.flush()


class SACheckRepository(CheckRepository):
    """SQLAlchemy implementation of CheckRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.Check).where(m.Check.phase_id == phase_id)
        ).scalars().all()
        return [
            {
                "id": r.id,
                "phase_id": r.phase_id,
                "description": r.description,
            }
            for r in rows
        ]

    def create(self, phase_id: int, data: dict[str, Any]) -> int:
        item = m.Check(phase_id=phase_id, description=data["description"])
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def delete_for_phase(self, phase_id: int) -> None:
        self._session.execute(
            text("DELETE FROM checks WHERE phase_id = :pid"),
            {"pid": phase_id},
        )


class SAEvidenceRepository(EvidenceRepository):
    """SQLAlchemy implementation of EvidenceRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.Evidence).where(m.Evidence.phase_id == phase_id)
        ).scalars().all()
        return [
            {
                "id": r.id,
                "phase_id": r.phase_id,
                "description": r.description,
            }
            for r in rows
        ]

    def create(self, phase_id: int, data: dict[str, Any]) -> int:
        item = m.Evidence(phase_id=phase_id, description=data["description"])
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def delete_for_phase(self, phase_id: int) -> None:
        self._session.execute(
            text("DELETE FROM evidence WHERE phase_id = :pid"),
            {"pid": phase_id},
        )


class SAAgentRepository(AgentRepository):
    """SQLAlchemy implementation of AgentRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self) -> Sequence[Agent]:
        rows = self._session.execute(select(m.Agent)).scalars().all()
        return [_row_to_agent(r) for r in rows]

    def get_by_name(self, name: str) -> Agent | None:
        row = self._session.execute(
            select(m.Agent).where(m.Agent.name == name)
        ).scalar_one_or_none()
        return _row_to_agent(row) if row else None

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


class SAInstructionRepository(InstructionRepository):
    """SQLAlchemy implementation of InstructionRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self, phase_id: int) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.Instruction)
            .where(m.Instruction.phase_id == phase_id)
            .order_by(m.Instruction.step_num)
        ).scalars().all()
        return [
            {
                "id": r.id,
                "phase_id": r.phase_id,
                "step_num": r.step_num,
                "description": r.description,
                "execution_type": r.execution_type or "sync",
                "skills": _parse_skills(r.skills),
            }
            for r in rows
        ]

    def get_by_id(self, instruction_id: int) -> dict[str, Any] | None:
        row = self._session.get(m.Instruction, instruction_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "phase_id": row.phase_id,
            "step_num": row.step_num,
            "description": row.description,
            "execution_type": row.execution_type or "sync",
            "skills": _parse_skills(row.skills),
        }

    def create(self, phase_id: int, data: dict[str, Any]) -> int:
        next_step = self._next_step_num(phase_id)
        item = m.Instruction(
            phase_id=phase_id,
            step_num=data.get("step_num", next_step),
            description=data["description"],
            execution_type=data.get("execution_type", "sync"),
            skills=_dump_skills(data.get("skills")),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, instruction_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.Instruction, instruction_id)
        if row is None:
            raise NotFoundError(f"Instruction {instruction_id} not found")
        if "description" in data:
            row.description = data["description"]
        if "execution_type" in data:
            row.execution_type = data["execution_type"]
        if "step_num" in data:
            row.step_num = data["step_num"]
        if "skills" in data:
            row.skills = _dump_skills(data["skills"])

    def delete(self, instruction_id: int) -> None:
        row = self._session.get(m.Instruction, instruction_id)
        if row is None:
            raise NotFoundError(f"Instruction {instruction_id} not found")
        self._session.delete(row)

    def delete_for_phase(self, phase_id: int) -> None:
        self._session.execute(
            text("DELETE FROM instructions WHERE phase_id = :pid"),
            {"pid": phase_id},
        )

    def reorder(self, phase_id: int, orders: List[tuple[int, int]]) -> None:
        """Reassign step_num values based on (instruction_id, new_step_num) pairs.

        Uses a two-stage raw-SQL update: first shift every instruction in the
        phase out of the target number range, then assign the final numbers.
        This avoids UNIQUE constraint collisions on (phase_id, step_num).
        """
        if not orders:
            return
        offset = len(orders) + 1000
        self._session.execute(
            text("UPDATE instructions SET step_num = step_num + :offset WHERE phase_id = :phase_id"),
            {"offset": offset, "phase_id": phase_id},
        )
        for instruction_id, new_step in orders:
            self._session.execute(
                text("UPDATE instructions SET step_num = :step WHERE id = :id"),
                {"step": new_step, "id": instruction_id},
            )
        self._session.flush()

    def _next_step_num(self, phase_id: int) -> int:
        max_step = self._session.execute(
            select(m.Instruction.step_num)
            .where(m.Instruction.phase_id == phase_id)
            .order_by(m.Instruction.step_num.desc())
        ).scalar()
        return (max_step or 0) + 1


class SACLIHistoryRepository:
    """SQLAlchemy repository for CLI call history."""

    def __init__(self, session: Session):
        self._session = session

    def list(self, limit: int = 200) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(
            select(m.CliHistory).order_by(m.CliHistory.id.asc()).limit(limit)
        ).scalars().all()
        return [m.model_to_dict(r) for r in rows]

    def create(
        self,
        command: str,
        task_key: str | None = None,
        request: str | None = None,
        response: str | None = None,
    ) -> int:
        item = m.CliHistory(
            command=command,
            task_key=task_key,
            request=request,
            response=response,
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)


def _parse_skills(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [str(s) for s in parsed] if isinstance(parsed, list) else []
    except Exception:
        return []


def _dump_skills(skills: Any) -> str | None:
    if skills in (None, [], ""):
        return None
    if isinstance(skills, str):
        return skills
    return json.dumps([str(s) for s in skills], ensure_ascii=False)
