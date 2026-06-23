"""Tests for DB session factory and UI template helpers."""
from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from project_workflow.infrastructure.db.session import (
    _is_sqlite,
    _normalize_url,
    ensure_schema,
    get_engine,
    get_session,
    get_sessionmaker,
    reset_engine,
)
from project_workflow.interfaces.ui import templates as templates_module
from project_workflow.interfaces.ui.templates import _group_instructions, _tojson_unicode


class TestSessionHelpers:
    def test_is_sqlite_detects_sqlite(self):
        assert _is_sqlite("sqlite:///tmp/db.sqlite")
        assert _is_sqlite("sqlite:///:memory:")
        assert not _is_sqlite("postgresql://user:pass@localhost/db")
        assert not _is_sqlite("mysql://user:pass@localhost/db")

    def test_normalize_url_passes_through_valid_urls(self):
        assert _normalize_url("postgresql://u:p@h/d") == "postgresql://u:p@h/d"
        assert _normalize_url("sqlite:///tmp/db.sqlite") == "sqlite:///tmp/db.sqlite"

    def test_normalize_url_converts_path_to_sqlite(self):
        assert _normalize_url("/tmp/db.sqlite") == "sqlite:////tmp/db.sqlite"
        assert _normalize_url("relative.db") == "sqlite:///relative.db"
        assert _normalize_url(":memory:") == "sqlite:///:memory:"

    def test_get_engine_returns_same_instance_for_same_url(self, tmp_path):
        reset_engine()
        db = tmp_path / "test.db"
        e1 = get_engine(f"sqlite:///{db}")
        e2 = get_engine(f"sqlite:///{db}")
        assert e1 is e2
        assert isinstance(e1, Engine)
        reset_engine()

    def test_get_engine_creates_new_instance_after_url_change(self, tmp_path):
        reset_engine()
        db1 = tmp_path / "a.db"
        db2 = tmp_path / "b.db"
        e1 = get_engine(f"sqlite:///{db1}")
        e2 = get_engine(f"sqlite:///{db2}")
        assert e1 is not e2
        reset_engine()

    def test_get_session_returns_active_session(self, tmp_path):
        reset_engine()
        db = tmp_path / "test.db"
        sess = get_session(f"sqlite:///{db}")
        assert isinstance(sess, Session)
        # SQLite pragmas were applied by event listener.
        from sqlalchemy import text
        pragma = sess.execute(text("PRAGMA journal_mode")).scalar()
        assert pragma is not None
        sess.close()
        reset_engine()

    def test_get_sessionmaker_returns_callable(self, tmp_path):
        reset_engine()
        db = tmp_path / "test.db"
        maker = get_sessionmaker(f"sqlite:///{db}")
        sess = maker()
        assert isinstance(sess, Session)
        sess.close()
        reset_engine()

    def test_ensure_schema_creates_tables(self, tmp_path):
        reset_engine()
        db = tmp_path / "test.db"
        engine = get_engine(f"sqlite:///{db}")
        ensure_schema(engine)
        with engine.connect() as conn:
            from sqlalchemy import text
            tables = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).scalars().all()
        assert "workflows" in tables
        assert "phases" in tables
        reset_engine()

    def test_reset_engine_clears_cache(self, tmp_path):
        db = tmp_path / "test.db"
        e1 = get_engine(f"sqlite:///{db}")
        reset_engine()
        e2 = get_engine(f"sqlite:///{db}")
        assert e1 is not e2
        reset_engine()


class TestTemplateHelpers:
    def test_tojson_unicode_escapes_unicode(self):
        value = {"text": "привет"}
        out = _tojson_unicode(value)
        assert "привет" in str(out)
        assert "\\u" not in str(out)

    def test_tojson_unicode_default_handler(self):
        class Custom:
            value = 42

            def __str__(self):
                return f"custom-{self.value}"

        out = _tojson_unicode({"x": Custom()})
        assert "custom-42" in str(out)

    def test_group_instructions_groups_parallel_with_previous(self):
        instructions = [
            {"id": 1, "execution_type": "sync"},
            {"id": 2, "execution_type": "parallel"},
            {"id": 3, "execution_type": "parallel"},
            {"id": 4, "execution_type": "sync"},
            {"id": 5, "execution_type": "sync"},
        ]
        groups = _group_instructions(instructions)
        assert len(groups) == 3
        assert [g["id"] for g in groups[0]] == [1, 2, 3]
        assert [g["id"] for g in groups[1]] == [4]
        assert [g["id"] for g in groups[2]] == [5]

    def test_group_instructions_returns_empty_for_none(self):
        assert _group_instructions(None) == []
        assert _group_instructions([]) == []

    def test_group_instructions_single_item(self):
        out = _group_instructions([{"id": 1}])
        assert out == [[{"id": 1}]]

    def test_templates_env_exposes_filters(self):
        assert "tojson_unicode" in templates_module.env.filters
        assert "group_instructions" in templates_module.env.filters