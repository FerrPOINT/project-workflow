"""Compatibility entrypoint for `python -m project_workflow.cli`."""

from __future__ import annotations

from project_workflow.interfaces.cli import main

if __name__ == "__main__":
    main()
