"""SQLAlchemy Unit of Work."""
from __future__ import annotations

from workflow_cli.domain.repositories import (
    AgentRepository,
    PhaseRepository,
    ProjectRepository,
    SupervisorRunRepository,
    TaskRepository,
    UnitOfWork,
    WorkflowRepository,
)
from workflow_cli.infrastructure.db.models import Base
from workflow_cli.infrastructure.db.repositories import (
    SAAgentRepository,
    SAPhaseRepository,
    SAProjectRepository,
    SASupervisorRunRepository,
    SATaskRepository,
    SAWorkflowRepository,
)
from workflow_cli.infrastructure.db.session import get_session


class SAUnitOfWork(UnitOfWork):
    """SQLAlchemy session-based unit of work."""

    def __init__(self, db_path: str | None = None):
        self._session = get_session(db_path)
        self._workflows = SAWorkflowRepository(self._session)
        self._phases = SAPhaseRepository(self._session)
        self._projects = SAProjectRepository(self._session)
        self._tasks = SATaskRepository(self._session)
        self._agents = SAAgentRepository(self._session)
        self._supervisor_runs = SASupervisorRunRepository(self._session)

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        self._session.close()
        return False

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

    def create_all(self) -> None:
        """Create schema (dev/test helper)."""
        Base.metadata.create_all(self._session.bind)
