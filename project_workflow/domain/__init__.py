"""Domain layer — business entities and value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from project_workflow.domain.project_theme import DEFAULT_PROJECT_COLOR, DEFAULT_PROJECT_ICON


@dataclass(frozen=True)
class TaskKey:
    """Validated task key with prefix and number."""

    raw: str
    prefix: str
    number: int

    def __str__(self) -> str:
        return self.raw


@dataclass(frozen=True)
class PhaseCode:
    """Semantic phase code, e.g. '1.INTAKE' or '10.REVIEW'."""

    value: str

    def __str__(self) -> str:
        return self.value


@dataclass
class Phase:
    """Domain phase."""

    id: int | None = None
    workflow_id: int | None = None
    code: str = ""
    name: str = ""
    description: str | None = ""
    phase_order: int = 0
    agent_id: int | None = None
    parallel_with_phase_id: int | None = None
    rollback_target_phase_id: int | None = None
    execution_type: str = "sync"
    workflow_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "phase_order": self.phase_order,
            "agent_id": self.agent_id,
            "parallel_with_phase_id": self.parallel_with_phase_id,
            "rollback_target_phase_id": self.rollback_target_phase_id,
            "execution_type": self.execution_type,
            "workflow_name": self.workflow_name,
        }


@dataclass
class Agent:
    """Domain agent."""

    id: int | None = None
    name: str = ""
    description: str = ""
    hermes_profile: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "hermes_profile": self.hermes_profile,
        }


@dataclass
class Workflow:
    """Domain workflow template."""

    id: int | None = None
    name: str = ""
    description: str = ""
    is_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_default": self.is_default,
        }


@dataclass
class Project:
    """Domain project instance with task key prefixes and UI branding."""

    id: int | None = None
    workflow_id: int = 0
    code: str = ""
    name: str = ""
    description: str = ""
    theme_icon: str = DEFAULT_PROJECT_ICON
    theme_color: str = DEFAULT_PROJECT_COLOR
    key_prefixes: list[str] = field(default_factory=list)
    workflow_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "theme_icon": self.theme_icon,
            "theme_color": self.theme_color,
            "key_prefixes": self.key_prefixes,
            "workflow_name": self.workflow_name,
        }


@dataclass
class Task:
    """Domain task."""

    id: int | None = None
    project_id: int = 0
    workflow_id: int = 0
    task_key: str = ""
    title: str = ""
    description: str = ""
    current_phase_id: int = 0
    current_phase_code: str = ""
    current_phase_name: str = ""
    status: str = "active"
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "workflow_id": self.workflow_id,
            "task_key": self.task_key,
            "title": self.title,
            "description": self.description,
            "current_phase_id": self.current_phase_id,
            "current_phase_code": self.current_phase_code,
            "current_phase_name": self.current_phase_name,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class TaskStepHistoryEntry:
    """One persisted evaluation produced by the CLI ``step`` flow."""

    id: int | None = None
    task_id: int = 0
    phase_id: int = 0
    verdict: str = ""
    worker_report: str = ""
    covered_item_ids: list[str] = field(default_factory=list)
    missing_item_ids: list[str] = field(default_factory=list)
    blocker_messages: list[str] = field(default_factory=list)
    next_phase_id: int | None = None
    rollback_phase_id: int | None = None
    replay_fingerprint: str | None = None
    evaluation_snapshot: dict[str, Any] = field(default_factory=dict)
    supervisor_response: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "phase_id": self.phase_id,
            "verdict": self.verdict,
            "worker_report": self.worker_report,
            "covered_item_ids": self.covered_item_ids,
            "missing_item_ids": self.missing_item_ids,
            "blocker_messages": self.blocker_messages,
            "next_phase_id": self.next_phase_id,
            "rollback_phase_id": self.rollback_phase_id,
            "replay_fingerprint": self.replay_fingerprint,
            "evaluation_snapshot": self.evaluation_snapshot,
            "supervisor_response": self.supervisor_response,
            "created_at": self.created_at,
        }


@dataclass
class TaskPhaseEvent:
    """One append-only task phase/status event."""

    id: int | None = None
    task_id: int = 0
    phase_id: int = 0
    step_history_id: int | None = None
    event_type: str = ""
    occurred_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "phase_id": self.phase_id,
            "step_history_id": self.step_history_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
        }
