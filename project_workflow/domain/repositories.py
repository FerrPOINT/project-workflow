"""Repository interfaces (ports)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, List, Literal, Sequence

from project_workflow.domain import Agent, Phase, Project, SupervisorRun, Task, Workflow


class WorkflowRepository(ABC):
    """Persistence contract for workflows."""

    @abstractmethod
    def list(self) -> Sequence[Workflow]: ...

    @abstractmethod
    def get_by_id(self, workflow_id: int) -> Workflow | None: ...

    @abstractmethod
    def get_by_name(self, name: str) -> Workflow | None: ...

    @abstractmethod
    def get_default(self) -> Workflow | None: ...

    @abstractmethod
    def create(self, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def update(self, workflow_id: int, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def delete(self, workflow_id: int) -> None: ...

    @abstractmethod
    def ensure_default_exists(self, name: str = "Default Workflow") -> Workflow: ...


class PhaseRepository(ABC):
    """Persistence contract for phases."""

    @abstractmethod
    def list(self, workflow_id: int | None = None) -> Sequence[Phase]: ...

    @abstractmethod
    def get_by_id(self, phase_id: int) -> Phase | None: ...

    @abstractmethod
    def get_by_code(self, code: str) -> Phase | None: ...

    @abstractmethod
    def create(self, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def update(self, phase_id: int, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def delete(self, phase_id: int) -> None: ...

    @abstractmethod
    def shift_orders(self, workflow_id: int, start_order: int, delta: int = 1) -> None: ...

    @abstractmethod
    def get_next_order(self, workflow_id: int) -> int: ...

    @abstractmethod
    def get_phases_for_workflow(self, workflow_id: int) -> Sequence[Phase]: ...

    @abstractmethod
    def get_checks(self, phase_id: int) -> Sequence[dict[str, Any]]: ...

    @abstractmethod
    def get_evidence(self, phase_id: int) -> Sequence[dict[str, Any]]: ...

    @abstractmethod
    def set_checks(self, phase_id: int, items: list[dict[str, Any]]) -> None: ...

    @abstractmethod
    def set_evidence(self, phase_id: int, items: list[dict[str, Any]]) -> None: ...


class InstructionRepository(ABC):
    """Persistence contract for phase instructions."""

    @abstractmethod
    def list(self, phase_id: int) -> Sequence[dict[str, Any]]: ...

    @abstractmethod
    def get_by_id(self, instruction_id: int) -> dict[str, Any] | None: ...

    @abstractmethod
    def create(self, phase_id: int, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def update(self, instruction_id: int, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def delete(self, instruction_id: int) -> None: ...

    @abstractmethod
    def delete_for_phase(self, phase_id: int) -> None: ...

    @abstractmethod
    def reorder(self, phase_id: int, orders: List[tuple[int, int]]) -> None: ...


class ProjectRepository(ABC):
    """Persistence contract for projects."""

    @abstractmethod
    def list(self) -> Sequence[Project]: ...

    @abstractmethod
    def get_by_id(self, project_id: int) -> Project | None: ...

    @abstractmethod
    def get_by_code(self, code: str) -> Project | None: ...

    @abstractmethod
    def create(self, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def update(self, project_id: int, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def delete(self, project_id: int) -> None: ...

    @abstractmethod
    def match_by_task_key(self, task_key: str) -> Project | None: ...


class TaskRepository(ABC):
    """Persistence contract for tasks."""

    @abstractmethod
    def list(self) -> Sequence[Task]: ...

    @abstractmethod
    def get_by_id(self, task_id: int) -> Task | None: ...

    @abstractmethod
    def get_by_key(self, task_key: str) -> Task | None: ...

    @abstractmethod
    def create(self, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def update(self, task_id: int, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def add_history(self, task_id: int, phase_id: int, status: str) -> None: ...

    @abstractmethod
    def get_history(self, task_id: int) -> Sequence[dict[str, Any]]: ...


class AgentRepository(ABC):
    """Persistence contract for agents."""

    @abstractmethod
    def list(self) -> Sequence[Agent]: ...

    @abstractmethod
    def get_by_id(self, agent_id: int) -> Agent | None: ...

    @abstractmethod
    def create(self, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def update(self, agent_id: int, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def delete(self, agent_id: int) -> None: ...


class SupervisorRunRepository(ABC):
    """Persistence contract for supervisor runs."""

    @abstractmethod
    def list(
        self,
        task_id: int | None = None,
        task_key: str | None = None,
        limit: int = 200,
    ) -> Sequence[SupervisorRun]: ...

    @abstractmethod
    def create(self, data: dict[str, Any]) -> int: ...


class CheckRepository(ABC):
    """Persistence contract for phase checks."""

    @abstractmethod
    def list(self, phase_id: int) -> Sequence[dict[str, Any]]: ...

    @abstractmethod
    def create(self, phase_id: int, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def delete_for_phase(self, phase_id: int) -> None: ...


class EvidenceRepository(ABC):
    """Persistence contract for phase evidence."""

    @abstractmethod
    def list(self, phase_id: int) -> Sequence[dict[str, Any]]: ...

    @abstractmethod
    def create(self, phase_id: int, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def delete_for_phase(self, phase_id: int) -> None: ...


class UnitOfWork(ABC):
    """Transaction boundary."""

    @abstractmethod
    def __enter__(self) -> UnitOfWork: ...

    @abstractmethod
    def __exit__(self, exc_type, exc_val, exc_tb) -> Literal[False]: ...

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def rollback(self) -> None: ...

    @property
    @abstractmethod
    def workflows(self) -> WorkflowRepository: ...

    @property
    @abstractmethod
    def phases(self) -> PhaseRepository: ...

    @property
    @abstractmethod
    def projects(self) -> ProjectRepository: ...

    @property
    @abstractmethod
    def tasks(self) -> TaskRepository: ...

    @property
    @abstractmethod
    def agents(self) -> AgentRepository: ...

    @property
    @abstractmethod
    def supervisor_runs(self) -> SupervisorRunRepository: ...

    @property
    @abstractmethod
    def instructions(self) -> InstructionRepository: ...

    @property
    @abstractmethod
    def checks(self) -> CheckRepository: ...

    @property
    @abstractmethod
    def evidence(self) -> EvidenceRepository: ...

    # Legacy compatibility aliases used by WizardEngine while tests migrate.
    # TODO: remove once all WizardEngine internals and tests use repositories.
    @abstractmethod
    def add_task_history(self, task_id: int, phase_id: int, status: str) -> None: ...

    @abstractmethod
    def update_task(self, task_id: int, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def create_supervisor_run(self, **kwargs: Any) -> int: ...

    @abstractmethod
    def create_phase(self, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def get_task(self, task_id: int) -> Task | None: ...

    @abstractmethod
    def get_task_by_key(self, key: str) -> Task | None: ...

    @abstractmethod
    def get_phase_by_code(self, code: str) -> Phase | None: ...

    @abstractmethod
    def get_phase_by_id(self, phase_id: int) -> Phase | None: ...
