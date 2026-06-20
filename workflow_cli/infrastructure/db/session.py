"""Database connection / session factory.

Deterministic default path next to the package, overridable via WORKFLOW_DB_PATH.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_pkg_dir = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = Path(
    os.getenv("WORKFLOW_DB_PATH", str(_pkg_dir / "data" / "workflow.db"))
)

_engine = None
_SessionLocal = None


def get_engine(db_path: str | Path | None = None):
    """Return a cached or newly created SQLAlchemy engine for SQLite."""
    global _engine
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if _engine is None or str(_engine.url.database) != str(target):
        _engine = create_engine(
            f"sqlite:///{target}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
    return _engine


def get_sessionmaker(db_path: str | Path | None = None):
    """Return a sessionmaker bound to the given (or default) DB path."""
    engine = get_engine(db_path)
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(db_path: str | Path | None = None):
    """Return a new SQLAlchemy Session."""
    return get_sessionmaker(db_path)()


def reset_engine():
    """Reset cached engine; useful in tests after monkeypatching DB path."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None
