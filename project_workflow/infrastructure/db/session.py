"""Database connection / session factory.

The DSN is read from config.Settings.DATABASE_URL.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from project_workflow.config import get_settings

from .models import Base

_engine = None
_SessionLocal = None


PG_CONNECT_RETRY_ATTEMPTS: int = 3
PG_CONNECT_RETRY_DELAY: float = 1.0


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite://")


def get_database_url() -> str:
    url = get_settings().DATABASE_URL
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set it to a PostgreSQL or SQLite DSN."
        )
    return url


def _normalize_url(url: str | None) -> str:
    if not url:
        return get_database_url()
    if "://" in url:
        return url
    if url == ":memory:" or url.startswith("/"):
        return f"sqlite:///{url}"
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
                connect_args={"check_same_thread": False, "timeout": 10},
                echo=False,
                poolclass=NullPool,
            )
        else:
            _engine = _create_postgres_engine(target)
    return _engine


def _create_postgres_engine(target: str) -> Engine:
    """Create a PostgreSQL engine with search_path and connection retry."""
    connect_args = {}
    schema = get_settings().DB_SCHEMA
    if schema:
        connect_args["options"] = f"-csearch_path={schema}"
    last_exc: Exception | None = None
    for attempt in range(PG_CONNECT_RETRY_ATTEMPTS):
        try:
            engine = create_engine(
                target,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                connect_args=connect_args,
                echo=False,
            )
            # Validate the engine can actually connect before returning it.
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return engine
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt + 1 < PG_CONNECT_RETRY_ATTEMPTS:
                time.sleep(PG_CONNECT_RETRY_DELAY)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Failed to create PostgreSQL engine")


def get_sessionmaker(url: str | None = None) -> sessionmaker[Any]:
    """Return a sessionmaker bound to the given (or default) DB URL."""
    engine = get_engine(url)
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(url: str | None = None) -> Session:
    """Return a new SQLAlchemy Session."""
    return get_sessionmaker(url)()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn: Any, connection_record: Any) -> None:
    """Apply performance and correctness pragmas to SQLite connections."""
    if getattr(connection_record, "dialect", None) is None or connection_record.dialect.name != "sqlite":
        return
    try:
        cursor = dbapi_conn.cursor()
    except AttributeError:
        return
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA synchronous = NORMAL")
    cursor.execute("PRAGMA temp_store = MEMORY")
    cursor.execute("PRAGMA cache_size = -32000")
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def reset_engine() -> None:
    """Reset cached engine; useful in tests after monkeypatching DB path."""
    global _engine, _SessionLocal
    _engine = None
    _SessionLocal = None


def ensure_schema(engine: Engine | Connection | None = None) -> None:
    """Create all tables from ORM models (fallback for tests / fresh DBs)."""
    target = engine or get_engine()
    dialect = target.dialect.name
    if isinstance(target, Connection):
        conn = target
        if dialect == "postgresql":
            schema = get_settings().DB_SCHEMA
            conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            conn.exec_driver_sql(f"SET search_path TO {schema}")
        Base.metadata.create_all(conn)
    else:
        with target.begin() as conn:
            if dialect == "postgresql":
                schema = get_settings().DB_SCHEMA
                conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
                conn.exec_driver_sql(f"SET search_path TO {schema}")
            Base.metadata.create_all(conn)


def run_alembic_command(cmd: str, engine: Engine | None = None) -> None:
    """Run an Alembic command using the configured engine."""
    engine = engine or get_engine()
    here = Path(__file__).resolve().parent.parent.parent.parent
    alembic_cfg = Config(str(here / "alembic.ini"))
    # Preserve the real password (str(URL) masks it) and escape percent signs
    # so configparser interpolation does not treat them as substitution syntax.
    url = engine.url.render_as_string(hide_password=False).replace("%", "%%")
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    getattr(command, cmd)(alembic_cfg, "head")
    # Alembic leaves the engine pool open; close it so migrations do not hold
    # connections that can block test database teardown.
    engine.dispose()


def ensure_migrated(engine: Engine | None = None) -> None:
    """Apply Alembic migrations to bring schema to head."""
    engine = engine or get_engine()
    if not _is_sqlite(str(engine.url)):
        schema = get_settings().DB_SCHEMA
        with engine.begin() as conn:
            conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    run_alembic_command("upgrade", engine)
    engine.dispose()


def stamp_head(engine: Engine | None = None) -> None:
    """Stamp Alembic version table at head without running migrations."""
    engine = engine or get_engine()
    run_alembic_command("stamp", engine)
