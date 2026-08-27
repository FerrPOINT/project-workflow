"""Repository interfaces (ports)."""

from __future__ import annotations

import builtins
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from project_workflow.domain import (
    Agent,
    Phase,
    Project,
    Task,
    TaskPhaseEvent,
    TaskStepHistoryEntry,
    Workflow,
)


class WorkflowRepository(ABC):
    """Persistence contract for workflows."""

    @abstractmethod
    def list(self) -> Sequence[Workflow]: ...

    @abstractmethod
    def get_by_id(self, workflow_id: int) -> Workflow | None: ...

    @abstractmethod
    def get_default(self) -> Workflow | None: ...

    @abstractmethod
    def lock(self, workflow_id: int) -> Workflow | None: ...

    @abstractmethod
    def create(self, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def update(self, workflow_id: int, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def delete(self, workflow_id: int) -> None: ...

    @abstractmethod
    def ensure_default_exists(self, name: str) -> Workflow: ...


class PhaseRepository(ABC):
    """Persistence contract for phases."""

    @abstractmethod
    def list(self, workflow_id: int | None = None) -> Sequence[Phase]: ...

    @abstractmethod
    def get_by_id(self, phase_id: int) -> Phase | None: ...

    @abstractmethod
    def get_by_code(self, workflow_id: int, code: str) -> Phase | None: ...

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
    def reference_kinds(self, phase_id: int) -> set[str]: ...

    @abstractmethod
    def has_agent_reference(self, agent_id: int) -> bool: ...

    @abstractmethod
    def workflow_ids_for_agent(self, agent_id: int) -> Sequence[int]: ...

    @abstractmethod
    def resequence(self, workflow_id: int) -> None: ...

    @abstractmethod
    def reorder(self, workflow_id: int, orders: Sequence[tuple[int, int]]) -> None: ...

    @abstractmethod
    def get_checks(self, phase_id: int) -> Sequence[dict[str, Any]]: ...

    @abstractmethod
    def get_evidence(self, phase_id: int) -> Sequence[dict[str, Any]]: ...

    @abstractmethod
    def set_checks(self, phase_id: int, items: builtins.list[dict[str, Any]]) -> None: ...

    @abstractmethod
    def set_evidence(self, phase_id: int, items: builtins.list[dict[str, Any]]) -> None: ...


class PhaseInstructionRepository(ABC):
    """Persistence contract for phase instructions."""

    @abstractmethod
    def list(self, phase_id: int) -> Sequence[dict[str, Any]]: ...

    @abstractmethod
    def list_for_phases(self, phase_ids: Sequence[int]) -> Mapping[int, Sequence[dict[str, Any]]]: ...

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
    def reorder(self, phase_id: int, orders: builtins.list[tuple[int, int]]) -> None: ...


class ProjectRepository(ABC):
    """Persistence contract for projects."""

    @abstractmethod
    def list(self) -> Sequence[Project]: ...

    @abstractmethod
    def get_by_id(self, project_id: int) -> Project | None: ...

    @abstractmethod
    def get_by_code(self, code: str) -> Project | None: ...

    @abstractmethod
    def lock(self, project_id: int) -> Project | None: ...

    @abstractmethod
    def lock_prefix_namespace(self) -> None: ...

    @abstractmethod
    def create(self, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def update(self, project_id: int, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def delete(self, project_id: int) -> None: ...


class TaskRepository(ABC):
    """Persistence contract for tasks."""

    @abstractmethod
    def list(self) -> Sequence[Task]: ...

    @abstractmethod
    def list_by_project(self, project_id: int) -> Sequence[Task]: ...

    @abstractmethod
    def get_by_id(self, task_id: int) -> Task | None: ...

    @abstractmethod
    def get_by_key(self, task_key: str) -> Task | None: ...

    @abstractmethod
    def lock(self, task_id: int) -> Task | None: ...

    @abstractmethod
    def create(self, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def update(self, task_id: int, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def update_if_state(
        self,
        task_id: int,
        expected_phase_id: int,
        expected_status: str,
        data: dict[str, Any],
    ) -> bool: ...

    @abstractmethod
    def record_phase_event(
        self,
        task_id: int,
        phase_id: int,
        event_type: str,
        step_history_id: int | None = None,
    ) -> None: ...

    @abstractmethod
    def list_phase_events(self, task_id: int) -> Sequence[TaskPhaseEvent]: ...

    @abstractmethod
    def list_phase_events_batch(self, task_ids: Sequence[int]) -> Mapping[int, Sequence[TaskPhaseEvent]]: ...

class AgentRepository(ABC):
    """Persistence contract for agents."""

    @abstractmethod
    def list(self) -> Sequence[Agent]: ...

    @abstractmethod
    def list_by_ids(self, agent_ids: Sequence[int]) -> Sequence[Agent]: ...

    @abstractmethod
    def get_by_id(self, agent_id: int) -> Agent | None: ...

    @abstractmethod
    def get_by_name(self, name: str) -> Agent | None: ...

    @abstractmethod
    def get_by_hermes_profile(self, profile: str) -> Agent | None: ...

    @abstractmethod
    def lock(self, agent_id: int) -> Agent | None: ...

    @abstractmethod
    def create(self, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def update(self, agent_id: int, data: dict[str, Any]) -> None: ...

    @abstractmethod
    def delete(self, agent_id: int) -> None: ...


class TaskStepHistoryRepository(ABC):
    """Persistence contract for evaluated CLI ``step`` records."""

    @abstractmethod
    def list(
        self,
        task_id: int | None = None,
        task_key: str | None = None,
        phase_id: int | None = None,
        limit: int | None = 200,
    ) -> Sequence[TaskStepHistoryEntry]: ...

    @abstractmethod
    def latest_for_tasks(self, task_ids: Sequence[int]) -> Sequence[TaskStepHistoryEntry]: ...

    @abstractmethod
    def get_by_fingerprint(
        self, task_id: int, phase_id: int, replay_fingerprint: str
    ) -> TaskStepHistoryEntry | None: ...

    @abstractmethod
    def create(self, data: dict[str, Any]) -> int: ...


class PhaseCheckRepository(ABC):
    """Persistence contract for phase checks."""

    @abstractmethod
    def list(self, phase_id: int) -> Sequence[dict[str, Any]]: ...

    @abstractmethod
    def list_for_phases(self, phase_ids: Sequence[int]) -> Mapping[int, Sequence[dict[str, Any]]]: ...

    @abstractmethod
    def create(self, phase_id: int, data: dict[str, Any]) -> int: ...

    @abstractmethod
    def delete_for_phase(self, phase_id: int) -> None: ...


class PhaseEvidenceRequirementRepository(ABC):
    """Persistence contract for phase evidence."""

    @abstractmethod
    def list(self, phase_id: int) -> Sequence[dict[str, Any]]: ...

    @abstractmethod
    def list_for_phases(self, phase_ids: Sequence[int]) -> Mapping[int, Sequence[dict[str, Any]]]: ...

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
    def step_history(self) -> TaskStepHistoryRepository: ...

    @property
    @abstractmethod
    def phase_instructions(self) -> PhaseInstructionRepository: ...

    @property
    @abstractmethod
    def phase_checks(self) -> PhaseCheckRepository: ...

    @property
    @abstractmethod
    def phase_evidence_requirements(self) -> PhaseEvidenceRequirementRepository: ...

    @abstractmethod
    def record_step(self, **kwargs: Any) -> int: ...

    @abstractmethod
    def get_task_by_key(self, key: str) -> dict[str, Any] | None: ...

