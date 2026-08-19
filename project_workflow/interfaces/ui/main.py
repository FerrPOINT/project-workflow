"""UI entry point."""

from __future__ import annotations

import argparse

import uvicorn

from project_workflow.config import get_settings
from project_workflow.interfaces.ui.app import app


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="project-workflow UI")
    parser.add_argument("--port", type=int, default=settings.UI_PORT, help="Port (default: %(default)s)")
    parser.add_argument("--host", default=settings.UI_HOST, help="Host (default: %(default)s)")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
