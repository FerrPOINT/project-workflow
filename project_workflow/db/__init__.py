"""WorkflowDB package — legacy-compatible handle backed by SQLAlchemy.

This module lazily re-exports ``WorkflowDBCompat`` under the legacy ``WorkflowDB``
name so CLI, wizard and seed loaders can keep import paths unchanged.  It also
preserves the legacy ``DB_PATH`` knob used by tests to redirect a default
``WorkflowDB()`` instance to a temporary database.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def __getattr__(name: str) -> Any:
    if name == "WorkflowDB":
        from .compat import WorkflowDBCompat
        return WorkflowDBCompat
    if name == "base":
        # Legacy tests reach into ``project_workflow.db.DB_PATH``.
        return __import__(__name__, fromlist=[""])
    if name == "DB_PATH":
        from .. import config

        url = config.get_settings().DATABASE_URL
        if url.startswith("sqlite:///"):
            return Path(url.replace("sqlite:///", ""))
        return Path(url)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["WorkflowDB", "base", "DB_PATH"]
