"""UI re-export of the shared SQLAlchemy-backed WorkflowDB compat shim.

The real implementation lives in ``project_workflow.infrastructure.db.compat`` so the CLI
and seed loaders can import ``WorkflowDB`` without pulling in the UI package.
"""
from __future__ import annotations

from ...application.state import _app_state
from ...infrastructure.db.compat import WorkflowDBCompat as _WorkflowDBCompat


class WorkflowDBCompat(_WorkflowDBCompat):
    """UI-specific shim that pins the global app state."""

    def __init__(self) -> None:  # noqa: D401
        super().__init__(_app_state)


__all__ = ["WorkflowDBCompat"]
