"""Database connection / session factory.

The DSN is read from config.Settings.DATABASE_URL.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from project_workflow.config import get_settings

from .models import Base

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_engine_lock = Lock()


PG_CONNECT_RETRY_ATTEMPTS: int = 3
PG_CONNECT_RETRY_DELAY: float = 1.0


class DatabaseUnavailable(RuntimeError):
    """База данных недоступна или её DSN настроен неверно."""

    exit_code = 1

    def __init__(self) -> None:
        super().__init__("Не удалось подключиться к базе данных; проверьте DATABASE_URL")


class DatabaseRecreateRequired(RuntimeError):
    """The configured database cannot safely use the clean baseline."""

    exit_code = 2

    def __init__(self) -> None:
        super().__init__("Несовместимую базу данных необходимо пересоздать")


def expected_tables() -> frozenset[str]:
    """Return the exact application table set owned by ORM metadata."""
    return frozenset(Base.metadata.tables)


def _is_sqlite(url: str) -> bool:
    return make_url(url).get_backend_name() == "sqlite"


def get_database_url() -> str:
    url = get_settings().DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL не настроен. Укажите DSN PostgreSQL или SQLite.")
    return url


def _normalize_url(url: str | None) -> str:
    if not url:
        return get_database_url()
    return url


def get_engine(url: str | None = None) -> Engine:
    """Return a cached or newly created SQLAlchemy engine."""
    global _engine
    target = _normalize_url(url)
    try:
        parsed_target = make_url(target)
    except (SQLAlchemyError, TypeError, ValueError):
        raise DatabaseUnavailable() from None
    if parsed_target.get_backend_name() not in {"postgresql", "sqlite"}:
        raise DatabaseUnavailable() from None
    if (
        parsed_target.get_backend_name() == "sqlite"
        and parsed_target.database not in (None, "", ":memory:")
    ):
        parsed_target = parsed_target.set(database=str(Path(parsed_target.database).resolve()))
    with _engine_lock:
        if _engine is not None and _engine.url == parsed_target:
            return _engine
        if parsed_target.get_backend_name() == "sqlite":
            db_path = parsed_target.database
            if db_path and db_path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            new_engine = create_engine(
                parsed_target,
                connect_args={"check_same_thread": False, "timeout": 10},
                echo=False,
                poolclass=NullPool,
            )
        else:
            new_engine = _create_postgres_engine(target)
        previous_engine = _engine
        _engine = new_engine
        if previous_engine is not None:
            previous_engine.dispose()
        return new_engine


def _create_postgres_engine(target: str) -> Engine:
    """Create a PostgreSQL engine with search_path and connection retry."""
    connect_args = {}
    schema = get_settings().DB_SCHEMA
    if schema:
        connect_args["options"] = f"-csearch_path={schema}"
    for attempt in range(PG_CONNECT_RETRY_ATTEMPTS):
        engine: Engine | None = None
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
        except (SQLAlchemyError, OSError):
            if engine is not None:
                engine.dispose()
            logger.warning(
                "Не удалось подключиться к PostgreSQL: попытка %s из %s",
                attempt + 1,
                PG_CONNECT_RETRY_ATTEMPTS,
            )
            if attempt + 1 < PG_CONNECT_RETRY_ATTEMPTS:
                time.sleep(PG_CONNECT_RETRY_DELAY)
    raise DatabaseUnavailable() from None


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
    if not isinstance(dbapi_conn, sqlite3.Connection):
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
    global _engine
    with _engine_lock:
        previous_engine = _engine
        _engine = None
        if previous_engine is not None:
            previous_engine.dispose()


def ensure_schema(engine: Engine | Connection | None = None) -> None:
    """Create the ORM schema for isolated SQLite tests only."""
    target = engine or get_engine()
    dialect = target.dialect.name
    if dialect != "sqlite":
        raise RuntimeError("ensure_schema доступен только в изолированных тестах SQLite")
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


def _metadata_is_current(target: Engine | Connection) -> bool:
    """Compare the live schema with the complete ORM metadata contract."""

    def compare(connection: Connection) -> bool:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": True},
        )
        return compare_metadata(context, Base.metadata) == []

    if isinstance(target, Connection):
        return compare(target)
    with target.connect() as connection:
        return compare(connection)


def ensure_migrated(engine: Engine | Connection | None = None) -> None:
    """Apply the baseline only to an empty or exact ``0001_initial`` database."""
    target = engine or get_engine()
    bound_engine = target.engine if isinstance(target, Connection) else target
    schema = None if _is_sqlite(str(bound_engine.url)) else get_settings().DB_SCHEMA
    revisions = database_revisions(target)
    existing_tables = set(inspect(target).get_table_names(schema=schema)) - {"alembic_version"}
    incompatible_revision = bool(revisions) and revisions != {migration_head()}
    exact_tables = existing_tables == expected_tables()
    incompatible_schema = revisions == {migration_head()} and (
        not exact_tables or not _metadata_is_current(target)
    )
    unversioned_database = not revisions and bool(existing_tables)
    if incompatible_revision or incompatible_schema or unversioned_database:
        raise DatabaseRecreateRequired()
    run_alembic_command("upgrade", target)
    migrated_tables = set(inspect(target).get_table_names(schema=schema)) - {"alembic_version"}
    if migrated_tables != expected_tables() or not _metadata_is_current(target):
        raise DatabaseRecreateRequired()


def migration_head() -> str:
    """Return the repository's single Alembic head revision."""
    here = Path(__file__).resolve().parent.parent.parent.parent
    script = ScriptDirectory.from_config(Config(str(here / "alembic.ini")))
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("Не настроена головная ревизия миграций Alembic")
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
    return (
        database_revisions(engine) == {migration_head()}
        and tables - {"alembic_version"} == expected_tables()
        and _metadata_is_current(engine)
    )


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
