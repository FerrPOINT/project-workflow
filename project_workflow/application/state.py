"""Shared application state holder for UI and CLI.

Replaces module-level globals and lives outside the UI package so the CLI
and seed loaders can reuse the same SQLAlchemy-backed services without
circular imports.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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
    WorkflowModeService,
    WorkflowService,
)

_MIGRATED_URLS: set[str] = set()


@dataclass
class _RequestUowScope:
    uow: SAUnitOfWork | None = None


class _AppState:
    """Application state holder (replaces module-level globals)."""

    __slots__ = ("_database_url", "_request_uow_scope")

    def __init__(self, database_url: str | None = None) -> None:
        self._database_url: str = database_url or get_settings().DATABASE_URL
        self._request_uow_scope: ContextVar[_RequestUowScope | None] = ContextVar(
            f"project_workflow_request_uow_{id(self)}", default=None
        )

    def _database_url_normalized(self) -> str:
        target = self._database_url
        if target.startswith("sqlite:///"):
            target = Path(target[10:]).resolve().as_posix()
            target = f"sqlite:///{target}"
        return target

    def get_db(self) -> SAUnitOfWork:
        """Return the request-scoped UI UnitOfWork when available."""
        return self._service_uow()

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

        if os.environ.get("PROJECT_WORKFLOW_MANAGED_CONFIGURATION") != "1":
            schema.ensure_phase_catalog(uow)
        return uow

    @contextmanager
    def request_scope(self) -> Iterator[None]:
        """Share one lazily-created UoW across UI services in a request."""
        current = self._request_uow_scope.get()
        if current is not None:
            yield
            return

        scope = _RequestUowScope()
        token = self._request_uow_scope.set(scope)
        try:
            yield
        except BaseException:
            if scope.uow is not None:
                scope.uow.rollback()
            raise
        finally:
            if scope.uow is not None:
                scope.uow.close()
            self._request_uow_scope.reset(token)

    def _service_uow(self) -> SAUnitOfWork:
        scope = self._request_uow_scope.get()
        if scope is None:
            return self.get_uow()
        if scope.uow is None:
            scope.uow = self.get_uow()
        return scope.uow

    def workflow_service(self) -> WorkflowService:
        return WorkflowService(self._service_uow())

    def workflow_mode_service(self) -> WorkflowModeService:
        return WorkflowModeService(self._service_uow())

    def phase_service(self) -> PhaseServiceApp:
        return PhaseServiceApp(self._service_uow())

    def project_service(self) -> ProjectService:
        return ProjectService(self._service_uow())

    def task_service(self) -> TaskService:
        return TaskService(self._service_uow())

    def agent_service(self) -> AgentService:
        return AgentService(self._service_uow())

    def instruction_service(self) -> InstructionService:
        return InstructionService(self._service_uow())

    @property
    def db(self) -> Any | None:
        return None


_app_state = _AppState()
__all__ = ["_AppState", "_app_state"]
