"""Application state and dependency injection for the UI.

The canonical ``_AppState`` implementation lives in ``project_workflow.application.state``
so it can be shared with the CLI and seed loaders without circular imports.
"""
from __future__ import annotations

from ...application.state import _AppState as _AppState, _app_state as _app_state

__all__ = ["_AppState", "_app_state"]
