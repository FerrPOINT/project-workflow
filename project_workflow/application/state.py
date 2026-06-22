"""Shared application state holder for UI and CLI.

Replaces module-level globals and lives outside the UI package so the CLI
and seed loaders can reuse the same SQLAlchemy-backed services without
circular imports.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import (
    AgentService,
    InstructionService,
    PhaseServiceApp,
    ProjectService,
    TaskService,
    WorkflowService,
)
from ..config import get_settings
from ..infrastructure.db.phase_service import PhaseService
from ..infrastructure.db.session import ensure_schema, get_engine
from ..infrastructure.db.uow import SAUnitOfWork


class _AppState:
    """Application state holder (replaces module-level globals)."""

    __slots__ = ("_db", "_srv", "_uow", "_catalog_ensured", "_database_url")

    def __init__(self, database_url: str | None = None) -> None:
        self._db: Any | None = None
        self._srv: Any | None = None  # PhaseService helper for UI detail/edit routes
        self._uow: SAUnitOfWork | None = None
        self._catalog_ensured: bool = False
        self._database_url: str = database_url or get_settings().DATABASE_URL

    def _database_url_normalized(self) -> str:
        target = self._database_url
        if target.startswith("sqlite:///"):
            target = str(Path(target[10:]).resolve())
            target = f"sqlite:///{target}"
        return target

    def get_db(self) -> SAUnitOfWork:
        """Return the SQLAlchemy UnitOfWork and ensure seed catalog is loaded."""
        if self._uow is None:
            engine = get_engine(self._database_url_normalized())
            if engine.dialect.name == "sqlite":
                ensure_schema(engine)
            self._uow = SAUnitOfWork(engine)
        if not self._catalog_ensured:
            from ..infrastructure.db import schema

            schema.ensure_phase_catalog(self._uow)
            self._catalog_ensured = True
        return self._uow

    def reset(self) -> None:
        if self._uow is not None:
            self._uow.close()
        self._db = None
        self._srv = None
        self._uow = None
        self._catalog_ensured = False

    def get_service(self) -> PhaseService:
        """PhaseService helper for UI detail/edit routes."""
        if self._srv is None:
            from ..infrastructure.db.phase_service import PhaseService

            self._srv = PhaseService(self.get_db())
        return self._srv

    def get_uow(self) -> SAUnitOfWork:
        engine = get_engine(self._database_url_normalized())
        if engine.dialect.name == "sqlite":
            ensure_schema(engine)
        return SAUnitOfWork(engine)

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
        return self._db

    @property
    def _database_url_public(self) -> str:
        return self._database_url


# Global shared instance.  Tests may monkeypatch this or create fresh instances.
_app_state = _AppState()

__all__ = ["_AppState", "_app_state"]
