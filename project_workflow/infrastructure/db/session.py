"""Database connection / session factory.

The DSN is read from config.Settings.DATABASE_URL.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from project_workflow.config import get_settings

from .models import Base

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


PG_CONNECT_RETRY_ATTEMPTS: int = 3
PG_CONNECT_RETRY_DELAY: float = 1.0
class DatabaseRecreateRequired(RuntimeError):
    """The configured database cannot safely use the clean baseline."""

    exit_code = 2

    def __init__(self) -> None:
        super().__init__("legacy database must be recreated")


def expected_tables() -> frozenset[str]:
    """Return the exact application table set owned by ORM metadata."""
    return frozenset(Base.metadata.tables)


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite://")


def get_database_url() -> str:
    url = get_settings().DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL is not configured. Set it to a PostgreSQL or SQLite DSN.")
    return url


def _normalize_url(url: str | None) -> str:
    if not url:
        return get_database_url()
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
        except (SQLAlchemyError, OSError) as exc:
            last_exc = exc
            logger.warning("Postgres engine creation failed (attempt %s): %s", attempt + 1, exc)
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
    """Create the ORM schema for isolated SQLite tests only."""
    target = engine or get_engine()
    dialect = target.dialect.name
    if dialect != "sqlite":
        raise RuntimeError("ensure_schema is only available for isolated SQLite tests")
    if isinstance(target, Connection):
        Base.metadata.create_all(target)
    else:
        with target.begin() as conn:
            Base.metadata.create_all(conn)


def run_alembic_command(
    cmd: str,
    engine: Engine | Connection | None = None,
    revision: str = "head",
) -> None:
    """Run an Alembic command in one DDL transaction."""
    target = engine or get_engine()
    bound_engine = target.engine if isinstance(target, Connection) else target
    here = Path(__file__).resolve().parent.parent.parent.parent
    alembic_cfg = Config(str(here / "alembic.ini"))
    url = bound_engine.url.render_as_string(hide_password=False).replace("%", "%%")
    alembic_cfg.set_main_option("sqlalchemy.url", url)

    def migrate(connection: Connection) -> None:
        alembic_cfg.attributes["connection"] = connection
        getattr(command, cmd)(alembic_cfg, revision)
        if cmd == "downgrade" and revision == "base" and connection.dialect.name == "postgresql":
            schema = get_settings().DB_SCHEMA
            if schema and schema != "public":
                quoted_schema = connection.dialect.identifier_preparer.quote(schema)
                connection.exec_driver_sql(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE")

    if isinstance(target, Connection):
        migrate(target)
        return
    with target.begin() as connection:
        migrate(connection)
    target.dispose()


def ensure_migrated(engine: Engine | Connection | None = None) -> None:
    """Apply the baseline migration, rejecting databases from the legacy graph."""
    target = engine or get_engine()
    bound_engine = target.engine if isinstance(target, Connection) else target
    schema = None if _is_sqlite(str(bound_engine.url)) else get_settings().DB_SCHEMA
    revisions = database_revisions(target)
    existing_tables = set(inspect(target).get_table_names(schema=schema)) - {"alembic_version"}
    incompatible_revision = revisions and revisions != {migration_head()}
    incompatible_schema = revisions == {migration_head()} and existing_tables != expected_tables()
    unversioned_database = not revisions and bool(existing_tables)
    if incompatible_revision or incompatible_schema or unversioned_database:
        raise DatabaseRecreateRequired()
    run_alembic_command("upgrade", target)
    migrated_tables = set(inspect(target).get_table_names(schema=schema)) - {"alembic_version"}
    if migrated_tables != expected_tables():
        raise DatabaseRecreateRequired()


def migration_head() -> str:
    """Return the repository's single Alembic head revision."""
    here = Path(__file__).resolve().parent.parent.parent.parent
    script = ScriptDirectory.from_config(Config(str(here / "alembic.ini")))
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("Alembic migration head is not configured")
    return head


def database_revisions(engine: Engine | Connection) -> set[str]:
    """Read applied Alembic revisions without mutating the database."""
    bound_engine = engine.engine if isinstance(engine, Connection) else engine
    schema = None if _is_sqlite(str(bound_engine.url)) else get_settings().DB_SCHEMA
    inspector = inspect(engine)
    if not inspector.has_table("alembic_version", schema=schema):
        return set()
    qualified_table = "alembic_version"
    if schema:
        quoted_schema = engine.dialect.identifier_preparer.quote(schema)
        qualified_table = f"{quoted_schema}.alembic_version"
    if isinstance(engine, Connection):
        return set(engine.execute(text(f"SELECT version_num FROM {qualified_table}")).scalars())
    with engine.connect() as conn:
        return set(conn.execute(text(f"SELECT version_num FROM {qualified_table}")).scalars())


def schema_is_ready(engine: Engine) -> bool:
    """Return whether the database is at head with the exact owned schema."""
    schema = None if _is_sqlite(str(engine.url)) else get_settings().DB_SCHEMA
    tables = set(inspect(engine).get_table_names(schema=schema))
    return database_revisions(engine) == {migration_head()} and tables - {"alembic_version"} == expected_tables()


@contextmanager
def initialization_transaction(engine: Engine) -> Iterator[Connection]:
    """Serialize and atomically run migration plus bootstrap for one schema."""
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(current_database() || ':' || :schema, 0))"
                ),
                {"schema": get_settings().DB_SCHEMA},
            )
        yield connection
