"""WARTZ Workflow CLI — thin entrypoint."""

from __future__ import annotations

from .core import cli

# ── Import command modules (registers subcommands) ─────
from . import ui         # noqa: E402,F401


def main() -> None:
    cli()

if __name__ == "__main__":
    main()
