"""Safety contract for the explicit e6a4c2d8b901 bridge."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from click import ClickException
from click.testing import CliRunner
from sqlalchemy import create_engine, text

from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.session import database_revisions, run_alembic_command
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project
from project_workflow.interfaces import admin_legacy
from project_workflow.interfaces.admin_legacy import apply_legacy, check_legacy, main


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legacy_engine(tmp_path: Path):
    database = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{database}")
    run_alembic_command("upgrade", engine, "0001_initial")
    with engine.begin() as connection:
        uow = SAUnitOfWork(connection)
        schema.ensure_phase_catalog(uow)
        bootstrap_default_project(uow)
        uow.commit()
        project_id = int(connection.execute(text("SELECT id FROM projects WHERE code = 'RUN'")).scalar_one())
        phase_id = int(
            connection.execute(
                text(
                    "SELECT p.id FROM phases p JOIN workflows w ON w.id = p.workflow_id "
                    "WHERE w.name = 'sdlc-business-tech-v1' AND p.code = '1.INTAKE'"
                )
            ).scalar_one()
        )
        task_id = int(
            connection.execute(
                text(
                    "INSERT INTO tasks (project_id, task_key, title, current_phase, status) "
                    "VALUES (:project, 'RUN-LEGACY', 'Legacy', '1.INTAKE', 'active') RETURNING id"
                ),
                {"project": project_id},
            ).scalar_one()
        )
        connection.execute(
            text("INSERT INTO task_history (task_id, phase_id, status) VALUES (:task, :phase, 'pending')"),
            {"task": task_id, "phase": phase_id},
        )

    # The production bridge is PostgreSQL-only.  This fixture explicitly
    # disables FK checks only while Alembic reshapes the SQLite test schema;
    # every engine returned to a test gets the normal FK-on connect hook.
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 0
        operations = Operations(MigrationContext.configure(connection))
        with operations.batch_alter_table("agents") as batch:
            batch.alter_column("description", existing_type=sa.String(), server_default=None)
        with operations.batch_alter_table("workflows") as batch:
            batch.alter_column("description", existing_type=sa.String(), server_default=None)
            batch.drop_constraint("ck_workflows_catalog_sha256", type_="check")
            batch.drop_constraint("ck_workflows_is_locked", type_="check")
            batch.drop_column("catalog_sha256")
            batch.drop_column("is_locked")
        with operations.batch_alter_table("projects") as batch:
            batch.drop_column("description")
        with operations.batch_alter_table("phases") as batch:
            batch.drop_constraint("ck_phases_phase_order_positive", type_="check")
        with operations.batch_alter_table("instructions") as batch:
            batch.drop_constraint("ck_instructions_step_num_positive", type_="check")
        with operations.batch_alter_table("tasks") as batch:
            batch.drop_constraint("ck_tasks_current_phase_nonblank", type_="check")
            batch.alter_column("current_phase", existing_type=sa.Text(), server_default="-1")
        operations.drop_index(
            "uq_supervisor_runs_task_phase_report_fingerprint",
            table_name="supervisor_runs",
        )
        operations.create_index(
            "uq_supervisor_runs_task_report_fingerprint",
            "supervisor_runs",
            ["task_id", "report_fingerprint"],
            unique=True,
        )
        connection.execute(text("UPDATE alembic_version SET version_num = 'e6a4c2d8b901'"))
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    engine.dispose()
    return create_engine(f"sqlite:///{database}"), database


def _backup_manifest(tmp_path: Path, database: Path) -> tuple[Path, str]:
    dump = tmp_path / "legacy.dump"
    shutil.copy2(database, dump)
    manifest = tmp_path / "backup-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "format_version": 1,
                "source_revision": "e6a4c2d8b901",
                "database": {"name": "sqlite", "schema": "main"},
                "dump": {"path": dump.name, "sha256": _sha256(dump)},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest, _sha256(manifest)


def test_check_and_apply_supported_legacy_database(tmp_path):
    engine, database = _legacy_engine(tmp_path)
    checked = check_legacy(engine)
    assert checked["revision"] == "e6a4c2d8b901"
    assert checked["counts"]["tasks"] == 1
    assert checked["v1_catalog_sha256"] == "c12e564f8896754387260c38f9706ae1776212c6a8a5504a3280021db80d039c"

    manifest, manifest_sha = _backup_manifest(tmp_path, database)
    result = apply_legacy(engine, manifest, manifest_sha)

    assert result["status"] == "applied"
    assert database_revisions(engine) == {"0002_sdlc_v2"}
    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT w.name FROM tasks t JOIN workflows w ON w.id = t.workflow_id "
                    "WHERE t.task_key = 'RUN-LEGACY'"
                )
            ).scalar_one()
            == "sdlc-business-tech-v1"
        )
        assert (
            connection.execute(
                text("SELECT w.name FROM projects p JOIN workflows w ON w.id = p.workflow_id WHERE p.code = 'RUN'")
            ).scalar_one()
            == "sdlc-business-tech-v2"
        )
        assert connection.execute(
            text("SELECT catalog_sha256 FROM workflows WHERE name = 'sdlc-business-tech-v1'")
        ).scalar_one() == checked["v1_catalog_sha256"]


def test_check_rejects_unknown_revision_without_writes(tmp_path):
    engine, _ = _legacy_engine(tmp_path)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'unknown'"))
    with pytest.raises(ClickException, match="revision must be exactly"):
        check_legacy(engine)
    assert database_revisions(engine) == {"unknown"}


def test_apply_rejects_unconfirmed_manifest_before_writes(tmp_path):
    engine, database = _legacy_engine(tmp_path)
    manifest, _ = _backup_manifest(tmp_path, database)
    with pytest.raises(ClickException, match="does not match"):
        apply_legacy(engine, manifest, "0" * 64)
    assert database_revisions(engine) == {"e6a4c2d8b901"}


def test_admin_entrypoint_exposes_only_explicit_migrate_legacy_command():
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "migrate-legacy" in result.output


def test_admin_explicit_database_url_is_authoritative_without_duplicate_env(monkeypatch):
    explicit_url = "postgresql+psycopg://operator:secret@database/project_workflow"
    observed: dict[str, str] = {}

    def fake_get_engine(url: str):
        observed["argument"] = url
        observed["settings"] = admin_legacy.config.get_settings().DATABASE_URL
        return object()

    monkeypatch.delenv("DATABASE_URL", raising=False)
    admin_legacy.config.get_settings.cache_clear()
    monkeypatch.setattr(admin_legacy, "get_engine", fake_get_engine)
    monkeypatch.setattr(
        admin_legacy,
        "check_legacy",
        lambda _engine: {"revision": "e6a4c2d8b901"},
    )

    result = CliRunner().invoke(
        main,
        ["migrate-legacy", "--database-url", explicit_url, "--check"],
        env={"DB_SCHEMA": "project_workflow"},
    )

    assert result.exit_code == 0, result.output
    assert observed == {"argument": explicit_url, "settings": explicit_url}
