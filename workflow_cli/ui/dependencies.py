"""Application state and dependency injection for the UI."""

from __future__ import annotations

from typing import Any

from .. import db, schema
from ..application import (
    AgentService,
    PhaseServiceApp,
    ProjectService,
    TaskService,
    WorkflowService,
)
from ..infrastructure.db.session import ensure_schema, get_engine
from ..infrastructure.db.uow import SAUnitOfWork


class _AppState:
    """Application state holder (replaces module-level globals)."""

    __slots__ = ("_db", "_srv", "_uow", "_catalog_ensured")

    def __init__(self) -> None:
        self._db: db.WorkflowDB | None = None
        self._srv: Any | None = None  # legacy PhaseService wrapper
        self._uow: SAUnitOfWork | None = None
        self._catalog_ensured: bool = False

    def get_db(self) -> db.WorkflowDB:
        if self._db is None:
            self._db = db.WorkflowDB()
            self._db.init()
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
        if self._uow is None:
            engine = get_engine(str(db.DB_PATH))
            ensure_schema(engine)
            self._uow = SAUnitOfWork(engine)
        return self._uow

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
    def db(self) -> db.WorkflowDB | None:
        return self._db


# Global instance is intentionally NOT created here; see ``workflow_cli.ui.state``.
