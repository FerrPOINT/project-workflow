"""WorkflowDB package — split from monolithic db.py.

Modules:
  base       — connection, serialization, hydration, resolve helpers, bootstrap, CRUD
"""
from .base import WorkflowDB, DB_PATH

__all__ = ["WorkflowDB", "DB_PATH"]
