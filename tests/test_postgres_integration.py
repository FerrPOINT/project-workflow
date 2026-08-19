"""Integration tests against a real PostgreSQL instance.

These tests are skipped by default (`-m 'not integration'`).
Run them explicitly with:
    pytest -m integration tests/test_postgres_integration.py -v
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

import psycopg
import pytest
from sqlalchemy import inspect

from project_workflow import config as config_module
from project_workflow.infrastructure.db.session import (
    ensure_migrated,
    ensure_schema,
    get_engine,
    reset_engine,
    run_alembic_command,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork

PG_HOST = os.environ.get("PGHOST", "localhost")
PG_PORT = int(os.environ.get("PGPORT", "5432"))
PG_USER = os.environ.get("PGUSER", "project_workflow")
PG_PASSWORD = os.environ.get("PGPASSWORD", "project_workflow")
PG_ADMIN_DB = os.environ.get("PGDATABASE", "project_workflow")


@pytest.fixture(scope="function")
def pg_url(monkeypatch):
    """Create a fresh PostgreSQL database and yield a SQLAlchemy URL for it."""
    if not PG_PASSWORD:
        pytest.skip("PGPASSWORD is not set")
    pid = os.getpid()
    db_name = f"project_workflow_test_{pid}"
    base_url = f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{db_name}"

    admin_conn = psycopg.connect(host=PG_HOST, port=PG_PORT, dbname=PG_ADMIN_DB, user=PG_USER, password=PG_PASSWORD)
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute("SET idle_in_transaction_session_timeout = 0")
        cur.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {db_name}")
    admin_conn.close()

    monkeypatch.setenv("DATABASE_URL", base_url)
    monkeypatch.setenv("DB_SCHEMA", "project_workflow")
    config_module.get_settings.cache_clear()
    reset_engine()
    from project_workflow.infrastructure.db.schema import mark_catalog_not_ensured

    mark_catalog_not_ensured()

    yield base_url

    reset_engine()
    admin_conn = psycopg.connect(host=PG_HOST, port=PG_PORT, dbname=PG_ADMIN_DB, user=PG_USER, password=PG_PASSWORD)
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
    admin_conn.close()


@pytest.mark.integration
class TestPostgresSession:
    def test_get_engine_postgresql(self, pg_url):
        engine = get_engine(pg_url)
        assert engine.dialect.name == "postgresql"
        assert engine.url.database == pg_url.rsplit("/", 1)[-1]

    def test_ensure_schema_creates_tables(self, pg_url):
        engine = get_engine(pg_url)
        ensure_schema(engine)
        with engine.connect() as conn:
            from sqlalchemy import text

            rows = conn.execute(
                text("""SELECT table_name FROM information_schema.tables
                       WHERE table_schema='project_workflow'""")
            ).fetchall()
            tables = {r[0] for r in rows}
        assert "workflows" in tables
        assert "projects" in tables
        assert "tasks" in tables

    def test_ensure_migrated_applies_migrations(self, pg_url):
        engine = get_engine(pg_url)
        ensure_migrated(engine)
        with engine.connect() as conn:
            from sqlalchemy import text

            version = conn.execute(text("SELECT version_num FROM project_workflow.alembic_version")).scalar()
        assert version is not None

    def test_upgrade_preserves_existing_run_and_creates_unique_index(self, pg_url):
        from project_workflow.infrastructure.db import schema
        from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

        engine = get_engine(pg_url)
        ensure_migrated(engine)
        uow = SAUnitOfWork(engine)
        schema.ensure_phase_catalog(uow)
        bootstrap_default_project(uow)
        project = uow.projects.get_by_code("TASK")
        phase = uow.phases.list(workflow_id=project.workflow_id)[0]
        task_id = uow.tasks.create(
            {"project_id": project.id, "task_key": "TASK-MIGRATION", "current_phase": phase.code}
        )
        run_id = uow.supervisor_runs.create(
            {"task_id": task_id, "phase_id": phase.id, "verdict": "partial", "report": "old"}
        )
        uow.commit()
        uow.close()

        run_alembic_command("downgrade", engine, "becf90549ae1")
        assert "report_fingerprint" not in {
            column["name"] for column in inspect(engine).get_columns("supervisor_runs", schema="project_workflow")
        }
        ensure_migrated(engine)
        ensure_migrated(engine)

        columns = {
            column["name"] for column in inspect(engine).get_columns("supervisor_runs", schema="project_workflow")
        }
        indexes = {index["name"] for index in inspect(engine).get_indexes("supervisor_runs", schema="project_workflow")}
        assert "report_fingerprint" in columns
        assert "uq_supervisor_runs_task_report_fingerprint" in indexes
        check_uow = SAUnitOfWork(engine)
        try:
            assert check_uow.supervisor_runs.list(task_id=task_id)[0].id == run_id
        finally:
            check_uow.close()


@pytest.mark.integration
class TestPostgresUoW:
    def test_create_and_read_workflow_project_task(self, pg_url):
        uow = SAUnitOfWork(pg_url)
        with uow:
            uow.create_all()
            wf_id = uow.workflows.create({"name": "Test Workflow", "description": "Test", "is_default": True})
            workflows = {w.name: w.id for w in uow.workflows.list()}
            assert workflows.get("Test Workflow") == wf_id

            proj_id = uow.projects.create({"workflow_id": wf_id, "code": "TST", "name": "Default"})
            projects = {p.code: p.id for p in uow.projects.list()}
            assert projects.get("TST") == proj_id

            task_id = uow.tasks.create(
                {
                    "project_id": proj_id,
                    "code": "TST-1",
                    "task_key": "TST-1",
                    "title": "First task",
                }
            )
            tasks = {t.task_key: t.id for t in uow.tasks.list()}
            assert tasks.get("TST-1") == task_id
            uow.commit()

    def test_ensure_phase_catalog_seeds_phases(self, pg_url):
        from project_workflow.infrastructure.db import schema as schema_module

        uow = SAUnitOfWork(pg_url)
        with uow:
            uow.create_all()
            default_wf_id = uow.workflows.create({"name": "Default", "description": "default", "is_default": True})
            uow.projects.create({"workflow_id": default_wf_id, "code": "DEFAULT", "name": "Default Project"})
            uow.commit()

        schema_module.ensure_phase_catalog(uow)
        with uow:
            default_wf = uow.workflows.get_default()
            phases = uow.phases.list(workflow_id=default_wf.id)
            codes = {p.code for p in phases}
            assert "0.5" in codes

    def test_uow_commit_and_rollback(self, pg_url):
        uow = SAUnitOfWork(pg_url)
        with uow:
            uow.create_all()
            wf_id = uow.workflows.create({"name": "Rollback WF", "description": "rollback"})
            uow.rollback()

        with uow:
            ids = {w.id for w in uow.workflows.list()}
            assert wf_id not in ids


def _pass_response(user_prompt: str) -> dict:
    item_ids = []
    for line in user_prompt.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and "] " in stripped:
            item_ids.append(stripped[1:].split("] ", 1)[0])
    return {
        "verdict": "PASS",
        "covered": item_ids,
        "missing": [],
        "blockers": [],
        "message": "ok",
        "confidence": 1.0,
    }


def _prepare_concurrent_task(pg_url: str, task_key: str) -> None:
    from project_workflow.infrastructure.db import schema
    from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

    engine = get_engine(pg_url)
    ensure_migrated(engine)
    uow = SAUnitOfWork(engine)
    schema.ensure_phase_catalog(uow)
    bootstrap_default_project(uow)
    project = uow.projects.get_by_code("TASK")
    phase = uow.phases.list(workflow_id=project.workflow_id)[0]
    uow.tasks.create({"project_id": project.id, "task_key": task_key, "current_phase": phase.code})
    uow.commit()
    uow.close()


@pytest.mark.integration
@pytest.mark.parametrize("same_report", [True, False])
def test_concurrent_reports_create_one_transition_and_run(pg_url, same_report):
    from project_workflow.wizard import WizardEngine

    task_key = "TASK-CONCURRENT"
    _prepare_concurrent_task(pg_url, task_key)
    barrier = Barrier(2)

    def evaluate(report: str):
        uow = SAUnitOfWork(pg_url)
        engine = WizardEngine(task_key, uow=uow, create_if_missing=False)
        barrier.wait()
        try:
            return engine.evaluate(report)
        finally:
            uow.close()

    reports = ["same report", "same report" if same_report else "different report"]
    with (
        patch(
            "project_workflow.wizard.evaluate.OllamaClient.chat",
            side_effect=lambda *_args, **kwargs: _pass_response(kwargs["user"]),
        ),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(evaluate, reports))

    uow = SAUnitOfWork(pg_url)
    task = uow.tasks.get_by_key(task_key)
    runs = uow.supervisor_runs.list(task_id=task.id)
    history = uow.tasks.get_history(task.id)
    uow.close()

    assert len(runs) == 1
    assert history
    assert sum(result["verdict"] == "PASS" for result in results) == (2 if same_report else 1)
    if same_report:
        assert sum(result["replayed"] is True for result in results) == 1
    else:
        assert sum(result["verdict"] == "BLOCKED" and result["retryable"] is True for result in results) == 1
