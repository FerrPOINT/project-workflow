"""project-workflow CLI — thin entrypoint."""

from __future__ import annotations

# ── Import command modules (registers subcommands) ─────
from . import ui as ui
from .core import cli


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
