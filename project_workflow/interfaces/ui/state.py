"""Global mutable application state holder for the UI.

Kept in its own tiny module so every UI sub-module can share the same
instance.  Tests monkeypatch ``project_workflow.interfaces.ui._app_state``; because the
symbol is defined here, the patch reaches all consumers.
"""

from __future__ import annotations

from .dependencies import _AppState
from ...application.state import _app_state

__all__ = ["_AppState", "_app_state"]
