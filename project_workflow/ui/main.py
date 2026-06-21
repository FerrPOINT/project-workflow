"""UI entry point."""

from __future__ import annotations

import argparse

import uvicorn

from .. import config
from .app import app


DEFAULT_UI_PORT = config.UI_PORT


def main() -> None:
    parser = argparse.ArgumentParser(description="project-workflow UI")
    parser.add_argument("--port", type=int, default=DEFAULT_UI_PORT, help="Port (default: %(default)s)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: %(default)s)")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
