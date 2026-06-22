"""WorkflowDB package — legacy-compatible handle.

Re-exports the SQLAlchemy-backed compatibility adapter from
project_workflow.infrastructure.db.compat so existing import paths keep
working. New code should import from project_workflow.infrastructure.db.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from project_workflow.infrastructure.db.compat import WorkflowDBCompat as WorkflowDB


def __getattr__(name: str) -> Any:
    if name == "DB_PATH":
        from project_workflow import config

        url = config.get_settings().DATABASE_URL
        if url.startswith("sqlite:///"):
            return Path(url.replace("sqlite:///", ""))
        return Path(url)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["WorkflowDB", "DB_PATH"]
