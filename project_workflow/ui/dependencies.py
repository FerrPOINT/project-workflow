"""Application state and dependency injection for the UI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import schema
from ..application import (
    AgentService,
    PhaseServiceApp,
    ProjectService,
    TaskService,
    WorkflowService,
)
from ..config import get_settings
from ..infrastructure.db.uow import SAUnitOfWork

if TYPE_CHECKING:
    from .compat import WorkflowDBCompat


class _AppState:
    """Application state holder (replaces module-level globals)."""

    __slots__ = ("_db", "_srv", "_uow", "_catalog_ensured", "_database_url")

    def __init__(self, database_url: str | None = None) -> None:
        self._db: "WorkflowDBCompat" | None = None
        self._srv: Any | None = None  # legacy PhaseService wrapper
        self._uow: SAUnitOfWork | None = None
        self._catalog_ensured: bool = False
        self._database_url: str = database_url or get_settings().DATABASE_URL

    def get_db(self) -> "WorkflowDBCompat":
        from .compat import WorkflowDBCompat

        if self._db is None:
            self._db = WorkflowDBCompat()
        # Always re-ensure default workflows so runtime mutations (renamed workflows,
        # missing default flag) are repaired on the next request.
        with self._db._conn() as conn:
            self._db._ensure_default_workflows(conn)
            conn.commit()
        if not self._catalog_ensured:
            schema.ensure_phase_catalog(self._db)
            self._catalog_ensured = True
        return self._db

    def reset(self) -> None:
        self._db = None
        self._srv = None
        self._uow = None
        self._catalog_ensured = False

    def get_service(self) -> Any:
        """Return the legacy raw-SQLite PhaseService used by detail/edit routes."""
        if self._srv is None:
            from ..service import PhaseService

            self._srv = PhaseService(self.get_db())
        return self._srv

    def get_uow(self) -> SAUnitOfWork:
        from ..infrastructure.db.session import ensure_schema, get_engine

        target = self._database_url
        if target.startswith("sqlite:///"):
            target = str(Path(target[10:]).resolve())
            target = f"sqlite:///{target}"
        engine = get_engine(target)
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

    @property
    def db(self) -> "WorkflowDBCompat" | None:
        return self._db


# Global instance is intentionally NOT created here; see ``project_workflow.ui.state``.
