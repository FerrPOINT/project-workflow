"""Database connection / session factory.

Deterministic default path next to the package, overridable via WORKFLOW_DB_PATH.
"""
from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .models import Base

_pkg_dir = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = Path(
    os.getenv("WORKFLOW_DB_PATH", str(_pkg_dir / "data" / "workflow.db"))
)

_engine = None
_SessionLocal = None


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA temp_store = MEMORY")
    cursor.execute("PRAGMA cache_size = -32000")
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


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


def ensure_migrated(engine: Engine | None = None) -> None:
    """Apply Alembic migrations to bring schema to head."""
    engine = engine or get_engine()
    db_path = str(engine.url.database)
    here = Path(__file__).resolve().parent.parent.parent.parent
    alembic_cfg = Config(str(here / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "head")


def ensure_schema(engine: Engine | None = None) -> None:
    """Create all tables from ORM models (fallback for tests / fresh DBs)."""
    engine = engine or get_engine()
    Base.metadata.create_all(engine)
