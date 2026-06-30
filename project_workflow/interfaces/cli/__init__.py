"""project-workflow CLI — thin entrypoint."""

from __future__ import annotations

from .core import cli

# ── Import command modules (registers subcommands) ─────
from . import ui as ui


def main() -> None:
    cli()

if __name__ == "__main__":
    main()
