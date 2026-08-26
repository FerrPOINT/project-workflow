"""Infrastructure persistence layer — SQLAlchemy DB adapters and repositories."""

from __future__ import annotations

from .models import Base
from .repositories import (
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
from .session import get_engine, get_session
from .uow import SAUnitOfWork, UnitOfWork

__all__ = [
    "Base",
    "SAAgentRepository",
    "SAPhaseCheckRepository",
    "SAPhaseEvidenceRequirementRepository",
    "SAPhaseInstructionRepository",
    "SAPhaseRepository",
    "SAProjectRepository",
    "SATaskStepHistoryRepository",
    "SATaskRepository",
    "SAWorkflowRepository",
    "get_engine",
    "get_session",
    "SAUnitOfWork",
    "UnitOfWork",
]
