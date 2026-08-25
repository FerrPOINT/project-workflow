"""Explicit, fail-closed bridge for the one deployed legacy Alembic head.

This entrypoint is intentionally separate from the two-command product CLI.
It may only bridge ``e6a4c2d8b901`` after an independently verified backup.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
from typing import Any

import click
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, Engine, inspect, text

from project_workflow import config
from project_workflow.infrastructure.db.session import (
    database_revisions,
    get_engine,
    run_alembic_command,
    schema_is_ready,
)

LEGACY_REVISION = "e6a4c2d8b901"
BASELINE_REVISION = "0001_initial"
V1_WORKFLOW = "sdlc-business-tech-v1"
V2_WORKFLOW = "sdlc-business-tech-v2"
RUN_PROJECT = "RUN"

LEGACY_COLUMNS: dict[str, frozenset[str]] = {
    "agents": frozenset({"id", "name", "description", "hermes_profile"}),
    "workflows": frozenset({"id", "name", "description", "is_default"}),
    "phases": frozenset(
        {
            "id",
            "workflow_id",
            "code",
            "name",
            "description",
            "min_time_min",
            "phase_order",
            "agent_id",
            "next_recommendation",
            "parallel_with",
            "rollback_target",
            "execution_type",
            "is_seed_managed",
            "is_blocker",
            "is_delegated",
            "is_critic",
        }
    ),
    "instructions": frozenset({"id", "phase_id", "step_num", "description", "execution_type", "skills"}),
    "checks": frozenset({"id", "phase_id", "description"}),
    "evidence": frozenset({"id", "phase_id", "description"}),
    "projects": frozenset({"id", "workflow_id", "code", "name", "key_prefixes"}),
    "tasks": frozenset(
        {
            "id",
            "project_id",
            "task_key",
            "title",
            "description",
            "current_phase",
            "status",
            "created_at",
            "updated_at",
        }
    ),
    "task_history": frozenset({"id", "task_id", "phase_id", "status", "completed_at"}),
    "supervisor_runs": frozenset(
        {
            "id",
            "task_id",
            "phase_id",
            "verdict",
            "report",
            "covered",
            "missing",
            "blockers",
            "next_phase_id",
            "rollback_phase_id",
            "report_fingerprint",
            "context_snapshot",
            "response",
            "created_at",
        }
    ),
}

LEGACY_CHECKS: dict[str, frozenset[str]] = {
    "agents": frozenset(),
    "workflows": frozenset({"ck_workflows_is_default"}),
    "phases": frozenset(
        {
            "ck_phases_execution_type",
            "ck_phases_is_blocker",
            "ck_phases_is_critic",
            "ck_phases_is_delegated",
            "ck_phases_is_seed_managed",
        }
    ),
    "instructions": frozenset({"ck_instructions_execution_type"}),
    "checks": frozenset(),
    "evidence": frozenset(),
    "projects": frozenset(),
    "tasks": frozenset({"ck_tasks_status"}),
    "task_history": frozenset({"ck_task_history_status"}),
    "supervisor_runs": frozenset({"ck_supervisor_runs_verdict"}),
}

LEGACY_UNIQUES: dict[str, frozenset[tuple[str, ...]]] = {
    "agents": frozenset({("hermes_profile",)}),
    "workflows": frozenset(),
    "phases": frozenset({("workflow_id", "code")}),
    "instructions": frozenset({("phase_id", "step_num")}),
    "checks": frozenset({("phase_id", "description")}),
    "evidence": frozenset({("phase_id", "description")}),
    "projects": frozenset({("code",)}),
    "tasks": frozenset({("task_key",)}),
    "task_history": frozenset({("task_id", "phase_id")}),
    "supervisor_runs": frozenset({("task_id", "report_fingerprint")}),
}

LEGACY_FOREIGN_KEYS: dict[
    str,
    frozenset[tuple[tuple[str, ...], str, tuple[str, ...], str | None]],
] = {
    "agents": frozenset(),
    "workflows": frozenset(),
    "phases": frozenset(
        {
            (("workflow_id",), "workflows", ("id",), "CASCADE"),
            (("agent_id",), "agents", ("id",), "SET NULL"),
        }
    ),
    "instructions": frozenset({(("phase_id",), "phases", ("id",), "CASCADE")}),
    "checks": frozenset({(("phase_id",), "phases", ("id",), "CASCADE")}),
    "evidence": frozenset({(("phase_id",), "phases", ("id",), "CASCADE")}),
    "projects": frozenset({(("workflow_id",), "workflows", ("id",), "CASCADE")}),
    "tasks": frozenset({(("project_id",), "projects", ("id",), None)}),
    "task_history": frozenset(
        {
            (("task_id",), "tasks", ("id",), "CASCADE"),
            (("phase_id",), "phases", ("id",), None),
        }
    ),
    "supervisor_runs": frozenset(
        {
            (("task_id",), "tasks", ("id",), "CASCADE"),
            (("phase_id",), "phases", ("id",), None),
            (("next_phase_id",), "phases", ("id",), None),
            (("rollback_phase_id",), "phases", ("id",), None),
        }
    ),
}


def _migration_module() -> Any:
    return importlib.import_module("project_workflow.infrastructure.db.migrations.versions.0002_sdlc_business_tech_v2")


def _schema(engine: Engine | Connection) -> str | None:
    dialect = engine.dialect.name
    return config.get_settings().DB_SCHEMA if dialect == "postgresql" else None


def _qualified(connection: Connection, table: str) -> str:
    schema = _schema(connection)
    preparer = connection.dialect.identifier_preparer
    if schema:
        return f"{preparer.quote(schema)}.{preparer.quote(table)}"
    return preparer.quote(table)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_backup_manifest(path: Path, expected_sha256: str, connection: Connection) -> dict[str, Any]:
    if len(expected_sha256) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in expected_sha256):
        raise click.ClickException("backup manifest SHA-256 must contain exactly 64 hex characters")
    actual_manifest_sha = _sha256(path)
    if actual_manifest_sha.casefold() != expected_sha256.casefold():
        raise click.ClickException("backup manifest SHA-256 does not match the supplied confirmation")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"backup manifest is not readable JSON: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
        raise click.ClickException("backup manifest format_version must equal 1")
    if manifest.get("source_revision") != LEGACY_REVISION:
        raise click.ClickException(f"backup manifest source_revision must equal {LEGACY_REVISION}")
    dump = manifest.get("dump")
    if not isinstance(dump, dict):
        raise click.ClickException("backup manifest must contain dump metadata")
    dump_path = Path(str(dump.get("path") or ""))
    if not dump_path.is_absolute():
        dump_path = (path.parent / dump_path).resolve()
    dump_sha = str(dump.get("sha256") or "")
    if not dump_path.is_file() or len(dump_sha) != 64 or _sha256(dump_path) != dump_sha.casefold():
        raise click.ClickException("backup dump is missing or its SHA-256 does not match the manifest")
    database = manifest.get("database")
    if not isinstance(database, dict):
        raise click.ClickException("backup manifest must contain database identity")
    identity_query = "SELECT current_database()" if connection.dialect.name == "postgresql" else "SELECT 'sqlite'"
    actual_name = connection.execute(text(identity_query)).scalar_one()
    if database.get("name") != actual_name or database.get("schema") != (_schema(connection) or "main"):
        raise click.ClickException("backup manifest database identity does not match the migration target")
    return manifest


def _snapshot(connection: Connection) -> dict[str, Any]:
    migration = _migration_module()
    schema = _schema(connection)
    inspector = inspect(connection)
    tables = set(inspector.get_table_names(schema=schema)) - {"alembic_version"}
    actual_columns = {
        table: frozenset(column["name"] for column in inspector.get_columns(table, schema=schema)) for table in tables
    }
    if tables != set(LEGACY_COLUMNS) or actual_columns != LEGACY_COLUMNS:
        raise click.ClickException("legacy schema differs from the only supported e6a4c2d8b901 shape")
    actual_checks = {
        table: frozenset(
            str(item["name"]) for item in inspector.get_check_constraints(table, schema=schema) if item.get("name")
        )
        for table in tables
    }
    if actual_checks != LEGACY_CHECKS:
        raise click.ClickException("legacy check constraints differ from the supported schema")
    actual_uniques: dict[str, frozenset[tuple[str, ...]]] = {}
    for table in tables:
        values = {
            tuple(str(value) for value in item.get("column_names") or ())
            for item in inspector.get_unique_constraints(table, schema=schema)
        }
        values.update(
            tuple(str(value) for value in item.get("column_names") or ())
            for item in inspector.get_indexes(table, schema=schema)
            if item.get("unique")
        )
        actual_uniques[table] = frozenset(value for value in values if value)
    if actual_uniques != LEGACY_UNIQUES:
        raise click.ClickException("legacy unique constraints differ from the supported schema")
    if connection.dialect.name == "postgresql":
        actual_foreign_keys = {
            table: frozenset(
                (
                    tuple(str(value) for value in item.get("constrained_columns") or ()),
                    str(item.get("referred_table") or ""),
                    tuple(str(value) for value in item.get("referred_columns") or ()),
                    str((item.get("options") or {}).get("ondelete") or "").upper() or None,
                )
                for item in inspector.get_foreign_keys(table, schema=schema)
            )
            for table in tables
        }
        if actual_foreign_keys != LEGACY_FOREIGN_KEYS:
            raise click.ClickException("legacy foreign keys differ from the supported schema")
    blank_phases = int(
        connection.execute(
            text(f"SELECT COUNT(*) FROM {_qualified(connection, 'tasks')} WHERE length(trim(current_phase)) = 0")
        ).scalar_one()
    )
    if blank_phases:
        raise click.ClickException("legacy tasks contain blank current_phase values")
    workflow_rows = connection.execute(
        text(f"SELECT id, name FROM {_qualified(connection, 'workflows')} ORDER BY id")
    ).all()
    v1_ids = [int(row[0]) for row in workflow_rows if row[1] == V1_WORKFLOW]
    if len(v1_ids) != 1:
        raise click.ClickException("legacy database must contain exactly one sdlc-business-tech-v1")
    v1_catalog = migration._read_catalog(connection, v1_ids[0])
    expected_catalog = migration._canonical_seed(migration._seed())
    if v1_catalog != expected_catalog:
        raise click.ClickException("legacy v1 catalog differs from the immutable packaged revision")
    counts = {
        table: int(connection.execute(text(f"SELECT COUNT(*) FROM {_qualified(connection, table)}")).scalar_one())
        for table in sorted(LEGACY_COLUMNS)
    }
    return {
        "revision": LEGACY_REVISION,
        "tables": sorted(tables),
        "counts": counts,
        "v1_workflow_id": v1_ids[0],
        "v1_catalog_sha256": migration._catalog_sha256(v1_catalog),
    }


def check_legacy(engine: Engine) -> dict[str, Any]:
    if database_revisions(engine) != {LEGACY_REVISION}:
        raise click.ClickException(f"database revision must be exactly {LEGACY_REVISION}")
    with engine.connect() as connection:
        return _snapshot(connection)


def _bridge_to_initial(connection: Connection) -> None:
    context = MigrationContext.configure(connection)
    operations = Operations(context)
    schema = _schema(connection)
    with operations.batch_alter_table("workflows", schema=schema) as batch:
        batch.add_column(sa.Column("is_locked", sa.Integer(), server_default="0", nullable=False))
        batch.add_column(sa.Column("catalog_sha256", sa.String(length=64), nullable=True))
        batch.create_check_constraint("ck_workflows_is_locked", "is_locked IN (0, 1)")
        batch.create_check_constraint(
            "ck_workflows_catalog_sha256",
            "catalog_sha256 IS NULL OR length(catalog_sha256) = 64",
        )
    with operations.batch_alter_table("projects", schema=schema) as batch:
        batch.add_column(sa.Column("description", sa.Text(), server_default="", nullable=False))
    with operations.batch_alter_table("phases", schema=schema) as batch:
        batch.create_check_constraint("ck_phases_phase_order_positive", "phase_order > 0")
    with operations.batch_alter_table("instructions", schema=schema) as batch:
        batch.create_check_constraint("ck_instructions_step_num_positive", "step_num > 0")
    with operations.batch_alter_table("tasks", schema=schema) as batch:
        batch.alter_column("current_phase", existing_type=sa.Text(), server_default=None)
        batch.create_check_constraint("ck_tasks_current_phase_nonblank", "length(trim(current_phase)) > 0")
        if connection.dialect.name == "postgresql":
            batch.drop_constraint("tasks_project_id_fkey", type_="foreignkey")
            batch.create_foreign_key(
                "tasks_project_id_fkey",
                "projects",
                ["project_id"],
                ["id"],
                referent_schema=schema,
                ondelete="RESTRICT",
            )
    if connection.dialect.name == "postgresql":
        with operations.batch_alter_table("task_history", schema=schema) as batch:
            batch.drop_constraint("task_history_phase_id_fkey", type_="foreignkey")
            batch.create_foreign_key(
                "task_history_phase_id_fkey",
                "phases",
                ["phase_id"],
                ["id"],
                referent_schema=schema,
                ondelete="RESTRICT",
            )
        with operations.batch_alter_table("supervisor_runs", schema=schema) as batch:
            for constraint, column in (
                ("supervisor_runs_phase_id_fkey", "phase_id"),
                ("supervisor_runs_next_phase_id_fkey", "next_phase_id"),
                ("supervisor_runs_rollback_phase_id_fkey", "rollback_phase_id"),
            ):
                batch.drop_constraint(constraint, type_="foreignkey")
                batch.create_foreign_key(
                    constraint,
                    "phases",
                    [column],
                    ["id"],
                    referent_schema=schema,
                    ondelete="RESTRICT",
                )
    operations.drop_index(
        "uq_supervisor_runs_task_report_fingerprint",
        table_name="supervisor_runs",
        schema=schema,
    )
    operations.create_index(
        "uq_supervisor_runs_task_phase_report_fingerprint",
        "supervisor_runs",
        ["task_id", "phase_id", "report_fingerprint"],
        unique=True,
        schema=schema,
    )
    version_table = _qualified(connection, "alembic_version")
    updated = connection.execute(
        text(f"UPDATE {version_table} SET version_num = :new WHERE version_num = :old"),
        {"new": BASELINE_REVISION, "old": LEGACY_REVISION},
    )
    if updated.rowcount != 1:
        raise click.ClickException("legacy Alembic revision changed during migration")


def _lock_legacy_schema(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    for table in ["alembic_version", *sorted(LEGACY_COLUMNS)]:
        connection.execute(
            text(f"LOCK TABLE {_qualified(connection, table)} IN ACCESS EXCLUSIVE MODE")
        )


def apply_legacy(engine: Engine, manifest: Path, manifest_sha256: str) -> dict[str, Any]:
    before = check_legacy(engine)
    with engine.begin() as connection:
        _verify_backup_manifest(manifest, manifest_sha256, connection)
        _lock_legacy_schema(connection)
        # Revalidate inside the write transaction before the first DDL statement.
        if database_revisions(connection) != {LEGACY_REVISION} or _snapshot(connection) != before:
            raise click.ClickException("legacy database changed after preflight")
        _bridge_to_initial(connection)
        run_alembic_command("upgrade", connection)
        v1_id = int(before["v1_workflow_id"])
        task_table = _qualified(connection, "tasks")
        project_table = _qualified(connection, "projects")
        workflow_table = _qualified(connection, "workflows")
        if int(
            connection.execute(
                text(f"SELECT COUNT(*) FROM {task_table} WHERE workflow_id <> :v1"), {"v1": v1_id}
            ).scalar_one()
        ):
            raise click.ClickException("not every legacy run was pinned to v1")
        project_workflow = connection.execute(
            text(
                f"SELECT w.name FROM {project_table} p JOIN {workflow_table} w ON w.id = p.workflow_id "
                "WHERE p.code = :code"
            ),
            {"code": RUN_PROJECT},
        ).scalar_one()
        if project_workflow != V2_WORKFLOW:
            raise click.ClickException("RUN project was not switched to v2")
        after_counts = {
            table: int(connection.execute(text(f"SELECT COUNT(*) FROM {_qualified(connection, table)}")).scalar_one())
            for table in sorted(LEGACY_COLUMNS)
        }
        for table in ("tasks", "task_history", "supervisor_runs"):
            if after_counts[table] != before["counts"][table]:
                raise click.ClickException(f"historical row count changed for {table}")
    if not schema_is_ready(engine):
        raise click.ClickException("database is not at the exact current schema after migration")
    return {"before": before, "revision": "0002_sdlc_v2", "status": "applied"}


@click.group()
def main() -> None:
    """Administrative commands that are never executed during normal startup."""


@main.command("migrate-legacy")
@click.option("--database-url", envvar="DATABASE_URL", required=True, help="Target PostgreSQL/SQLite DSN")
@click.option("--check", "check_only", is_flag=True, help="Validate without writing")
@click.option("--apply", "apply_mode", is_flag=True, help="Apply the one supported bridge")
@click.option("--backup-manifest", type=click.Path(path_type=Path), help="Verified backup manifest JSON")
@click.option("--backup-manifest-sha256", help="Out-of-band confirmed SHA-256 of the manifest")
def migrate_legacy(
    database_url: str,
    check_only: bool,
    apply_mode: bool,
    backup_manifest: Path | None,
    backup_manifest_sha256: str | None,
) -> None:
    """Check or bridge only the deployed e6a4c2d8b901 database."""
    if check_only == apply_mode:
        raise click.UsageError("choose exactly one of --check or --apply")
    # The explicit administrative DSN is authoritative.  Settings is also used
    # for DB_SCHEMA while constructing the PostgreSQL engine, so keep its
    # process-local view in sync instead of requiring a duplicate env variable.
    os.environ["DATABASE_URL"] = database_url
    config.get_settings.cache_clear()
    engine = get_engine(database_url)
    if check_only:
        result = {"ok": True, "mode": "check", **check_legacy(engine)}
    else:
        if backup_manifest is None or backup_manifest_sha256 is None:
            raise click.UsageError("--apply requires --backup-manifest and --backup-manifest-sha256")
        result = {"ok": True, "mode": "apply", **apply_legacy(engine, backup_manifest, backup_manifest_sha256)}
    click.echo(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
