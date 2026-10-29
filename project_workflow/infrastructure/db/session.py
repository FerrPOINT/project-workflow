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
from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    inspect,
    literal,
    select,
    text,
)
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from project_workflow.config import get_settings

from . import project_admission  # noqa: F401 -- registers request-scoped ORM guards
from .models import Base

logger = logging.getLogger(__name__)

_engine: Engine | None = None
_engine_lock = Lock()

_LEGACY_ARCHIVES = frozenset({"legacy_agent_metadata", "legacy_phase_agent_links"})
_LEGACY_READONLY_BODY = "BEGIN RAISE EXCEPTION 'Legacy metadata archive is read-only'; END;"


def _legacy_archive_tables(connection: Connection) -> tuple[Table, Table]:
    """Released metadata only; these records never establish runtime authority."""
    schema = get_settings().DB_SCHEMA if connection.dialect.name == "postgresql" else None
    metadata = MetaData(schema=schema)
    agents = Table("legacy_agent_metadata", metadata,
                   Column("id", Integer, primary_key=True, autoincrement=False),
                   Column("name", String, nullable=False), Column("description", String, nullable=False),
                   Column("hermes_profile", String(251), nullable=True))
    links = Table("legacy_phase_agent_links", metadata,
                  Column("phase_id", Integer, primary_key=True, autoincrement=False),
                  Column("agent_id", Integer, ForeignKey(f"{agents.fullname}.id", ondelete="RESTRICT"), nullable=True))
    return agents, links


def _legacy_readonly_ddl(connection: Connection) -> list[str]:
    if connection.dialect.name == "sqlite":
        return [f"CREATE TRIGGER {name}_no_{action.lower()} BEFORE {action} ON {name} "
                "BEGIN SELECT RAISE(ABORT, 'Legacy metadata archive is read-only'); END"
                for name in sorted(_LEGACY_ARCHIVES) for action in ("INSERT", "UPDATE", "DELETE")]
    schema = connection.dialect.identifier_preparer.quote_schema(get_settings().DB_SCHEMA)
    return [f"CREATE FUNCTION {schema}.legacy_metadata_readonly() RETURNS trigger LANGUAGE plpgsql "
            f"AS $${_LEGACY_READONLY_BODY}$$",
            *[f"CREATE TRIGGER {name}_readonly BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON {schema}.{name} "
              f"FOR EACH STATEMENT EXECUTE FUNCTION {schema}.legacy_metadata_readonly()"
              for name in sorted(_LEGACY_ARCHIVES)]]


def _legacy_archive_guards(connection: Connection, present: bool) -> bool:
    if connection.dialect.name == "sqlite":
        rows: dict[str, str] = {name: sql for name, sql in connection.execute(text(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND "
            "(tbl_name IN ('legacy_agent_metadata','legacy_phase_agent_links') OR "
            "name LIKE 'legacy_agent_metadata_no_%' OR name LIKE 'legacy_phase_agent_links_no_%')"
        )).all()}
        expected_sql = {sql.split()[2]: sql for sql in _legacy_readonly_ddl(connection)} if present else {}
        return rows == expected_sql
    schema = get_settings().DB_SCHEMA
    functions = connection.execute(text(
        "SELECT p.prosrc,p.pronargs,p.prorettype='trigger'::regtype,l.lanname FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang "
        "WHERE n.nspname=:schema AND p.proname='legacy_metadata_readonly'"
    ), {"schema": schema}).all()
    triggers = connection.execute(text(
        "SELECT c.relname,t.tgname,t.tgtype,t.tgenabled,t.tgnargs,t.tgqual IS NULL,p.proname,pn.nspname "
        "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace pn ON pn.oid=p.pronamespace "
        "WHERE n.nspname=:schema AND NOT t.tgisinternal AND "
        "(c.relname IN ('legacy_agent_metadata','legacy_phase_agent_links') OR "
        "t.tgname IN ('legacy_agent_metadata_readonly','legacy_phase_agent_links_readonly'))"
    ), {"schema": schema}).all()
    expected_triggers = {(name, f"{name}_readonly", 62, "O", 0, True, "legacy_metadata_readonly", schema)
                         for name in _LEGACY_ARCHIVES} if present else set()
    return (functions == ([(_LEGACY_READONLY_BODY, 0, True, "plpgsql")] if present else [])
            and set(triggers) == expected_triggers)


