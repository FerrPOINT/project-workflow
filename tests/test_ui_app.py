"""Tests for interfaces.ui.app FastAPI wiring."""

from __future__ import annotations

import asyncio
import importlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from project_workflow import config
from project_workflow.infrastructure.db.session import DatabaseUnavailable, reset_engine
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


def test_unknown_page_returns_html_error_template():
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/unknown-page")

    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "Страница не найдена" in response.text
    assert "К дашборду" in response.text
    assert '"ok":false' not in response.text


def test_unknown_api_route_still_returns_json_error():
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/unknown-page")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"ok": False, "error": "Ресурс не найден"}


def test_request_logging_middleware():
    app = create_app()
    client = TestClient(app)
    app_module = importlib.import_module("project_workflow.interfaces.ui.app")
    with patch.object(app_module, "logger") as mock_logger:
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


def test_lifespan_hides_database_and_shutdown_exception_details():
    app = create_app()
    app_module = importlib.import_module("project_workflow.interfaces.ui.app")

    async def exercise_lifespan() -> None:
        with (
            patch.object(app_module, "get_engine", side_effect=RuntimeError("startup-secret-marker")),
            patch.object(app_module, "reset_engine", side_effect=RuntimeError("shutdown-secret-marker")),
            patch.object(app_module, "logger") as logger,
        ):
            async with app.router.lifespan_context(app):
                pass

        rendered_calls = str(logger.warning.call_args_list)
        assert "startup-secret-marker" not in rendered_calls
        assert "shutdown-secret-marker" not in rendered_calls
        logger.warning.assert_any_call("База данных недоступна при запуске приложения")
        logger.warning.assert_any_call("Не удалось освободить пул базы данных при остановке приложения")

    asyncio.run(exercise_lifespan())

    assert not hasattr(app.state, "startup_error")


def test_unmigrated_database_requests_return_sanitized_readiness_errors(tmp_path):
    from project_workflow.application import state as app_state

    reset_engine()
    app_state._app_state.__init__(database_url=f"sqlite:///{tmp_path / 'empty.db'}")  # type: ignore[misc]
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    try:
        api_response = client.get("/api/namespaces")
        page_response = client.get("/namespaces")
    finally:
        app_state._app_state.__init__(database_url=None)  # type: ignore[misc]
        reset_engine()

    assert api_response.status_code == 503
    assert api_response.json() == {
        "ok": False,
        "error": "База данных не готова",
        "error_code": "database-not-ready",
    }
    assert page_response.status_code == 503
    assert "База данных не готова" in page_response.text
    for leaked in ("SELECT", "sqlite", "OperationalError", "Traceback", "empty.db"):
        assert leaked not in api_response.text
        assert leaked not in page_response.text


def test_uow_creation_database_errors_return_sanitized_readiness_errors():
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    error = OperationalError("SELECT secret", {}, RuntimeError("dsn-secret"))

    with patch("project_workflow.application.state._AppState.create_uow", side_effect=error):
        api_response = client.get("/api/namespaces")
        page_response = client.get("/namespaces")

    assert api_response.status_code == 503
    assert api_response.json() == {
        "ok": False,
        "error": "База данных не готова",
        "error_code": "database-not-ready",
    }
    assert page_response.status_code == 503
    assert "База данных не готова" in page_response.text
    for leaked in ("SELECT", "OperationalError", "Traceback", "dsn-secret"):
        assert leaked not in api_response.text
        assert leaked not in page_response.text


def test_uow_creation_database_unavailable_returns_sanitized_readiness_errors():
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    with patch("project_workflow.application.state._AppState.create_uow", side_effect=DatabaseUnavailable()):
        api_response = client.get("/api/namespaces")
        page_response = client.get("/namespaces")

    assert api_response.status_code == 503
    assert api_response.json()["error_code"] == "database-not-ready"
    assert page_response.status_code == 503
    assert "База данных не готова" in page_response.text
    assert "DATABASE_URL" not in api_response.text
    assert "DATABASE_URL" not in page_response.text


def test_uow_creation_config_validation_returns_sanitized_readiness_errors(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config.get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError) as exc_info:
            config.Settings(_env_file=None)  # type: ignore[call-arg]
    finally:
        config.get_settings.cache_clear()

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    with patch("project_workflow.application.state._AppState.create_uow", side_effect=exc_info.value):
        api_response = client.get("/api/namespaces")
        page_response = client.get("/namespaces")

    assert api_response.status_code == 503
    assert api_response.json() == {
        "ok": False,
        "error": "База данных не готова",
        "error_code": "database-not-ready",
    }
    assert page_response.status_code == 503
    assert "База данных не готова" in page_response.text
    for leaked in ("DATABASE_URL", "ValidationError", "Traceback", "Переменная DATABASE_URL обязательна"):
        assert leaked not in api_response.text
        assert leaked not in page_response.text
