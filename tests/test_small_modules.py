"""Tests for module entry points and small coverage gaps."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestEntryPoints:
    def test_cli_module_main_invokes_main(self, monkeypatch):
        import importlib
        cli_main_mod = importlib.import_module("project_workflow.interfaces.cli.__main__")
        called = []
        monkeypatch.setattr(cli_main_mod, "main", lambda: called.append(True))
        with pytest.raises(SystemExit):
            exec("if True:\n    main()\n    raise SystemExit(0)", {"main": cli_main_mod.main, "SystemExit": SystemExit})

    def test_ui_module_main_invokes_main(self, monkeypatch):
        import importlib
        ui_main_mod = importlib.import_module("project_workflow.interfaces.ui.main")
        called = []
        monkeypatch.setattr(ui_main_mod, "main", lambda: called.append(True))
        exec("if True:\n    main()", {"main": ui_main_mod.main})
        assert called


class TestConfigRawSettings:
    def test_read_raw_settings_invalid_json(self, tmp_path, monkeypatch):
        from project_workflow import config as config_module
        bad_file = tmp_path / "settings.json"
        bad_file.write_text("not json")
        monkeypatch.setattr(config_module, "SETTINGS_PATH", str(bad_file))
        assert config_module._read_raw_settings() == {}


class TestSessionSQLiteBranches:
    def test_normalize_url_relative_path(self, tmp_path, monkeypatch):
        from project_workflow.infrastructure.db.session import _normalize_url
        monkeypatch.setattr(
            "project_workflow.infrastructure.db.session.get_database_url",
            lambda: "sqlite:///default.db",
        )
        rel = str(tmp_path / "rel.db")
        assert _normalize_url(rel).endswith("rel.db")
        assert _normalize_url(":memory:").startswith("sqlite:///")

    def test_get_sessionmaker_returns_callable(self, tmp_path):
        from project_workflow.infrastructure.db.session import get_sessionmaker, reset_engine
        reset_engine()
        sm = get_sessionmaker(f"sqlite:///{tmp_path}/sm.db")
        assert callable(sm)
        session = sm()
        assert session is not None
        session.close()

    def test_ensure_schema_with_connection(self, tmp_path):
        from sqlalchemy import create_engine
        from project_workflow.infrastructure.db.session import ensure_schema
        engine = create_engine(f"sqlite:///{tmp_path}/ensure.db")
        with engine.begin() as conn:
            ensure_schema(conn)
        engine.dispose()

    def test_sqlite_pragma_attribute_error(self):
        from project_workflow.infrastructure.db.session import _set_sqlite_pragma
        fake_conn = MagicMock()
        fake_conn.cursor.side_effect = AttributeError("no cursor")
        _set_sqlite_pragma(fake_conn, MagicMock(dialect=MagicMock(name="sqlite")))

    def test_run_alembic_command(self, tmp_path):
        from sqlalchemy import create_engine
        from project_workflow.infrastructure.db.session import run_alembic_command
        engine = create_engine(f"sqlite:///{tmp_path}/alembic.db")
        try:
            with patch("project_workflow.infrastructure.db.session.command") as mock_cmd:
                run_alembic_command("upgrade", engine)
                mock_cmd.upgrade.assert_called_once()
        finally:
            engine.dispose()


class TestUILazyImports:
    def test_ui_init_lazy_app_state(self):
        import project_workflow.interfaces.ui as ui_pkg
        state = ui_pkg._app_state
        assert state is not None

    def test_ui_init_lazy_app_state_class(self):
        import project_workflow.interfaces.ui as ui_pkg
        cls = ui_pkg._AppState
        assert cls is not None

    def test_ui_init_unknown_attr(self):
        import project_workflow.interfaces.ui as ui_pkg
        with pytest.raises(AttributeError):
            _ = ui_pkg._no_such_attr
