"""Domain layer — business entities and value objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
    """Semantic phase code, e.g. '-1', '0.0a', '1'."""

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
    description: str = ""
    min_time_min: int = 0
    phase_order: int = 0
    agent_id: int | None = None
    next_recommendation: str = ""
    parallel_with: str | None = None
    rollback_target: str | None = None
    execution_type: str = "sync"
    is_seed_managed: bool = False
    workflow_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "min_time_min": self.min_time_min,
            "phase_order": self.phase_order,
            "agent_id": self.agent_id,
            "next_recommendation": self.next_recommendation,
            "parallel_with": self.parallel_with,
            "rollback_target": self.rollback_target,
            "execution_type": self.execution_type,
            "is_seed_managed": self.is_seed_managed,
            "workflow_name": self.workflow_name,
        }


@dataclass
class Agent:
    """Domain agent."""

    id: int | None = None
    name: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
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
    """Domain project with task key prefixes."""

    id: int | None = None
    workflow_id: int = 0
    code: str = ""
    name: str = ""
    key_prefixes: list[str] = field(default_factory=list)
    workflow_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "code": self.code,
            "name": self.name,
            "key_prefixes": self.key_prefixes,
            "workflow_name": self.workflow_name,
        }


@dataclass
class Task:
    """Domain task."""

    id: int | None = None
    project_id: int = 0
    task_key: str = ""
    title: str = ""
    description: str = ""
    current_phase: str = "-1"
    current_phase_name: str = ""
    status: str = "active"
    created_at: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "task_key": self.task_key,
            "title": self.title,
            "description": self.description,
            "current_phase": self.current_phase,
            "current_phase_name": self.current_phase_name,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class SupervisorRun:
    """Domain supervisor run."""

    id: int | None = None
    task_id: int = 0
    phase_id: int = 0
    verdict: str = ""
    report: str = ""
    covered: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_phase_id: int | None = None
    rollback_phase_id: int | None = None
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "phase_id": self.phase_id,
            "verdict": self.verdict,
            "report": self.report,
            "covered": self.covered,
            "missing": self.missing,
            "blockers": self.blockers,
            "next_phase_id": self.next_phase_id,
            "rollback_phase_id": self.rollback_phase_id,
            "context_snapshot": self.context_snapshot,
            "response": self.response,
            "created_at": self.created_at,
        }


@dataclass
class PhaseContent:
    """Instructions / checks / evidence for a phase."""

    instructions: list[dict[str, Any]] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
