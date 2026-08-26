"""Tests for interfaces.ui.main entry point."""

from __future__ import annotations

import importlib
from unittest.mock import patch

ui_main = importlib.import_module("project_workflow.interfaces.ui.main")


def test_main_defaults():
    with patch.object(ui_main, "uvicorn") as mock_uvicorn:
        with patch("sys.argv", ["ui"]):
            ui_main.main()
    args = mock_uvicorn.run.call_args.kwargs
    assert args["host"] == "127.0.0.1"
    assert args["port"] == 8811
    assert args["log_level"] == "info"


def test_main_custom_args():
    with patch.object(ui_main, "uvicorn") as mock_uvicorn:
        with patch("sys.argv", ["ui", "--port", "9999", "--host", "127.0.0.1"]):
            ui_main.main()
    args = mock_uvicorn.run.call_args.kwargs
    assert args["host"] == "127.0.0.1"
    assert args["port"] == 9999