def _validate_legacy_archives(connection: Connection) -> bool:
    agents, links = _legacy_archive_tables(connection)
    inspector = inspect(connection)
    views = set(inspector.get_view_names(schema=agents.schema))
    if connection.dialect.name == "postgresql":
        views.update(inspector.get_materialized_view_names(schema=agents.schema))
    if views & _LEGACY_ARCHIVES:
        raise ValueError("Legacy agent metadata preservation refused: foreign archive view")
    present = set(inspector.get_table_names(schema=agents.schema)) & _LEGACY_ARCHIVES
    if present and present != _LEGACY_ARCHIVES or not _legacy_archive_guards(connection, bool(present)):
        raise ValueError("Legacy agent metadata preservation refused: partial or foreign archive")
    if not present:
        return False
    for table in (agents, links):
        columns = inspector.get_columns(table.name, schema=table.schema)
        expected = [(c.name, str(c.type.compile(dialect=connection.dialect)), c.nullable) for c in table.c]
        actual = [(c["name"], str(c["type"].compile(dialect=connection.dialect)), c["nullable"]) for c in columns]
        keys = inspector.get_pk_constraint(table.name, schema=table.schema)["constrained_columns"]
        foreign = inspector.get_foreign_keys(table.name, schema=table.schema)
        valid_fk = not foreign if table is agents else len(foreign) == 1 and (
            foreign[0]["constrained_columns"] == ["agent_id"] and foreign[0]["referred_table"] == agents.name
            and foreign[0]["referred_columns"] == ["id"]
            and foreign[0]["referred_schema"] in {None, agents.schema}
            and foreign[0]["options"].get("ondelete") == "RESTRICT"
        )
        if (actual != expected or keys != [c.name for c in table.primary_key]
            or any(c.get("default") is not None for c in columns)
            or not valid_fk or inspector.get_indexes(table.name, schema=table.schema)
            or inspector.get_unique_constraints(table.name, schema=table.schema)
            or inspector.get_check_constraints(table.name, schema=table.schema)):
            raise ValueError("Legacy agent metadata preservation refused: foreign archive schema")
    orphan = select(literal(1)).select_from(links.outerjoin(agents, links.c.agent_id == agents.c.id)).where(
        links.c.agent_id.is_not(None), agents.c.id.is_(None),
    ).limit(1)
    if connection.execute(orphan).first() is not None:
        raise ValueError("Legacy agent metadata preservation refused: foreign phase-agent join")
    return True


def _preserve_legacy_metadata(connection: Connection) -> None:
    """Copy before released 0013 inside initialization transaction; never overwrite."""
    agents, links = _legacy_archive_tables(connection)
    tables = set(inspect(connection).get_table_names(schema=agents.schema))
    present = _validate_legacy_archives(connection)
    phase_columns = inspect(connection).get_columns("phases", schema=agents.schema) if "phases" in tables else []
    source_present = "agents" in tables
    if source_present != any(c["name"] == "agent_id" for c in phase_columns):
        raise ValueError("Legacy agent metadata preservation refused: partial legacy source")
    if not source_present:
        return
    if connection.dialect.name == "postgresql":
        schema = connection.dialect.identifier_preparer.quote_schema(get_settings().DB_SCHEMA)
        connection.execute(text(f"LOCK TABLE {schema}.agents,{schema}.phases IN ACCESS EXCLUSIVE MODE"))
    original = Table("agents", MetaData(), schema=agents.schema, autoload_with=connection, resolve_fks=False)
    phases = Table("phases", MetaData(), schema=agents.schema, autoload_with=connection, resolve_fks=False)
    if ([(c.name, str(c.type.compile(dialect=connection.dialect)), c.nullable) for c in original.c]
        != [(c.name, str(c.type.compile(dialect=connection.dialect)), c.nullable) for c in agents.c]):
        raise ValueError("Legacy agent metadata preservation refused: foreign legacy columns")
    sources = (select(*original.c), select(phases.c.id, phases.c.agent_id))
    if not present:
        agents.metadata.create_all(connection)
        for table, source in zip((agents, links), sources, strict=True):
            connection.execute(table.insert().from_select(list(table.c.keys()), source))
    for table, source in zip((agents, links), sources, strict=True):
        archived = select(*table.c)
        for difference in (source.except_(archived), archived.except_(source)):
            if connection.execute(select(literal(1)).select_from(difference.subquery()).limit(1)).first() is not None:
                raise ValueError("Legacy agent metadata preservation refused: incomplete or changed archive")
    if not present:
        for sql in _legacy_readonly_ddl(connection):
            connection.execute(text(sql))
    _validate_legacy_archives(connection)


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
    alembic_cfg = _alembic_config()
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
    if target.dialect.name == "sqlite":
        # SQLite ignores PRAGMA foreign_keys changes once a transaction has
        # started. Alembic batch table rebuilds therefore need enforcement
        # disabled before the migration transaction, then restored even when
        # the migration fails.
        with target.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            try:
                with connection.begin():
                    migrate(connection)
            finally:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()
        return
    with target.begin() as connection:
        migrate(connection)


