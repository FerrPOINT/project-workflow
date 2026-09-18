"""Tests for interfaces.ui.app FastAPI wiring."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from project_workflow.application.state import _AppState
from project_workflow.interfaces.ui.app import _health, create_app


def test_health_ok():
    with patch("project_workflow.interfaces.ui.app.get_engine") as mock_engine:
        conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__.return_value = conn
        response = asyncio.run(_health())
        assert response.status_code == 200
        body = response.body
        assert b'"ok":true' in body


def test_create_app_routes():
    app = create_app()
    routes = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/health" in routes
    assert "/" in routes
    assert "/api/phases" in routes


def test_request_logging_middleware():
    app = create_app()
    client = TestClient(app)
    with patch("project_workflow.interfaces.ui.app.logger") as mock_logger:
        # Health endpoint hits DB, mock engine to avoid real DB.
        with patch("project_workflow.interfaces.ui.app.get_engine") as mock_engine:
            conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__.return_value = conn
            response = client.get("/health")
            assert response.status_code == 200
            # Logging middleware should have logged the request.
            assert mock_logger.info.called


def test_api_phases_reuses_and_closes_one_request_uow():
    """A request must not exhaust a size-one PostgreSQL connection pool."""
    state = _AppState("sqlite:///:memory:")
    uow = MagicMock()

    workflow = MagicMock()
    workflow.to_dict.return_value = {"id": 1, "name": "Workflow"}
    mode = MagicMock(id=1)
    phase = MagicMock()
    phase.to_dict.return_value = {
        "id": 1,
        "name": "Phase",
        "workflow_id": 1,
        "mode_id": 1,
        "phase_order": 1,
        "agent_id": 1,
    }
    agent = MagicMock()
    agent.to_dict.return_value = {"id": 1, "name": "Agent"}

    uow.workflows.list.return_value = [workflow]
    uow.workflow_modes.get_by_key.return_value = mode
    uow.phases.list.return_value = [phase]
    uow.agents.list.return_value = [agent]

    app = create_app()
    with (
        patch("project_workflow.application.state._app_state", state),
        patch.object(_AppState, "get_uow", autospec=True, return_value=uow) as get_uow,
        TestClient(app) as client,
    ):
        response = client.get("/api/phases?workflow_id=1")

    assert response.status_code == 200
    assert response.json()["phases"][0]["agent_name"] == "Agent"
    get_uow.assert_called_once_with(state)
    uow.close.assert_called_once_with()


def test_request_uow_rolls_back_and_closes_on_error():
    state = _AppState("sqlite:///:memory:")
    uow = MagicMock()

    with patch.object(_AppState, "get_uow", autospec=True, return_value=uow):
        with pytest.raises(RuntimeError, match="boom"):
            with state.request_scope():
                state.workflow_service()
                raise RuntimeError("boom")

    uow.rollback.assert_called_once_with()
    uow.close.assert_called_once_with()


def test_request_without_database_work_does_not_create_uow():
    state = _AppState("sqlite:///:memory:")

    with patch.object(_AppState, "get_uow", autospec=True) as get_uow:
        with state.request_scope():
            pass

    get_uow.assert_not_called()
