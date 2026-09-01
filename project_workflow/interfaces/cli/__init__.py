"""project-workflow CLI — thin entrypoint."""

from __future__ import annotations

import sys

# ── Import command modules (registers subcommands) ─────
from . import ui as ui
from .core import cli


def _configure_output_encoding() -> None:
    """Avoid UnicodeEncodeError when Click prints Russian help on narrow encodings."""
    sample = "Использование: Ошибка"
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or "utf-8"
        try:
            sample.encode(encoding)
        except (LookupError, UnicodeEncodeError):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _configure_output_encoding()
    cli()


if __name__ == "__main__":
    main()
