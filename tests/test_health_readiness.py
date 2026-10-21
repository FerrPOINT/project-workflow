"""Regression checks through the public health endpoint on disposable schemas."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from project_workflow import config
from project_workflow.infrastructure.db import session
from project_workflow.interfaces.ui.app import create_app


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'health.db'}")
    config.get_settings.cache_clear()
    session.reset_engine()
    engine = session.get_engine()
    session.ensure_migrated(engine)
    return engine, TestClient(create_app())


def test_repeated_health_does_not_repeat_full_schema_reflection(tmp_path, monkeypatch):
    engine, client = _client(tmp_path, monkeypatch)
    with patch.object(session, "schema_is_ready", wraps=session.schema_is_ready) as deep:
        assert client.get("/health").status_code == 200
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num=version_num"))
        assert client.get("/health").status_code == 200
        assert deep.call_count == 1


@pytest.mark.parametrize("change", [
    "ALTER TABLE projects ADD COLUMN unexpected_health_column TEXT",
    "CREATE TABLE unexpected_health_table(id INTEGER)",
    "UPDATE alembic_version SET version_num='unknown_health_revision'",
])
def test_health_rejects_schema_drift_immediately_after_cached_success(change, tmp_path, monkeypatch):
    engine, client = _client(tmp_path, monkeypatch)
    assert client.get("/health").status_code == 200
    with engine.begin() as connection:
        connection.execute(text(change))
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["error_code"] == "schema-not-ready"


def test_health_rechecks_revision_and_recovers_after_repair(tmp_path, monkeypatch):
    engine, client = _client(tmp_path, monkeypatch)
    assert client.get("/health").status_code == 200
    head = session.migration_head()
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='unknown_health_revision'"))
    assert client.get("/health").status_code == 503
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num=:head"), {"head": head})
    assert client.get("/health").status_code == 200


def test_health_does_not_hide_database_failure_after_cached_success(tmp_path, monkeypatch):
    engine, client = _client(tmp_path, monkeypatch)
    assert client.get("/health").status_code == 200
    with patch.object(engine, "connect", side_effect=OperationalError("connect", {}, Exception("private-detail"))):
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["error_code"] == "database-unavailable"
    assert "private-detail" not in response.text
    assert client.get("/health").status_code == 200


def test_health_rejects_schema_change_during_full_validation(tmp_path, monkeypatch):
    engine, client = _client(tmp_path, monkeypatch)
    original = session.schema_is_ready

    def validate_then_change(target):
        ready = original(target)
        with target.begin() as connection:
            connection.execute(text("ALTER TABLE projects ADD COLUMN changed_during_health TEXT"))
        return ready

    with patch.object(session, "schema_is_ready", side_effect=validate_then_change):
        assert client.get("/health").status_code == 503
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE projects DROP COLUMN changed_during_health"))
    assert client.get("/health").status_code == 200


def test_concurrent_health_requests_share_one_full_validation(tmp_path, monkeypatch):
    _engine, client = _client(tmp_path, monkeypatch)
    with patch.object(session, "schema_is_ready", wraps=session.schema_is_ready) as deep:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: client.get("/health"), range(2)))
        assert [response.status_code for response in responses] == [200, 200]
        assert deep.call_count == 1
