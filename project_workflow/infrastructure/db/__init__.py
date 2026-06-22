"""Infrastructure persistence layer — SQLAlchemy DB adapters and repositories."""
from __future__ import annotations

from pathlib import Path

from ... import config

DB_PATH = Path(config.get_settings().WORKFLOW_DIR) / "workflow.db"

from .models import Base
from .repositories import (
    SAAgentRepository,
    SAInstructionRepository,
    SAPhaseRepository,
    SAProjectRepository,
    SASupervisorRunRepository,
    SATaskRepository,
    SAWorkflowRepository,
)
from .session import get_engine, get_session
from .uow import SAUnitOfWork, UnitOfWork

__all__ = [
    "Base",
    "DB_PATH",
    "SAAgentRepository",
    "SAInstructionRepository",
    "SAPhaseRepository",
    "SAProjectRepository",
    "SASupervisorRunRepository",
    "SATaskRepository",
    "SAWorkflowRepository",
    "get_engine",
    "get_session",
    "SAUnitOfWork",
    "UnitOfWork",
]