def _metadata_is_current(target: Engine | Connection) -> bool:
    """Compare the live schema with the complete ORM metadata contract."""

    def compare(connection: Connection) -> bool:
        try:
            _validate_legacy_archives(connection)
        except ValueError:
            return False
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": True,
                  "include_object": lambda obj, name, kind, reflected, compare_to:
                  kind != "table" or name not in _LEGACY_ARCHIVES},
        )
        return compare_metadata(context, Base.metadata) == []

    if isinstance(target, Connection):
        return compare(target)
    with target.connect() as connection:
        return compare(connection)


def ensure_migrated(engine: Engine | Connection | None = None) -> None:
    """Apply migrations to empty databases or supported versioned predecessors."""
    target = engine or get_engine()
    if isinstance(target, Engine):
        with initialization_transaction(target) as connection:
            ensure_migrated(connection)
        return
    if target.dialect.name == "sqlite":
        driver = target.connection.driver_connection
        if not isinstance(driver, sqlite3.Connection):
            raise ValueError("SQLite migration connection unavailable")
        if not driver.in_transaction:
            target.exec_driver_sql("BEGIN IMMEDIATE")
    bound_engine = target.engine if isinstance(target, Connection) else target
    schema = None if _is_sqlite(str(bound_engine.url)) else get_settings().DB_SCHEMA
    revisions = database_revisions(target)
    existing_tables = set(inspect(target).get_table_names(schema=schema)) - {"alembic_version"}
    head = migration_head()
    compatible_upgrade_revisions = {
        head,
        "0001_initial",
        "0002_workflow_modes",
        "0003_runtime_assignment_bind",
        "0004_wide_work_item_revision",
        "0005_mode_execution_scopes",
        "0006_versioned_mode_catalog",
        "0007_resource_execution_contexts",
        "0008_pm_execution",
        "0009_pm_draft_assignment",
        "0010_namespace_default_names",
        "0011_profession_workflows",
        "0012_profession_themes",
        "0013_profession_execution",
        "0014_launch_profile_only",
        "0015_single_task_assignments",
        "0016_human_project_commit_guard",
        "0017_human_application_clock",
        "0018_identity_deletion_owner",
        "0019_pm_terminal_resume_retry",
        "0020_configured_cli_catalog",
        "0021_profession_task_workflows",
    }
    incompatible_revision = bool(revisions) and not revisions.issubset(compatible_upgrade_revisions)
    _validate_legacy_archives(target)
    exact_tables = existing_tables - _LEGACY_ARCHIVES == expected_tables()
    incompatible_schema = revisions == {head} and (
        not exact_tables or not _metadata_is_current(target)
    )
    unversioned_database = not revisions and bool(existing_tables)
    if incompatible_revision or incompatible_schema or unversioned_database:
        raise DatabaseRecreateRequired()
    _preserve_legacy_metadata(target)
    run_alembic_command("upgrade", target)
    migrated_tables = set(inspect(target).get_table_names(schema=schema)) - {"alembic_version"}
    if migrated_tables - _LEGACY_ARCHIVES != expected_tables() or not _metadata_is_current(target):
        raise DatabaseRecreateRequired()


def migration_head() -> str:
    """Return the repository's single Alembic head revision."""
    script = ScriptDirectory.from_config(_alembic_config())
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("Не настроена головная ревизия миграций Alembic")
    return head


def _alembic_config() -> Config:
    """Build a cwd-independent config for packaged programmatic migrations."""
    config = Config()
    migrations = Path(__file__).resolve().parent / "migrations"
    config.set_main_option("script_location", str(migrations))
    return config


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
        and tables - {"alembic_version"} - _LEGACY_ARCHIVES == expected_tables()
        and _metadata_is_current(engine)
    )


@contextmanager
def initialization_transaction(engine: Engine) -> Iterator[Connection]:
    """Serialize and atomically run migration plus bootstrap for one schema."""
    if engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            try:
                with connection.begin():
                    # pysqlite's legacy mode otherwise auto-commits DDL before the first INSERT.
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                    yield connection
            finally:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()
        return
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
