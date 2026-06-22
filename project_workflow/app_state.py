"""Compatibility shim: app_state moved to project_workflow.application.state."""
from __future__ import annotations

from project_workflow.application.state import _AppState, _app_state

__all__ = ["_AppState", "_app_state"]
