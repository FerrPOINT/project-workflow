"""Global mutable application state holder for the UI.

Kept in its own tiny module so every UI sub-module can share the same
instance.  Tests monkeypatch ``project_workflow.interfaces.ui._app_state``; because the
symbol is defined here, the patch reaches all consumers.
"""

from __future__ import annotations

from ...application.state import _AppState
from ...application import state as _app_state_module


class _AppStateProxy:
    """Dynamic proxy to the canonical ``_app_state`` in ``project_workflow.application.state``.

    This lets UI tests monkeypatch a single SQLite-backed state without every
    UI submodule having cached the original PostgreSQL instance at import time.
    """

    def __getattr__(self, name: str) -> object:
        return getattr(_app_state_module._app_state, name)

    def __repr__(self) -> str:
        return f"<_AppStateProxy target={_app_state_module._app_state!r}>"


_app_state: _AppState = _AppStateProxy()  # type: ignore[assignment]

__all__ = ["_AppState", "_app_state"]
