from logging.config import fileConfig
from pathlib import Path
import sys

import os
from sqlalchemy import engine_from_config, pool, text

from alembic import context

# Make package importable when alembic is run from repo root.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_workflow.config import get_settings  # noqa: E402
from project_workflow.infrastructure.db.models import Base  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# Allow Docker / ops to override the DB URL via environment.
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

SCHEMA = get_settings().DB_SCHEMA


def _ensure_schema(connection) -> None:
    """Create target schema before running migrations on PostgreSQL."""
    dialect = connection.dialect.name
    if dialect != "postgresql":
        return
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))


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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _ensure_schema(connection)
        configure_kwargs = dict(
            connection=connection,
            target_metadata=target_metadata,
        )
        if connection.dialect.name == "postgresql":
            configure_kwargs["version_table_schema"] = SCHEMA
        context.configure(**configure_kwargs)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
