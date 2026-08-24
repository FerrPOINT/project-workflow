"""Contract tests for the single clean Alembic baseline."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from project_workflow.infrastructure.db.models import Base
from project_workflow.infrastructure.db.session import (
    DatabaseRecreateRequired,
    database_revisions,
    ensure_migrated,
    migration_head,
    run_alembic_command,
    schema_is_ready,
)


def _sqlite_engine(tmp_path: Path):
    return create_engine(f"sqlite:///{tmp_path / 'initial.db'}")


def _constraint_names(items: list[dict]) -> set[str]:
    return {str(item["name"]) for item in items if item.get("name")}


def test_repository_has_exactly_one_base_and_head():
    versions = Path(__file__).parents[1] / "project_workflow" / "infrastructure" / "db" / "migrations" / "versions"
    assert [path.name for path in versions.glob("*.py")] == ["0001_initial_schema.py"]
    assert migration_head() == "0001_initial"


def test_fresh_sqlite_migration_matches_orm_metadata(tmp_path):
    engine = _sqlite_engine(tmp_path)
    ensure_migrated(engine)

    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names()) - {"alembic_version"}
    assert actual_tables == set(Base.metadata.tables)

    for table_name, table in Base.metadata.tables.items():
        actual_columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert set(actual_columns) == set(table.columns.keys()), table_name
        assert {
            name: column["nullable"] for name, column in actual_columns.items()
        } == {name: column.nullable for name, column in table.columns.items()}

        expected_checks = {
            constraint.name
            for constraint in table.constraints
            if constraint.__class__.__name__ == "CheckConstraint"
        }
        expected_uniques = {
            constraint.name
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        assert _constraint_names(inspector.get_check_constraints(table_name)) == expected_checks - {None}
        assert _constraint_names(inspector.get_unique_constraints(table_name)) == expected_uniques - {None}
        assert _constraint_names(inspector.get_indexes(table_name)) == {index.name for index in table.indexes}

        actual_fks = {
            (
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                (fk.get("options") or {}).get("ondelete"),
            )
            for fk in inspector.get_foreign_keys(table_name)
        }
        expected_fks = {
            (
                tuple(constraint.column_keys),
                next(iter(constraint.elements)).column.table.name,
                tuple(element.column.name for element in constraint.elements),
                constraint.ondelete,
            )
            for constraint in table.foreign_key_constraints
        }
        assert actual_fks == expected_fks, table_name

    assert database_revisions(engine) == {"0001_initial"}
    assert schema_is_ready(engine) is True
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": True},
        )
        assert compare_metadata(context, Base.metadata) == []


def test_in_memory_sqlite_migration_keeps_the_schema_alive():
    engine = create_engine("sqlite://")

    ensure_migrated(engine)

    assert schema_is_ready(engine) is True


def test_sqlite_upgrade_downgrade_reupgrade(tmp_path):
    engine = _sqlite_engine(tmp_path)
    ensure_migrated(engine)
    run_alembic_command("downgrade", engine, "base")
    assert set(inspect(engine).get_table_names()).isdisjoint(Base.metadata.tables)
    ensure_migrated(engine)
    assert set(Base.metadata.tables).issubset(inspect(engine).get_table_names())


def test_sqlite_legacy_revision_is_refused_without_mutation(tmp_path):
    engine = _sqlite_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('old_revision')"))
        conn.execute(text("CREATE TABLE keep_me (id INTEGER PRIMARY KEY)"))

    with pytest.raises(DatabaseRecreateRequired, match="legacy database must be recreated"):
        ensure_migrated(engine)

    assert database_revisions(engine) == {"old_revision"}
    assert inspect(engine).has_table("keep_me")


def test_sqlite_unversioned_nonempty_database_is_refused(tmp_path):
    engine = _sqlite_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE keep_me (id INTEGER PRIMARY KEY)"))

    with pytest.raises(DatabaseRecreateRequired, match="legacy database must be recreated"):
        ensure_migrated(engine)

    assert inspect(engine).has_table("keep_me")


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_head_with_damaged_or_polluted_schema_is_refused(tmp_path, mutation):
    engine = _sqlite_engine(tmp_path)
    ensure_migrated(engine)
    with engine.begin() as connection:
        if mutation == "missing":
            connection.execute(text("DROP TABLE instructions"))
        else:
            connection.execute(text("CREATE TABLE unexpected_table (id INTEGER PRIMARY KEY)"))

    assert schema_is_ready(engine) is False
    with pytest.raises(DatabaseRecreateRequired):
        ensure_migrated(engine)


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE projects ADD COLUMN unexpected_column TEXT",
        "ALTER TABLE projects DROP COLUMN description",
    ],
)
def test_head_with_column_drift_is_refused(tmp_path, statement):
    engine = _sqlite_engine(tmp_path)
    ensure_migrated(engine)
    with engine.begin() as connection:
        connection.execute(text(statement))

    assert schema_is_ready(engine) is False
    with pytest.raises(DatabaseRecreateRequired):
        ensure_migrated(engine)


def test_sqlite_initial_constraints(tmp_path):
    engine = _sqlite_engine(tmp_path)
    ensure_migrated(engine)
    with engine.begin() as conn:
        workflow_id = conn.execute(
            text("INSERT INTO workflows (name, description, is_default) VALUES ('W', '', 1) RETURNING id")
        ).scalar_one()
        phase_id = conn.execute(
            text(
                "INSERT INTO phases (workflow_id, code, name, phase_order) "
                "VALUES (:workflow_id, '1', 'Phase', 1) RETURNING id"
            ),
            {"workflow_id": workflow_id},
        ).scalar_one()

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO phases (workflow_id, code, name, phase_order) "
                    "VALUES (:workflow_id, '0', 'Bad', 0)"
                ),
                {"workflow_id": workflow_id},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO instructions (phase_id, step_num, description) VALUES (:id, 0, 'Bad')"),
                {"id": phase_id},
            )


def test_health_requires_migrated_schema_and_hides_internal_details(tmp_path, monkeypatch):
    from project_workflow.infrastructure.db import session
    from project_workflow.interfaces.ui.app import _health

    engine = _sqlite_engine(tmp_path)
    monkeypatch.setattr(session, "get_engine", lambda: engine)
    unavailable = asyncio.run(_health())
    assert unavailable.status_code == 503
    assert b'"error_code":"schema-not-ready"' in unavailable.body
    assert b"sqlite" not in unavailable.body.lower()

    ensure_migrated(engine)
    ready = asyncio.run(_health())
    assert ready.status_code == 200
    assert b'"database":"ok"' in ready.body
    assert b'"schema":"ok"' in ready.body
