"""UI entry point."""

from __future__ import annotations

import argparse

import uvicorn

from project_workflow.config import get_settings
from project_workflow.interfaces.ui.app import app


DEFAULT_UI_PORT = get_settings().UI_PORT


def main() -> None:
    parser = argparse.ArgumentParser(description="project-workflow UI")
    parser.add_argument("--port", type=int, default=DEFAULT_UI_PORT, help="Port (default: %(default)s)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: %(default)s)")
    args = parser.parse_args()
    from project_workflow.application.state import _app_state
    uow = _app_state.get_uow()
    try:
        uow._bootstrap_smoke_project_and_workflow()
    finally:
        uow.close()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
