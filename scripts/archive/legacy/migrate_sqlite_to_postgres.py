#!/usr/bin/env python3
"""Migrate legacy SQLite workflow.db data into the Postgres database.

Uses the SQLAlchemy ORM models in ``project_workflow.infrastructure.db.models``
and the configured ``DATABASE_URL`` / ``DB_SCHEMA`` for the Postgres target.

Tables are copied in dependency order, target tables are cleared in reverse
order, and Postgres serial sequences are reset to the maximum migrated PK.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

# Allow running the script from the repo root without installing the package.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from project_workflow.config import get_settings  # noqa: E402
from project_workflow.infrastructure.db.models import (  # noqa: E402
    Agent,
    Base,
    Check,
    CliHistory,
    Evidence,
    Instruction,
    Phase,
    Project,
    SupervisorRun,
    Task,
    TaskHistory,
    Workflow,
)
from project_workflow.infrastructure.db.session import get_engine  # noqa: E402

ModelT = TypeVar("ModelT", bound=Base)

# Tables are ordered so parents are inserted before children.
MIGRATION_TABLES = [
    "agents",
    "workflows",
    "phases",
    "instructions",
    "checks",
    "evidence",
    "projects",
    "tasks",
    "task_history",
    "supervisor_runs",
    "cli_history",
]

# Map legacy SQLite column names to ORM attribute names.
COLUMN_MAP: dict[str, dict[str, str]] = {
    "phases": {"phase_num": "phase_order"},
}

MODEL_BY_TABLE: dict[str, type[Base]] = {
    "agents": Agent,
    "workflows": Workflow,
    "phases": Phase,
    "instructions": Instruction,
    "checks": Check,
    "evidence": Evidence,
    "projects": Project,
    "tasks": Task,
    "task_history": TaskHistory,
    "supervisor_runs": SupervisorRun,
    "cli_history": CliHistory,
}


def _get_legacy_sqlite_engine() -> Engine:
    """Build an engine for the legacy SQLite database.

    The default path mirrors WorkflowDB.DB_PATH. Override with the
    ``WORKFLOW_DB_PATH`` environment variable.
    """
    env_path = os.getenv("WORKFLOW_DB_PATH")
    if env_path:
        db_path = Path(env_path)
    else:
        pkg_dir = Path(__file__).resolve().parent.parent / "project_workflow"
        db_path = pkg_dir / "data" / "workflow.db"

    if not db_path.exists():
        raise FileNotFoundError(f"Legacy SQLite database not found: {db_path}")

    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )


def _target_table_names() -> list[str]:
    """Return table names in the order they should be cleared.

    Children must be deleted before parents, so this is the reverse insertion
    order.
    """
    return list(reversed(MIGRATION_TABLES))


def _get_model_columns(model: type[Base]) -> list[str]:
    """Return the list of column/attribute names for ``model``."""
    return [column.name for column in inspect(model).mapper.columns]


def _map_legacy_row(
    table_name: str,
    row: dict[str, Any],
    model_columns: list[str],
) -> dict[str, Any]:
    """Translate a raw SQLite row dict to kwargs suitable for the ORM model."""
    mapping = COLUMN_MAP.get(table_name, {})
    translated: dict[str, Any] = {}
    for legacy_key, value in row.items():
        model_key = mapping.get(legacy_key, legacy_key)
        if model_key in model_columns:
            translated[model_key] = value
    return translated


def _clear_target_tables(target_session: Session) -> None:
    """Delete all rows from target tables in FK-safe order."""
    for table_name in _target_table_names():
        model = MODEL_BY_TABLE[table_name]
        count = target_session.query(model).delete(synchronize_session=False)
        print(f"  cleared {table_name}: {count} rows deleted")


def _reset_sequences(target_engine: Engine) -> None:
    """Reset Postgres SERIAL sequences to the highest inserted PK + 1."""
    schema = get_settings().DB_SCHEMA
    with target_engine.begin() as conn:
        for table_name in MIGRATION_TABLES:
            model = MODEL_BY_TABLE[table_name]
            pk_column = inspect(model).mapper.primary_key[0].name
            seq_name = f"{table_name}_{pk_column}_seq"
            if schema:
                conn.exec_driver_sql(
                    f"SELECT setval('{schema}.{seq_name}', COALESCE((SELECT MAX({pk_column}) FROM {schema}.{table_name}), 1), true)"  # noqa: S608
                )
            else:
                conn.exec_driver_sql(
                    f"SELECT setval('{seq_name}', COALESCE((SELECT MAX({pk_column}) FROM {table_name}), 1), true)"  # noqa: S608
                )


def _copy_table(
    source_engine: Engine,
    target_session: Session,
    table_name: str,
    model: type[ModelT],
    row_transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> int:
    """Copy all rows from the SQLite table into Postgres via the ORM model."""
    model_columns = _get_model_columns(model)
    with source_engine.connect() as conn:
        rows = conn.execute(text(f"SELECT * FROM {table_name}")).mappings().all()

    inserted = 0
    for raw_row in rows:
        row = dict(raw_row)
        kwargs = _map_legacy_row(table_name, row, model_columns)
        if row_transform:
            kwargs = row_transform(kwargs)
        target_session.add(model(**kwargs))
        inserted += 1

    target_session.flush()
    return inserted


def _coerce_int(value: Any) -> int | None:
    """Convert SQLite booleans/numbers to int or None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def migrate(source_engine: Engine | None = None, target_engine: Engine | None = None) -> dict[str, int]:
    """Run the full migration and return per-table inserted row counts."""
    if source_engine is None:
        source_engine = _get_legacy_sqlite_engine()
    if target_engine is None:
        target_engine = get_engine()

    TargetSession = sessionmaker(bind=target_engine, expire_on_commit=False)
    target_session = TargetSession()

    summary: dict[str, int] = {}

    try:
        print("Clearing target tables...")
        _clear_target_tables(target_session)

        print("Copying data from SQLite to Postgres...")
        for table_name in MIGRATION_TABLES:
            model = MODEL_BY_TABLE[table_name]
            transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None

            if table_name == "phases":
                def _phase_transform(row: dict[str, Any]) -> dict[str, Any]:
                    row["is_seed_managed"] = _coerce_int(row.get("is_seed_managed")) or 0
                    return row

                transform = _phase_transform

            count = _copy_table(source_engine, target_session, table_name, model, transform)
            summary[table_name] = count
            print(f"  {table_name}: {count} rows copied")

        print("Resetting Postgres sequences...")
        _reset_sequences(target_engine)

        target_session.commit()
    except Exception:
        target_session.rollback()
        raise
    finally:
        target_session.close()

    return summary


def main() -> None:
    print("Starting SQLite → Postgres migration")
    counts = migrate()
    total = sum(counts.values())
    print("\nMigration complete.")
    print(f"Total rows copied: {total}")
    for table_name, count in counts.items():
        print(f"  {table_name}: {count}")


if __name__ == "__main__":
    main()
