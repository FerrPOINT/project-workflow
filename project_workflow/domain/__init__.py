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
    mode_id: int | None = None
    mode_key: str | None = None
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
            "mode_id": self.mode_id,
            "mode_key": self.mode_key,
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
    modes: list[WorkflowMode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_default": self.is_default,
            "modes": [mode.to_dict() for mode in self.modes],
        }


@dataclass
class WorkflowMode:
    """Execution mode catalog owned by one workflow."""

    id: int | None = None
    workflow_id: int | None = None
    key: str = "default"
    name: str = "Default"
    mode_order: int = 1
    role_key: str | None = None
    execution_scope: str | None = None
    tech_workspace_policy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "key": self.key,
            "name": self.name,
            "mode_order": self.mode_order,
            "role_key": self.role_key,
            "execution_scope": self.execution_scope,
            "tech_workspace_policy": self.tech_workspace_policy,
        }


@dataclass
class Project:
    """Domain namespace stored in the legacy projects table."""

    id: int | None = None
    workflow_id: int = 0
    code: str = ""
    name: str = ""
    description: str = ""
    theme_icon: str = DEFAULT_PROJECT_ICON
    theme_color: str = DEFAULT_PROJECT_COLOR
    cli_command: str = ""
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
            "cli_command": self.cli_command,
            "key_prefixes": self.key_prefixes,
            "workflow_name": self.workflow_name,
        }


@dataclass
class Task:
    """Domain task."""

    id: int | None = None
    project_id: int = 0
    workflow_id: int = 0
    mode_id: int = 0
    mode_key: str = "default"
    cycle_number: int = 0
    assignment_operation_key: str | None = None
    assignment_revision: int = 0
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
            "mode_id": self.mode_id,
            "mode_key": self.mode_key,
            "cycle_number": self.cycle_number,
            "assignment_operation_key": self.assignment_operation_key,
            "assignment_revision": self.assignment_revision,
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


@dataclass(frozen=True)
class TaskRuntimeAssignment:
    """Immutable adapter acceptance record for one Business operation key."""

    id: int | None = None
    operation_key: str = ""
    task_id: int = 0
    project_id: int = 0
    workflow_id: int = 0
    mode_id: int = 0
    mode_key: str = "default"
    cycle_number: int = 0
    assignment_revision: int = 0
    role_key: str | None = None
    execution_scope: str | None = None
    business_task_ref: str | None = None
    root_task_ref: str | None = None
    work_item_ref: str | None = None
    task_workspace_ref: str | None = None
    tech_execution_workspace_ref: str | None = None
    tech_execution_attempt_ref: str | None = None
    decomposition_revision_ref: str | None = None
    stage_revision: str | None = None
    assignment_ref: str | None = None
    binding_ref: str | None = None
    hermes_run_ref: str | None = None
    workspace_generation: int | None = None
    lease_generation: int | None = None
    exact_input_refs: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "operation_key": self.operation_key,
            "task_id": self.task_id,
            "project_id": self.project_id,
            "workflow_id": self.workflow_id,
            "mode_id": self.mode_id,
            "mode_key": self.mode_key,
            "cycle_number": self.cycle_number,
            "assignment_revision": self.assignment_revision,
            "role_key": self.role_key,
            "execution_scope": self.execution_scope,
            "business_task_ref": self.business_task_ref,
            "root_task_ref": self.root_task_ref,
            "work_item_ref": self.work_item_ref,
            "task_workspace_ref": self.task_workspace_ref,
            "tech_execution_workspace_ref": self.tech_execution_workspace_ref,
            "tech_execution_attempt_ref": self.tech_execution_attempt_ref,
            "decomposition_revision_ref": self.decomposition_revision_ref,
            "stage_revision": self.stage_revision,
            "assignment_ref": self.assignment_ref,
            "binding_ref": self.binding_ref,
            "hermes_run_ref": self.hermes_run_ref,
            "workspace_generation": self.workspace_generation,
            "lease_generation": self.lease_generation,
            "exact_input_refs": [dict(item) for item in self.exact_input_refs],
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }


@dataclass
class TaskStepHistoryEntry:
    """One persisted evaluation produced by the CLI ``step`` flow."""

    id: int | None = None
    task_id: int = 0
    workflow_id: int = 0
    mode_id: int = 0
    mode_key: str = "default"
    cycle_number: int = 0
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
            "workflow_id": self.workflow_id,
            "mode_id": self.mode_id,
            "mode_key": self.mode_key,
            "cycle_number": self.cycle_number,
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
    workflow_id: int = 0
    mode_id: int = 0
    mode_key: str = "default"
    cycle_number: int = 0
    phase_id: int = 0
    step_history_id: int | None = None
    event_type: str = ""
    occurred_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "workflow_id": self.workflow_id,
            "mode_id": self.mode_id,
            "mode_key": self.mode_key,
            "cycle_number": self.cycle_number,
            "phase_id": self.phase_id,
            "step_history_id": self.step_history_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
        }
