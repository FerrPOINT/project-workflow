"""SQLAlchemy Unit of Work."""
from __future__ import annotations

from typing import Any, Literal

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql import select, text

from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.repositories import (
    AgentRepository,
    CheckRepository,
    EvidenceRepository,
    InstructionRepository,
    PhaseRepository,
    ProjectRepository,
    SupervisorRunRepository,
    TaskRepository,
    UnitOfWork,
    WorkflowRepository,
)
from project_workflow.infrastructure.db.models import Base
from project_workflow.infrastructure.db.repositories import (
    SAAgentRepository,
    SACheckRepository,
    SACLIHistoryRepository,
    SAEvidenceRepository,
    SAInstructionRepository,
    SAPhaseRepository,
    SAProjectRepository,
    SASupervisorRunRepository,
    SATaskRepository,
    SAWorkflowRepository,
)
from project_workflow.infrastructure.db.session import get_session


class SAUnitOfWork(UnitOfWork):
    """SQLAlchemy session-based unit of work."""

    def __init__(self, db_path_or_engine: str | Engine | None = None):
        if isinstance(db_path_or_engine, Engine):
            self._session = Session(bind=db_path_or_engine, expire_on_commit=False)
        elif db_path_or_engine is None:
            from ... import config
            url = config.get_settings().DATABASE_URL
            target: str | None
            if url and "://" in url and not url.startswith("sqlite:///"):
                target = url
            else:
                from project_workflow.infrastructure import db
                target = str(getattr(db, "DB_PATH", ""))
            if not target:
                target = None
            self._session = get_session(target)
        else:
            self._session = get_session(db_path_or_engine)
        self._init_repositories()

    def _init_repositories(self) -> None:
        self._workflows: SAWorkflowRepository = SAWorkflowRepository(self._session)
        self._phases: SAPhaseRepository = SAPhaseRepository(self._session)
        self._instructions: SAInstructionRepository = SAInstructionRepository(self._session)
        self._checks: SACheckRepository = SACheckRepository(self._session)
        self._evidence: SAEvidenceRepository = SAEvidenceRepository(self._session)
        self._projects: SAProjectRepository = SAProjectRepository(self._session)
        self._tasks: SATaskRepository = SATaskRepository(self._session)
        self._agents: SAAgentRepository = SAAgentRepository(self._session)
        self._supervisor_runs: SASupervisorRunRepository = SASupervisorRunRepository(self._session)
        self._cli_history: SACLIHistoryRepository = SACLIHistoryRepository(self._session)

    def clone(self) -> "SAUnitOfWork":
        """Return a new UoW bound to the same database URL."""
        return SAUnitOfWork()

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Literal[False]:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        return False

    def close(self) -> None:
        """Close the underlying session — call once the UoW is no longer needed."""
        self._session.close()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    @property
    def workflows(self) -> WorkflowRepository:
        return self._workflows

    @property
    def phases(self) -> PhaseRepository:
        return self._phases

    @property
    def projects(self) -> ProjectRepository:
        return self._projects

    @property
    def tasks(self) -> TaskRepository:
        return self._tasks

    @property
    def agents(self) -> AgentRepository:
        return self._agents

    @property
    def supervisor_runs(self) -> SupervisorRunRepository:
        return self._supervisor_runs

    @property
    def instructions(self) -> InstructionRepository:
        return self._instructions

    @property
    def checks(self) -> CheckRepository:
        return self._checks

    @property
    def evidence(self) -> EvidenceRepository:
        return self._evidence

    @property
    def cli_history(self) -> SACLIHistoryRepository:
        return self._cli_history

    # Compatibility aliases used by legacy tests and WizardEngine internals.
    def is_empty(self) -> bool:
        """Return True when no workflows/projects/tasks exist."""
        from project_workflow.infrastructure.db import models as m
        return (
            self._session.execute(select(m.Workflow)).scalar_one_or_none() is None
            and self._session.execute(select(m.Project)).scalar_one_or_none() is None
            and self._session.execute(select(m.Task)).scalar_one_or_none() is None
        )

    def add_task_history(self, task_id: int, phase_id: int | str, status: str) -> None:
        self.tasks.add_history(task_id, int(phase_id), status)
        self.commit()

    def get_phase_instructions(self, token: Any) -> list[Any]:
        phase = self.get_phase(token)
        if phase is None:
            return []
        phase_id = phase["id"] if isinstance(phase, dict) else getattr(phase, "id", None)
        if phase_id is None:
            return []
        return list(self.instructions.list(int(phase_id)))

    def create_supervisor_run(self, *args: Any, **kwargs: Any) -> int:
        if args and isinstance(args[0], dict) and not kwargs:
            kwargs = args[0]
        return self.supervisor_runs.create(kwargs)

    def create_phase(self, *args: Any, **kwargs: Any) -> int:
        from project_workflow.application.phase import PhaseServiceApp
        if args and isinstance(args[0], dict) and not kwargs:
            kwargs = args[0]
        data = dict(kwargs)
        if "agent_id" in data and isinstance(data["agent_id"], dict):
            data["agent_id"] = data["agent_id"].get("id")
        if "workflow_id" not in data or data["workflow_id"] is None:
            default_wf = self.workflows.ensure_default_exists()
            data["workflow_id"] = default_wf.id if default_wf else None
        if "code" not in data:
            data["code"] = str(data.get("id")) if data.get("id") is not None else str(data.get("phase_order", "0"))
        result = PhaseServiceApp(self).create_phase(data)
        return result["id"]

    def create_instruction(self, *args: Any, **kwargs: Any) -> int:
        if args and isinstance(args[0], dict) and not kwargs:
            kwargs = args[0]
        data = dict(kwargs)
        phase_id = data.pop("phase_id")
        if isinstance(phase_id, str):
            phase = self.phases.get_by_code(phase_id)
            phase_id = phase.id if phase else None
        if phase_id is None:
            raise RuntimeError("create_instruction requires phase_id")
        return self.instructions.create(int(phase_id), data)

    def create_check(self, *args: Any, **kwargs: Any) -> int:
        if args and isinstance(args[0], dict) and not kwargs:
            kwargs = args[0]
        data = dict(kwargs)
        phase_id = data.pop("phase_id")
        if isinstance(phase_id, str):
            phase = self.phases.get_by_code(phase_id)
            phase_id = phase.id if phase else None
        if phase_id is None:
            raise RuntimeError("create_check requires phase_id")
        return self.checks.create(int(phase_id), data)

    def create_evidence(self, *args: Any, **kwargs: Any) -> int:
        if args and isinstance(args[0], dict) and not kwargs:
            kwargs = args[0]
        data = dict(kwargs)
        phase_id = data.pop("phase_id")
        if isinstance(phase_id, str):
            phase = self.phases.get_by_code(phase_id)
            phase_id = phase.id if phase else None
        if phase_id is None:
            raise RuntimeError("create_evidence requires phase_id")
        return self.evidence.create(int(phase_id), data)

    def get_phase_by_id(self, phase_id: int) -> Any | None:
        row = self.phases.get_by_id(phase_id)
        return row.to_dict() if hasattr(row, "to_dict") else row

    def get_phase_by_code(self, code: str) -> Any | None:
        row = self.phases.get_by_code(code)
        return row.to_dict() if hasattr(row, "to_dict") else row

    def get_phase(self, token: Any) -> Any | None:
        """Legacy alias resolving a phase by id or code."""
        # Prefer numeric id lookup to avoid collisions with code strings like "3".
        numeric_id: int | None = None
        if isinstance(token, int):
            numeric_id = token
        elif isinstance(token, str) and token.isdigit():
            numeric_id = int(token)
        if numeric_id is not None:
            row = self.phases.get_by_id(numeric_id)
            if row is not None:
                return row.to_dict() if hasattr(row, "to_dict") else row
        row = self.phases.get_by_code(str(token))
        if row is None:
            try:
                row = self.phases.get_by_id(int(token))
            except (TypeError, ValueError):
                pass
        return row.to_dict() if hasattr(row, "to_dict") else row

    def get_task(self, task_id: int) -> Any | None:
        row = self.tasks.get_by_id(task_id)
        return row.to_dict() if hasattr(row, "to_dict") else row

    def get_task_by_key(self, key: str) -> Any | None:
        row = self.tasks.get_by_key(key)
        return row.to_dict() if hasattr(row, "to_dict") else row

    def update_task(self, task_id: int, data: dict[str, Any]) -> None:
        return self.tasks.update(task_id, data)

    def get_cli_history(self, limit: int = 200) -> list[dict[str, Any]]:
        return list(self.cli_history.list(limit))

    def log_cli_call(
        self,
        command: str,
        task_key: str | None = None,
        request: str | None = None,
        response: str | None = None,
    ) -> int:
        return self.cli_history.create(command, task_key, request, response)

    def import_phases(self, phases: list[dict[str, Any]]) -> None:
        default_wf = self.workflows.ensure_default_exists()
        workflow_id = default_wf.id if default_wf else None
        if workflow_id is None:
            raise RuntimeError("No default workflow available for import_phases")
        self._session.execute(
            text("DELETE FROM instructions WHERE phase_id IN (SELECT id FROM phases WHERE workflow_id = :wid)"),
            {"wid": workflow_id},
        )
        self._session.execute(
            text("DELETE FROM checks WHERE phase_id IN (SELECT id FROM phases WHERE workflow_id = :wid)"),
            {"wid": workflow_id},
        )
        self._session.execute(
            text("DELETE FROM evidence WHERE phase_id IN (SELECT id FROM phases WHERE workflow_id = :wid)"),
            {"wid": workflow_id},
        )
        self._session.execute(
            text("DELETE FROM phases WHERE workflow_id = :wid"),
            {"wid": workflow_id},
        )
        for order, phase in enumerate(phases, start=1):
            data = {
                "workflow_id": workflow_id,
                "code": str(phase.get("code", order)),
                "name": phase.get("name", f"Phase {order}"),
                "description": phase.get("description", ""),
                "phase_order": order,
                "next_recommendation": phase.get("next_recommendation", ""),
                "parallel_with": phase.get("parallel_with"),
                "rollback_target": phase.get("rollback_target"),
                "execution_type": phase.get("execution_type", "sync"),
                "is_seed_managed": phase.get("is_seed_managed", True),
            }
            phase_id = self.phases.create(data)
            for idx, instr in enumerate(phase.get("instructions", []), start=1):
                self.instructions.create(
                    int(phase_id),
                    {
                        "step_num": idx,
                        "description": instr.get("step", instr.get("description", "")),
                        "example": instr.get("example", ""),
                        "execution_type": instr.get("execution_type", "sync"),
                        "skills": instr.get("skills", []),
                    },
                )
            self.phases.set_checks(
                int(phase_id),
                [{"description": c.get("description", c.get("item", ""))} for c in phase.get("checks", [])],
            )
            self.phases.set_evidence(
                int(phase_id),
                [{"description": e.get("description", e.get("item", ""))} for e in phase.get("evidence", [])],
            )
        self.commit()

    def create_project(self, data: dict[str, Any]) -> dict[str, Any]:
        from project_workflow.application.project import ProjectService
        return ProjectService(self).create_project(data)

    def create_agent(self, data: dict[str, Any]) -> int:
        from project_workflow.application.agent import AgentService
        result = AgentService(self).create_agent(data)
        return result["id"]

    def create_workflow(self, data: dict[str, Any]) -> dict[str, Any]:
        from project_workflow.application.workflow import WorkflowService
        return WorkflowService(self).create_workflow(data)

    def delete_workflow(self, workflow_id: int) -> None:
        self.workflows.delete(workflow_id)

    def update_workflow(self, workflow_id: int, data: dict[str, Any]) -> None:
        self.workflows.update(workflow_id, data)

    def create_task(self, *args: Any, **kwargs: Any) -> int:
        from project_workflow.application.task import TaskService
        if args and isinstance(args[0], dict) and not kwargs:
            kwargs = args[0]
        data = dict(kwargs)
        if "project_id" in data and isinstance(data["project_id"], dict):
            data["project_id"] = data["project_id"].get("id")
        result = TaskService(self).create_task(data)
        return result["id"]

    def get_phases(self, workflow_id: int | None = None) -> list[Any]:
        if workflow_id is None:
            default_wf = self.workflows.ensure_default_exists()
            workflow_id = default_wf.id if default_wf else None
        rows = self.phases.list(workflow_id=workflow_id)
        return [r.to_dict() if hasattr(r, "to_dict") else r for r in rows]

    def get_projects(self) -> list[Any]:
        rows = self.projects.list()
        return [r.to_dict() if hasattr(r, "to_dict") else r for r in rows]

    def get_tasks(self) -> list[Any]:
        rows = self.tasks.list()
        return [r.to_dict() if hasattr(r, "to_dict") else r for r in rows]

    def get_agents(self) -> list[Any]:
        rows = self.agents.list()
        return [r.to_dict() if hasattr(r, "to_dict") else r for r in rows]

    def get_workflows(self) -> list[Any]:
        rows = self.workflows.list()
        return [r.to_dict() if hasattr(r, "to_dict") else r for r in rows]

    def list_phases(self, workflow_id: int | None = None) -> list[Any]:
        return self.get_phases(workflow_id)

    def list_projects(self) -> list[Any]:
        return self.get_projects()

    def list_tasks(self) -> list[Any]:
        return self.get_tasks()

    def list_agents(self) -> list[Any]:
        return self.get_agents()

    def list_workflows(self) -> list[Any]:
        return self.get_workflows()

    def get_task_history(self, task_id: int) -> list[dict[str, Any]]:
        return [r.to_dict() if hasattr(r, "to_dict") else r for r in self.tasks.get_history(task_id)]

    def get_supervisor_runs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [r.to_dict() if hasattr(r, "to_dict") else r for r in self.supervisor_runs.list(**kwargs)]

    def init(self) -> None:
        self.create_all()
        self._bootstrap_default_project()
        self._bootstrap_smoke_project_and_workflow()

    def _bootstrap_smoke_project_and_workflow(self) -> None:
        from project_workflow import config
        smoke_wf = self.workflows.get_by_name(config.SMOKE_WORKFLOW_NAME)
        if smoke_wf:
            smoke_wf_id = smoke_wf.id
        else:
            smoke_wf_id = self.workflows.create({
                "name": config.SMOKE_WORKFLOW_NAME,
                "description": "Smoke test workflow",
                "_skip_default_phase": True,
            })
        smoke_project = self.projects.get_by_code(config.SMOKE_PROJECT_CODE)
        if smoke_project is None:
            self.projects.create({
                "workflow_id": smoke_wf_id,
                "code": config.SMOKE_PROJECT_CODE,
                "name": config.SMOKE_PROJECT_NAME,
                "key_prefixes": list(config.SMOKE_TASK_KEY_PREFIXES),
                "workflow_name": config.SMOKE_WORKFLOW_NAME,
            })
        self.commit()
        self._ensure_smoke_phases()

    def _ensure_smoke_phases(self) -> None:
        from project_workflow.infrastructure.db import schema
        from project_workflow import config
        smoke_wf = self.workflows.get_by_name(config.SMOKE_WORKFLOW_NAME)
        if not smoke_wf:
            return
        smoke_phases = list(self.phases.list(workflow_id=smoke_wf.id))
        if smoke_phases:
            return
        seed_phases = schema.load_phases_from_seed(config.SMOKE_SEED_PATH)
        # Ensure agents referenced by selected_agent exist first.
        for phase in seed_phases:
            agent_name = phase.delegate.agent if phase.delegate else ""
            if agent_name and not self.agents.get_by_name(agent_name):
                self.agents.create({"name": agent_name, "description": f"Smoke seed agent for {phase.code}"})
        self.commit()
        for order, phase in enumerate(seed_phases, start=1):
            data = {
                "workflow_id": smoke_wf.id,
                "code": phase.code,
                "name": phase.name,
                "description": phase.description,
                "min_time_min": phase.min_time_min,
                "phase_order": order,
                "next_recommendation": phase.next_recommendation,
                "parallel_with": phase.parallel_with,
                "rollback_target": phase.rollback_target,
                "execution_type": phase.execution_type,
                "is_seed_managed": True,
            }
            if phase.delegate:
                agent = self.agents.get_by_name(phase.delegate.agent)
                if agent:
                    data["agent_id"] = agent.id
            phase_id = self.phases.create(data)
            for idx, instr in enumerate(phase.instructions, start=1):
                self.instructions.create(
                    int(phase_id),
                    {
                        "step_num": idx,
                        "description": instr.step,
                        "example": instr.example,
                        "execution_type": instr.execution_type,
                        "skills": instr.skills,
                    },
                )
            self.phases.set_checks(
                int(phase_id),
                [{"description": c.description} for c in phase.checks],
            )
            self.phases.set_evidence(
                int(phase_id),
                [{"description": e.item} for e in phase.evidence],
            )
        self.commit()

    def _bootstrap_default_project(self) -> None:
        from project_workflow import config
        code = "TASK"
        if self.get_project_by_code(code) is None:
            default_wf = self.workflows.ensure_default_exists()
            self.projects.create({
                "workflow_id": default_wf.id,
                "code": code,
                "name": "Default Project",
                "key_prefixes": list(config.DEFAULT_TASK_KEY_PREFIXES),
            })
            self.commit()

    def get_default_workflow(self) -> Any | None:
        row = self.workflows.ensure_default_exists()
        return row.to_dict() if hasattr(row, "to_dict") else row

    def delete_phase(self, token: int | str) -> None:
        phase_id: int | None = None
        if isinstance(token, str):
            phase = self.phases.get_by_code(token)
            phase_id = phase.id if phase else None
        else:
            phase_id = token
        if phase_id is None:
            raise NotFoundError(f"Phase {token} not found")
        self.phases.delete(int(phase_id))

    def get_project_by_code(self, code: str) -> Any | None:
        row = self.projects.get_by_code(code)
        if row is None:
            return None
        return row.to_dict() if hasattr(row, "to_dict") else row

    def sanitize_runtime_state(self) -> None:
        """Remove known test residue and deduplicate agents."""
        # Remove test projects by known prefixes
        for project in self.projects.list():
            code = project.code
            if code in ("UITEST",):
                pid = project.id
                if pid is None:
                    continue
                self._session.execute(
                    text("DELETE FROM task_history WHERE task_id IN (SELECT id FROM tasks WHERE project_id = :pid)"),
                    {"pid": pid},
                )
                self._session.execute(
                    text("DELETE FROM supervisor_runs WHERE task_id IN (SELECT id FROM tasks WHERE project_id = :pid)"),
                    {"pid": pid},
                )
                self._session.execute(
                    text("DELETE FROM tasks WHERE project_id = :pid"),
                    {"pid": pid},
                )
                self.projects.delete(int(pid))

        # Dedupe agents by name
        agents = list(self.agents.list())
        seen: dict[str, int] = {}
        for agent in agents:
            aid = agent.id
            if aid is None:
                continue
            if agent.name in seen:
                self.agents.delete(int(aid))
            else:
                seen[agent.name] = int(aid)

        self._session.commit()

    def create_all(self) -> None:
        """Create schema (dev/test helper)."""
        bind = self._session.bind
        if bind is None:
            raise RuntimeError("Session has no engine bound")
        Base.metadata.create_all(bind)
        return None
