"""Real request transaction and deferred COMMIT, never application data."""
from __future__ import annotations

import importlib
import os
import time
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.request_clock import RequestClock, current_clock

pytestmark = pytest.mark.integration


def test_original_application_clock_survives_wait_inside_real_postgres_commit(monkeypatch):
    url = os.environ.get("WORKFLOW_APPLICATION_CLOCK_TEST_URL")
    if not url:
        pytest.skip("Explicit disposable PostgreSQL fixture URL required")
    parsed = make_url(url)
    assert parsed.database == "request_clock_fixture", "Only the dedicated empty QA database is allowed"
    monkeypatch.delenv("PROJECT_WORKFLOW_SPACES__ENABLED", raising=False)
    schema = "test_application_clock_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        m.Base.metadata.create_all(engine)
        migration = importlib.import_module(
            "project_workflow.infrastructure.db.migrations.versions.0017_human_application_clock")
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            connection.execute(text("CREATE SEQUENCE qa_commit_entered"))
            connection.execute(text("""
                CREATE FUNCTION qa_delay_commit() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  PERFORM nextval('qa_commit_entered');
                  PERFORM pg_sleep(0.45);
                  RETURN NEW;
                END; $$
            """))
            connection.execute(text(
                "CREATE CONSTRAINT TRIGGER a_qa_commit_delay AFTER INSERT ON workflows "
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION qa_delay_commit()"))
        token = current_clock.set(RequestClock(time.monotonic() + 0.3, time.time() + 0.3))
        uow = SAUnitOfWork(engine)
        try:
            uow.session.add(m.Workflow(key="expires-during-commit", name="Must roll back"))
            with pytest.raises(DBAPIError) as rejected:
                uow.commit()
            assert getattr(rejected.value.orig, "sqlstate", None) == "42501"
        finally:
            uow.rollback()
            uow.close()
            current_clock.reset(token)

        with engine.connect() as connection:
            # A sequence is intentionally nontransactional: it proves COMMIT entered the delay.
            assert connection.scalar(text("SELECT is_called FROM qa_commit_entered")) is True
            assert connection.scalar(select(m.Workflow).where(m.Workflow.key == "expires-during-commit")) is None

        token = current_clock.set(RequestClock(time.monotonic() + 20, time.time() + 20))
        try:
            with SAUnitOfWork(engine) as uow:
                uow.session.add(m.Workflow(key="fresh", name="Fresh permit succeeds"))
        finally:
            current_clock.reset(token)
        with SAUnitOfWork(engine) as uow:
            # Reusing a connection never inherits the preceding request's clock.
            assert uow.session.scalar(text(
                "SELECT nullif(current_setting('pdlc.workflow_request_until', true), '')")) is None
            uow.session.add(m.Workflow(key="native", name="Native retains its own authorization"))
        with engine.connect() as connection:
            assert set(connection.scalars(select(m.Workflow.key))) == {"fresh", "native"}
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
