"""Tests for interfaces.ui.main entry point."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

ui_main = importlib.import_module("project_workflow.interfaces.ui.main")


def test_main_defaults():
    mock_uow = MagicMock()
    mock_state = MagicMock()
    mock_state.get_uow.return_value = mock_uow
    with patch.object(ui_main, "uvicorn") as mock_uvicorn:
        with patch("sys.argv", ["ui"]):
            with patch("project_workflow.application.state._app_state", mock_state):
                ui_main.main()
    args = mock_uvicorn.run.call_args.kwargs
    assert args["host"] == "0.0.0.0"
    assert args["port"] == ui_main.DEFAULT_UI_PORT
    assert args["log_level"] == "info"
    mock_uow._bootstrap_smoke_project_and_workflow.assert_called_once()


def test_main_custom_args():
    mock_uow = MagicMock()
    mock_state = MagicMock()
    mock_state.get_uow.return_value = mock_uow
    with patch.object(ui_main, "uvicorn") as mock_uvicorn:
        with patch("sys.argv", ["ui", "--port", "9999", "--host", "127.0.0.1"]):
            with patch("project_workflow.application.state._app_state", mock_state):
                ui_main.main()
    args = mock_uvicorn.run.call_args.kwargs
    assert args["host"] == "127.0.0.1"
    assert args["port"] == 9999
    mock_uow._bootstrap_smoke_project_and_workflow.assert_called_once()


def test_managed_main_does_not_seed_smoke_workflow(monkeypatch):
    mock_uow = MagicMock()
    mock_state = MagicMock()
    mock_state.get_uow.return_value = mock_uow
    monkeypatch.setenv("PROJECT_WORKFLOW_MANAGED_CONFIGURATION", "1")
    with patch.object(ui_main, "uvicorn") as mock_uvicorn:
        with patch("sys.argv", ["ui"]):
            with patch("project_workflow.application.state._app_state", mock_state):
                ui_main.main()
    mock_uow._bootstrap_smoke_project_and_workflow.assert_not_called()
    mock_uow.close.assert_called_once()
    mock_uvicorn.run.assert_called_once()
