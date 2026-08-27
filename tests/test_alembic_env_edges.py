"""Direct tests for Alembic env.py branch behavior."""

from __future__ import annotations

import sys
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from project_workflow import config as config_module

pytestmark = [pytest.mark.unit]


class _FakeAlembicConfig:
    config_file_name = None

    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}
        self.options: dict[str, str] = {}

    def set_main_option(self, key: str, value: str) -> None:
        self.options[key] = value

    def get_main_option(self, key: str) -> str:
        return self.options.get(key, "")


class _FakeContext:
    def __init__(self, *, offline: bool) -> None:
        self.config = _FakeAlembicConfig()
        self.offline = offline
        self.configure_kwargs: dict[str, Any] | None = None
        self.ran_migrations = False

    def is_offline_mode(self) -> bool:
        return self.offline

    def configure(self, **kwargs: Any) -> None:
        self.configure_kwargs = kwargs

    def begin_transaction(self):
        return nullcontext()

    def run_migrations(self) -> None:
        self.ran_migrations = True


class _FakeConnection:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.dialect = SimpleNamespace(
            name="postgresql",
            identifier_preparer=SimpleNamespace(quote=lambda value: f'"{value}"'),
        )

    def in_transaction(self) -> bool:
        return True

    def execute(self, statement: Any) -> None:
        self.executed.append(str(statement))


def _load_env(fake_context: _FakeContext, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    fake_alembic = ModuleType("alembic")
    fake_alembic.context = fake_context
    monkeypatch.setitem(sys.modules, "alembic", fake_alembic)
    path = Path(__file__).parents[1] / "project_workflow" / "infrastructure" / "db" / "migrations" / "env.py"
    namespace = {
        "__file__": str(path),
        "__name__": "project_workflow.infrastructure.db.migrations.env_under_test",
        "__package__": "project_workflow.infrastructure.db.migrations",
    }
    original_get_settings = config_module.get_settings
    config_module.get_settings = lambda: SimpleNamespace(DB_SCHEMA="quality_schema")  # type: ignore[method-assign]
    try:
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    finally:
        config_module.get_settings = original_get_settings  # type: ignore[method-assign]
    return namespace


def test_alembic_env_offline_configures_postgres_schema(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    fake_context = _FakeContext(offline=True)

    _load_env(fake_context, monkeypatch)

    assert fake_context.config.options["sqlalchemy.url"] == "postgresql+psycopg://u:p@localhost/db"
    assert fake_context.configure_kwargs is not None
    assert fake_context.configure_kwargs["literal_binds"] is True
    assert fake_context.configure_kwargs["version_table_schema"] == "quality_schema"
    assert fake_context.ran_migrations is True


def test_alembic_env_online_supplied_connection_selects_postgres_schema(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    fake_context = _FakeContext(offline=False)
    connection = _FakeConnection()
    fake_context.config.attributes["connection"] = connection

    _load_env(fake_context, monkeypatch)

    assert connection.executed == [
        'CREATE SCHEMA IF NOT EXISTS "quality_schema"',
        'SET search_path TO "quality_schema"',
    ]
    assert fake_context.configure_kwargs is not None
    assert fake_context.configure_kwargs["connection"] is connection
    assert fake_context.configure_kwargs["version_table_schema"] == "quality_schema"
    assert fake_context.ran_migrations is True


def test_alembic_env_online_requires_database_url_without_supplied_connection(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    fake_context = _FakeContext(offline=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        _load_env(fake_context, monkeypatch)
