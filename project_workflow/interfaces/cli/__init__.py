"""project-workflow CLI — thin entrypoint."""

from __future__ import annotations

# Import the only supported controller commands.
from . import v2 as v2
from .core import cli


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
