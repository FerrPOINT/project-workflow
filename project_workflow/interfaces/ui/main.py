"""UI entry point."""

from __future__ import annotations

import argparse
from ipaddress import ip_address

import uvicorn

from project_workflow.config import get_settings
from project_workflow.interfaces.ui.app import app


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="project-workflow UI")
    parser.add_argument("--port", type=int, default=settings.UI_PORT, help="Port (default: %(default)s)")
    parser.add_argument("--host", default=settings.UI_HOST, help="Host (default: %(default)s)")
    args = parser.parse_args()
    if settings.PROJECT_WORKFLOW_MODE == "standalone" and not settings.PROJECT_WORKFLOW_STANDALONE_CONTAINER_NETWORK:
        try:
            local_bind = args.host == "localhost" or ip_address(args.host).is_loopback
        except ValueError:
            local_bind = False
        if not local_bind:
            parser.error("Standalone direct execution requires a loopback bind")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", proxy_headers=False)


if __name__ == "__main__":
    main()
