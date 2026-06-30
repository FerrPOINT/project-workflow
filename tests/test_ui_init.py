"""Tests for interfaces.ui.__getattr__ lazy resolver."""
from __future__ import annotations

from project_workflow.interfaces.ui import _app_state


def test_app_state_export():
    # _app_state is resolved lazily via __getattr__ and should be an _AppState instance.
    from project_workflow.interfaces.ui.dependencies import _AppState
    assert isinstance(_app_state, _AppState)
