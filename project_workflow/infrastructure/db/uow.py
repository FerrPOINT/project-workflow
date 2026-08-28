"""SQLAlchemy Unit of Work."""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from project_workflow.domain.repositories import (
    AgentRepository,
    PhaseCheckRepository,
    PhaseEvidenceRequirementRepository,
    PhaseInstructionRepository,
    PhaseRepository,
    ProjectRepository,
    TaskRepository,
    TaskStepHistoryRepository,
    UnitOfWork,
    WorkflowRepository,
)
from project_workflow.infrastructure.db.repositories import (
    SAAgentRepository,
    SAPhaseCheckRepository,
    SAPhaseEvidenceRequirementRepository,
    SAPhaseInstructionRepository,
    SAPhaseRepository,
    SAProjectRepository,
    SATaskRepository,
    SATaskStepHistoryRepository,
    SAWorkflowRepository,
)
from project_workflow.infrastructure.db.session import get_session


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
        self._phase_instructions = SAPhaseInstructionRepository(self._session)
        self._phase_checks = SAPhaseCheckRepository(self._session)
        self._phase_evidence_requirements = SAPhaseEvidenceRequirementRepository(self._session)
        self._projects: SAProjectRepository = SAProjectRepository(self._session)
        self._tasks: SATaskRepository = SATaskRepository(self._session)
        self._agents: SAAgentRepository = SAAgentRepository(self._session)
        self._step_history = SATaskStepHistoryRepository(self._session)

    def __enter__(self) -> SAUnitOfWork:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Literal[False]:
        try:
            if exc_type is not None:
                self.rollback()
            else:
                self.commit()
        finally:
            self.close()
        return False

    def close(self) -> None:
        """Close the underlying session — call once the UoW is no longer needed."""
        self._session.close()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def refresh(self) -> None:
        """Expire cached ORM rows so subsequent repository reads hit the database."""
        self._session.expire_all()

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
    def step_history(self) -> TaskStepHistoryRepository:
        return self._step_history

    @property
    def phase_instructions(self) -> PhaseInstructionRepository:
        return self._phase_instructions

    @property
    def phase_checks(self) -> PhaseCheckRepository:
        return self._phase_checks

    @property
    def phase_evidence_requirements(self) -> PhaseEvidenceRequirementRepository:
        return self._phase_evidence_requirements

    @property
    def session(self) -> Session:
        return self._session

    def record_step(self, **kwargs: Any) -> int:
        return self.step_history.create(kwargs)

    def get_task_by_key(
        self,
        key: str,
        workflow_id: int | None = None,
        project_id: int | None = None,
    ) -> dict[str, Any] | None:
        task = self.tasks.get_by_key(key, workflow_id=workflow_id, project_id=project_id)
        return task.to_dict() if task is not None else None

    def get_phases(self, workflow_id: int) -> list[dict[str, Any]]:
        if not isinstance(workflow_id, int) or isinstance(workflow_id, bool) or workflow_id <= 0:
            raise ValueError("workflow_id должен быть положительным целым числом")
        return [phase.to_dict() for phase in self.phases.list(workflow_id=workflow_id)]

    def get_projects(self) -> list[dict[str, Any]]:
        return [project.to_dict() for project in self.projects.list()]

    def get_tasks(self) -> list[dict[str, Any]]:
        return [task.to_dict() for task in self.tasks.list()]

    def get_agents(self) -> list[dict[str, Any]]:
        return [agent.to_dict() for agent in self.agents.list()]

    def get_workflows(self) -> list[dict[str, Any]]:
        return [workflow.to_dict() for workflow in self.workflows.list()]

    def list_phase_events(self, task_id: int) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.tasks.list_phase_events(task_id)]

    def list_phase_events_batch(self, task_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        return {
            task_id: [event.to_dict() for event in events]
            for task_id, events in self.tasks.list_phase_events_batch(task_ids).items()
        }

    def list_step_history(self, **kwargs: Any) -> list[dict[str, Any]]:
        return [entry.to_dict() for entry in self.step_history.list(**kwargs)]
