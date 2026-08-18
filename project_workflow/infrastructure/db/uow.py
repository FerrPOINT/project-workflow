"""SQLAlchemy Unit of Work."""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

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
    SAEvidenceRepository,
    SAInstructionRepository,
    SAPhaseRepository,
    SAProjectRepository,
    SASupervisorRunRepository,
    SATaskRepository,
    SAWorkflowRepository,
)
from project_workflow.infrastructure.db.session import get_session

from .row_utils import row_to_dict, rows_to_dicts


class SAUnitOfWork(UnitOfWork):
    """SQLAlchemy session-based unit of work."""

    def __init__(self, db_path_or_engine: str | Engine | None = None):
        if isinstance(db_path_or_engine, Engine):
            self._session = Session(bind=db_path_or_engine, expire_on_commit=False)
        elif db_path_or_engine is None:
            from ... import config

            url = config.get_settings().DATABASE_URL
            target: str | None
            if url and "://" in url:
                target = url
            else:
                from project_workflow.infrastructure import db

                target = str(getattr(db, "get_db_path", lambda: getattr(db, "DB_PATH", ""))())
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

    def __enter__(self) -> SAUnitOfWork:
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
    def session(self) -> Session:
        return self._session

    def add_task_history(self, task_id: int, phase_id: int | str, status: str) -> None:
        self.tasks.add_history(task_id, int(phase_id), status)
        self.commit()

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

    def get_phase_by_code(self, code: str) -> Any | None:
        return row_to_dict(self.phases.get_by_code(code))

    def get_phase(self, token: Any) -> Any | None:
        """Resolve a phase by id or code."""
        numeric_id: int | None = None
        if isinstance(token, int):
            numeric_id = token
        elif isinstance(token, str) and token.isdigit():
            numeric_id = int(token)
        if numeric_id is not None:
            row = self.phases.get_by_id(numeric_id)
            if row is not None:
                return row_to_dict(row)
        row = self.phases.get_by_code(str(token))
        if row is None:
            try:
                row = self.phases.get_by_id(int(token))
            except (TypeError, ValueError):
                pass
        return row_to_dict(row)

    def get_task(self, task_id: int) -> Any | None:
        return row_to_dict(self.tasks.get_by_id(task_id))

    def get_task_by_key(self, key: str) -> Any | None:
        return row_to_dict(self.tasks.get_by_key(key))

    def update_task(self, task_id: int, data: dict[str, Any]) -> None:
        return self.tasks.update(task_id, data)

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
        return rows_to_dicts(self.phases.list(workflow_id=workflow_id))

    def get_all_phases(self) -> list[Any]:
        """Return phases across every workflow (used by dashboard aggregation)."""
        return rows_to_dicts(self.phases.list())

    def get_projects(self) -> list[Any]:
        return rows_to_dicts(self.projects.list())

    def get_tasks(self) -> list[Any]:
        return rows_to_dicts(self.tasks.list())

    def get_agents(self) -> list[Any]:
        return rows_to_dicts(self.agents.list())

    def get_workflows(self) -> list[Any]:
        return rows_to_dicts(self.workflows.list())

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
        return rows_to_dicts(self.tasks.get_history(task_id))

    def get_supervisor_runs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return rows_to_dicts(self.supervisor_runs.list(**kwargs))

    def init(self) -> None:
        self.create_all()
        self._bootstrap_default_project()
        self._bootstrap_smoke_project_and_workflow()

    def _bootstrap_smoke_project_and_workflow(self) -> None:
        from .uow_bootstrap import bootstrap_smoke_project_and_workflow
        bootstrap_smoke_project_and_workflow(self)

    def _ensure_smoke_phases(self) -> None:
        from .uow_bootstrap import ensure_smoke_phases
        ensure_smoke_phases(self)

    def _bootstrap_default_project(self) -> None:
        from .uow_bootstrap import bootstrap_default_project
        bootstrap_default_project(self)

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

    def create_all(self) -> None:
        """Create schema (dev/test helper)."""
        bind = self._session.bind
        if bind is None:
            raise RuntimeError("Session has no engine bound")
        # For PostgreSQL make sure the target schema exists and search_path
        # is set before creating tables.
        from .session import ensure_schema

        ensure_schema(bind)
        Base.metadata.create_all(bind)
        return None
