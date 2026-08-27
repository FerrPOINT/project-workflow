"""Tests for interfaces.ui.main entry point."""

from __future__ import annotations

import importlib
from unittest.mock import patch

ui_main = importlib.import_module("project_workflow.interfaces.ui.main")


def test_main_defaults(monkeypatch):
    from project_workflow.config import get_settings

    monkeypatch.delenv("UI_HOST", raising=False)
    monkeypatch.delenv("UI_PORT", raising=False)
    get_settings.cache_clear()
    try:
        with patch.object(ui_main, "uvicorn") as mock_uvicorn:
            with patch("sys.argv", ["ui"]):
                ui_main.main()
        args = mock_uvicorn.run.call_args.kwargs
        assert args["host"] == "127.0.0.1"
        assert args["port"] == 8811
        assert args["log_level"] == "info"
    finally:
        get_settings.cache_clear()


def test_main_custom_args():
    with patch.object(ui_main, "uvicorn") as mock_uvicorn:
        with patch("sys.argv", ["ui", "--port", "9999", "--host", "127.0.0.1"]):
            ui_main.main()
    args = mock_uvicorn.run.call_args.kwargs
    assert args["host"] == "127.0.0.1"
    assert args["port"] == 9999
