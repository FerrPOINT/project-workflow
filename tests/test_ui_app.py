"""Tests for interfaces.ui.app FastAPI wiring."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from project_workflow.interfaces.ui.app import _health, create_app


def test_health_ok():
    with patch("project_workflow.infrastructure.db.session.get_engine") as mock_engine, patch(
        "project_workflow.infrastructure.db.session.schema_is_ready", return_value=True
    ):
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
        with patch("project_workflow.infrastructure.db.session.get_engine") as mock_engine, patch(
            "project_workflow.infrastructure.db.session.schema_is_ready", return_value=True
        ):
            conn = MagicMock()
            mock_engine.return_value.connect.return_value.__enter__.return_value = conn
            response = client.get("/health")
            assert response.status_code == 200
            # Logging middleware should have logged the request.
            assert mock_logger.info.called
