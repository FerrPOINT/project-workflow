"""Database connection / session factory.

Supports both PostgreSQL (runtime) and SQLite (tests/fallback).
The DSN is read from config.Settings.DATABASE_URL.
"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from project_workflow.config import get_settings

from .models import Base

_engine = None
_SessionLocal = None


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite://")


def _get_default_sqlite_url() -> str:
    pkg_dir = Path(__file__).resolve().parent.parent.parent
    return f"sqlite:///{pkg_dir / 'data' / 'workflow.db'}"


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    # Only applies to SQLite connections
    try:
        cursor = dbapi_conn.cursor()
    except AttributeError:
        return
    try:
        cursor.execute("SELECT 1 FROM sqlite_master LIMIT 1")
    except Exception:
        return
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA temp_store = MEMORY")
    cursor.execute("PRAGMA cache_size = -32000")
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def get_database_url() -> str:
    url = get_settings().DATABASE_URL
    if not url:
        return _get_default_sqlite_url()
    if "://" in url:
        return url
    if Path(url).suffix == ".db":
        return f"sqlite:///{url}"
    return url


def _normalize_url(url: str | None) -> str:
    if not url:
        return get_database_url()
    if "://" in url:
        return url
    if Path(url).suffix == ".db":
        return f"sqlite:///{url}"
    return url


def get_engine(url: str | None = None) -> Engine:
    """Return a cached or newly created SQLAlchemy engine."""
    global _engine
    target = _normalize_url(url)
    normalized_target = str(target)
    if _engine is None or str(_engine.url) != normalized_target:
        if _is_sqlite(target):
            db_path = target.replace("sqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            _engine = create_engine(
                target,
                connect_args={"check_same_thread": False},
                echo=False,
            )
        else:
            # PostgreSQL
            connect_args = {}
            schema = get_settings().DB_SCHEMA
            if schema:
                connect_args["options"] = f"-csearch_path={schema}"
            _engine = create_engine(
                target,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                connect_args=connect_args,
                echo=False,
            )
    return _engine


def get_sessionmaker(url: str | None = None) -> sessionmaker:
    """Return a sessionmaker bound to the given (or default) DB URL."""
    engine = get_engine(url)
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(url: str | None = None):
    """Return a new SQLAlchemy Session."""
    return get_sessionmaker(url)()


def reset_engine() -> None:
    """Reset cached engine; useful in tests after monkeypatching DB path."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None


def ensure_schema(engine: Engine | None = None) -> None:
    """Create all tables from ORM models (fallback for tests / fresh DBs)."""
    engine = engine or get_engine()
    Base.metadata.create_all(engine)


def run_alembic_command(cmd: str, engine: Engine | None = None) -> None:
    """Run an Alembic command using the configured engine."""
    engine = engine or get_engine()
    here = Path(__file__).resolve().parent.parent.parent.parent
    alembic_cfg = Config(str(here / "alembic.ini"))
    alembic_cfg.set_main_option("sqlalchemy.url", str(engine.url))
    getattr(command, cmd)(alembic_cfg, "head")


def ensure_migrated(engine: Engine | None = None) -> None:
    """Apply Alembic migrations to bring schema to head."""
    engine = engine or get_engine()
    if not _is_sqlite(str(engine.url)):
        schema = get_settings().DB_SCHEMA
        with engine.begin() as conn:
            conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    run_alembic_command("upgrade", engine)


def stamp_head(engine: Engine | None = None) -> None:
    """Stamp Alembic version table at head without running migrations."""
    engine = engine or get_engine()
    run_alembic_command("stamp", engine)
