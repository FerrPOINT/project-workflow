"""Infrastructure persistence layer — SQLAlchemy DB adapters and repositories."""
from __future__ import annotations

from pathlib import Path
import os

from ... import config

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


def get_db_path() -> Path:
    """Resolve SQLite DB path from the current WORKFLOW_DIR environment variable.

    This is recomputed on every call so that changes to ``WORKFLOW_DIR`` are
    respected (important for CLI and tests). Falls back to the configured
    Settings value when the environment variable is not set.
    """
    workflow_dir = os.getenv("WORKFLOW_DIR") or config.get_settings().WORKFLOW_DIR
    return Path(workflow_dir) / "workflow.db"


# Kept for backwards compatibility with code that imports DB_PATH directly.
# Prefer :func:`get_db_path` when the environment may change between imports.
DB_PATH = get_db_path()

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
