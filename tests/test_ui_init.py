"""Tests for interfaces.ui.__getattr__ lazy resolver."""

from __future__ import annotations

from project_workflow.interfaces.ui import _app_state


def test_app_state_export():
    # _app_state is a dynamic proxy that delegates to the canonical _AppState instance.
    from project_workflow.application.state import _app_state as core_app_state
    from project_workflow.application.state import _AppState
    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    assert callable(getattr(_app_state, "get_uow"))
    assert isinstance(_app_state.get_uow(), SAUnitOfWork)
    assert isinstance(core_app_state, _AppState)
    # Proxy itself is not an _AppState, but it behaves like one at runtime.
    assert not isinstance(_app_state, _AppState)
