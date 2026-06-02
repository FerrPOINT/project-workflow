"""WARTZ Workflow CLI — thin entrypoint."""

from __future__ import annotations

from .core import cli

# ── Import command modules (registers subcommands) ─────
from . import init       # noqa: E402,F401
from . import phase      # noqa: E402,F401
from . import status     # noqa: E402,F401
from . import workflow   # noqa: E402,F401
from . import delegate   # noqa: E402,F401
from . import rollback   # noqa: E402,F401
from . import ui         # noqa: E402,F401


def main() -> None:
    cli()

if __name__ == "__main__":
    main()
