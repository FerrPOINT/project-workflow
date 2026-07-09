"""Shared application state holder for UI and CLI.

Replaces module-level globals and lives outside the UI package so the CLI
and seed loaders can reuse the same SQLAlchemy-backed services without
circular imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..application.phase_service import PhaseService
from ..config import get_settings
from ..infrastructure.db.session import ensure_migrated, ensure_schema, get_engine
from ..infrastructure.db.uow import SAUnitOfWork
from . import (
    AgentService,
    InstructionService,
    PhaseServiceApp,
    ProjectService,
    TaskService,
    WorkflowService,
)

_MIGRATED_URLS: set[str] = set()


class _AppState:
    """Application state holder (replaces module-level globals)."""

    __slots__ = ("_database_url",)

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url: str = database_url or get_settings().DATABASE_URL

    def _database_url_normalized(self) -> str:
        target = self._database_url
        if target.startswith("sqlite:///"):
            target = str(Path(target[10:]).resolve())
            target = f"sqlite:///{target}"
        return target

    def get_db(self) -> SAUnitOfWork:
        """Return a fresh SQLAlchemy UnitOfWork and ensure seed catalog is loaded."""
        return self.get_uow()

    def reset(self) -> None:
        from ..infrastructure.db import schema

        schema.mark_catalog_not_ensured(self._database_url_normalized())
        _MIGRATED_URLS.discard(self._database_url_normalized())

    def get_service(self) -> PhaseService:
        """PhaseService helper for UI detail/edit routes."""
        return PhaseService(self)

    def get_uow(self) -> SAUnitOfWork:
        engine = get_engine(self._database_url_normalized())
        url = self._database_url_normalized()
        if engine.dialect.name == "sqlite":
            ensure_schema(engine)
        elif url not in _MIGRATED_URLS:
            ensure_migrated(engine)
            _MIGRATED_URLS.add(url)
        uow = SAUnitOfWork(engine)
        from ..infrastructure.db import schema

        schema.ensure_phase_catalog(uow)
        return uow

    def workflow_service(self) -> WorkflowService:
        return WorkflowService(self.get_uow())

    def phase_service(self) -> PhaseServiceApp:
        return PhaseServiceApp(self.get_uow())

    def project_service(self) -> ProjectService:
        return ProjectService(self.get_uow())

    def task_service(self) -> TaskService:
        return TaskService(self.get_uow())

    def agent_service(self) -> AgentService:
        return AgentService(self.get_uow())

    def instruction_service(self) -> InstructionService:
        return InstructionService(self.get_uow())

    @property
    def db(self) -> Any | None:
        return None


_app_state = _AppState()
__all__ = ["_AppState", "_app_state"]
