"""Infrastructure persistence layer — SQLAlchemy DB adapters and repositories."""
from __future__ import annotations

from pathlib import Path

from .compat import WorkflowDBCompat as WorkflowDB

# Legacy module-level DB path — tests monkeypatch this attribute.
DB_PATH = Path.home() / ".project-workflow" / "workflow.db"

from .models import (
    Agent,
    Check,
    Evidence,
    Instruction,
    Phase,
    Project,
    SupervisorRun,
    Task,
    Workflow,
)
from .repositories import (
    AgentRepository,
    InstructionRepository,
    PhaseRepository,
    ProjectRepository,
    SupervisorRunRepository,
    TaskRepository,
    WorkflowRepository,
)
from .session import ensure_schema, get_engine
from .uow import SAUnitOfWork

__all__ = [
    "Agent",
    "AgentRepository",
    "Check",
    "Evidence",
    "Instruction",
    "InstructionRepository",
    "Phase",
    "PhaseRepository",
    "Project",
    "ProjectRepository",
    "SAUnitOfWork",
    "SupervisorRun",
    "SupervisorRunRepository",
    "Task",
    "TaskRepository",
    "Workflow",
    "WorkflowDB",
    "WorkflowRepository",
    "ensure_schema",
    "get_engine",
]
