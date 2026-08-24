import os
import sys
from contextlib import nullcontext
from logging.config import fileConfig
from pathlib import Path
from typing import Any

from alembic import context
from sqlalchemy import create_engine, pool, text

# Make package importable when alembic is run from repo root.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_workflow.config import get_settings  # noqa: E402
from project_workflow.infrastructure.db.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

SCHEMA = get_settings().DB_SCHEMA


def _ensure_schema(connection: Any) -> None:
    """Create and select the configured schema before PostgreSQL migrations."""
    dialect = connection.dialect.name
    if dialect != "postgresql":
        return
    quoted_schema = connection.dialect.identifier_preparer.quote(SCHEMA)
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {quoted_schema}"))
    connection.execute(text(f"SET search_path TO {quoted_schema}"))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    configure_kwargs = dict(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    if "postgresql" in (url or ""):
        configure_kwargs["version_table_schema"] = SCHEMA
    context.configure(**configure_kwargs)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    def migrate(connection: Any) -> None:
        is_postgresql = connection.dialect.name == "postgresql"
        transaction = nullcontext() if connection.in_transaction() else connection.begin()
        with transaction:
            _ensure_schema(connection)
            configure_kwargs = dict(
                connection=connection,
                target_metadata=target_metadata,
                transactional_ddl=True,
            )
            if is_postgresql:
                configure_kwargs["version_table_schema"] = SCHEMA
            context.configure(**configure_kwargs)
            context.run_migrations()

    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        migrate(supplied_connection)
        return

    db_url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if not db_url:
        raise RuntimeError("DATABASE_URL is required for online migrations")
    connectable = create_engine(db_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        migrate(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
