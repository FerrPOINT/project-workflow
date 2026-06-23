"""Integration tests against a real PostgreSQL instance.

These tests are skipped by default (`-m 'not integration'`).
Run them explicitly with:
    pytest -m integration tests/test_postgres_integration.py -v
"""
from __future__ import annotations

import os

import pytest
import psycopg

from project_workflow import config as config_module
from project_workflow.infrastructure.db.session import (
    ensure_migrated,
    ensure_schema,
    get_engine,
    reset_engine,
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
    base_url = (
        f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{db_name}"
    )

    admin_conn = psycopg.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_ADMIN_DB, user=PG_USER, password=PG_PASSWORD
    )
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

    yield base_url

    reset_engine()
    admin_conn = psycopg.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_ADMIN_DB, user=PG_USER, password=PG_PASSWORD
    )
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
            version = conn.execute(
                text("SELECT version_num FROM project_workflow.alembic_version")
            ).scalar()
        assert version is not None


@pytest.mark.integration
class TestPostgresUoW:
    def test_create_and_read_workflow_project_task(self, pg_url):
        uow = SAUnitOfWork(pg_url)
        with uow:
            uow.create_all()
            wf_id = uow.workflows.create(
                {"name": "Test Workflow", "description": "Test", "is_default": True}
            )
            workflows = {w.name: w.id for w in uow.workflows.list()}
            assert workflows.get("Test Workflow") == wf_id

            proj_id = uow.projects.create(
                {"workflow_id": wf_id, "code": "TST", "name": "Default"}
            )
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
            default_wf_id = uow.workflows.create(
                {"name": "Default", "description": "default", "is_default": True}
            )
            uow.projects.create(
                {"workflow_id": default_wf_id, "code": "DEFAULT", "name": "Default Project"}
            )
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
            wf_id = uow.workflows.create(
                {"name": "Rollback WF", "description": "rollback"}
            )
            uow.rollback()

        with uow:
            ids = {w.id for w in uow.workflows.list()}
            assert wf_id not in ids
