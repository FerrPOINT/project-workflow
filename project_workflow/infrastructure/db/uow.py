"""SQLAlchemy Unit of Work."""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

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

    def __init__(self, db_path_or_engine: str | Engine | Connection | None = None):
        if isinstance(db_path_or_engine, (Engine, Connection)):
            self._session = Session(bind=db_path_or_engine, expire_on_commit=False)
        elif db_path_or_engine is None:
            self._session = get_session()
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

    def create_supervisor_run(self, *args: Any, **kwargs: Any) -> int:
        if args and isinstance(args[0], dict) and not kwargs:
            kwargs = args[0]
        return self.supervisor_runs.create(kwargs)

    def get_task_by_key(self, key: str) -> Any | None:
        return row_to_dict(self.tasks.get_by_key(key))

    def get_phases(self, workflow_id: int | None = None) -> list[Any]:
        if workflow_id is None:
            default_wf = self.workflows.get_default()
            if default_wf is None:
                return []
            workflow_id = default_wf.id
        return rows_to_dicts(self.phases.list(workflow_id=workflow_id))

    def get_projects(self) -> list[Any]:
        return rows_to_dicts(self.projects.list())

    def get_tasks(self) -> list[Any]:
        return rows_to_dicts(self.tasks.list())

    def get_agents(self) -> list[Any]:
        return rows_to_dicts(self.agents.list())

    def get_workflows(self) -> list[Any]:
        return rows_to_dicts(self.workflows.list())

    def get_task_history(self, task_id: int) -> list[dict[str, Any]]:
        return rows_to_dicts(self.tasks.get_history(task_id))

    def get_supervisor_runs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return rows_to_dicts(self.supervisor_runs.list(**kwargs))
