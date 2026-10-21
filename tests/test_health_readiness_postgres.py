"""Real PostgreSQL invalidation and query-budget checks for public health."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from project_workflow.infrastructure.db import session
from project_workflow.interfaces.ui.app import create_app
from tests.test_postgres_integration import pg_url as _shared_pg_url

pg_url = _shared_pg_url
pytestmark = pytest.mark.integration


def _client(pg_url):
    engine = session.get_engine(pg_url)
    session.ensure_migrated(engine)
    return engine, TestClient(create_app())


def test_postgres_warm_health_reuses_exact_validation_with_bounded_queries(pg_url):
    engine, client = _client(pg_url)
    with patch.object(session, "schema_is_ready", wraps=session.schema_is_ready) as deep:
        assert client.get("/health").status_code == 200
        queries = []

        def record(_conn, _cursor, statement, _parameters, _context, _many):
            queries.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            for _ in range(3):
                assert client.get("/health").status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert deep.call_count == 1
        assert len(queries) <= 18


@pytest.mark.parametrize("change", [
    "ALTER TABLE projects ADD COLUMN unexpected_health_column TEXT",
    "ALTER TABLE projects ALTER COLUMN name TYPE text",
    "ALTER TABLE projects ALTER COLUMN name SET DEFAULT 'unexpected-default'",
    "CREATE INDEX health_extra_index ON projects(name)",
    "CREATE TABLE unexpected_health_table(id integer)",
    "CREATE FUNCTION legacy_metadata_readonly() RETURNS trigger LANGUAGE plpgsql "
    "AS $$BEGIN RETURN NEW; END;$$",
    "UPDATE alembic_version SET version_num='unknown_health_revision'",
])
def test_postgres_health_rejects_ddl_or_revision_drift_without_ttl(pg_url, change):
    engine, client = _client(pg_url)
    assert client.get("/health").status_code == 200
    with engine.begin() as connection:
        connection.execute(text(change))
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["error_code"] == "schema-not-ready"


def test_postgres_health_recovers_after_ddl_repair(pg_url):
    engine, client = _client(pg_url)
    assert client.get("/health").status_code == 200
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE unexpected_health_table(id integer)"))
    assert client.get("/health").status_code == 503
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE unexpected_health_table"))
    assert client.get("/health").status_code == 200


def test_postgres_neighbor_namespace_and_same_revision_dml_do_not_repeat_validation(pg_url):
    engine, client = _client(pg_url)
    with patch.object(session, "schema_is_ready", wraps=session.schema_is_ready) as deep:
        assert client.get("/health").status_code == 200
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num=version_num"))
            connection.execute(text('CREATE SCHEMA "Health_Neighbor"'))
            connection.execute(text('CREATE TABLE "Health_Neighbor".extra(id integer)'))
        assert client.get("/health").status_code == 200
        assert deep.call_count == 1
