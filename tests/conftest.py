"""Shared pytest fixtures for repo-wide test isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from project_workflow import config, db as db_module, schema as schema_module, ui as ui_module


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state(tmp_path, monkeypatch):
    """Keep tests away from the user's real runtime DB/settings and mutable seed file."""
    runtime_dir = tmp_path / ".project-workflow"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    test_db = runtime_dir / "workflow.db"
    settings_path = runtime_dir / "settings.json"
    seed_path = runtime_dir / "seed.json"
    repo_seed = Path(__file__).resolve().parents[1] / "project_workflow" / "references" / "seed.json"
    seed_path.write_text(repo_seed.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(db_module.base, "DB_PATH", test_db)
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    monkeypatch.setattr(config, "WORKFLOW_DIR", str(runtime_dir))
    monkeypatch.setattr(config, "SETTINGS_PATH", str(settings_path))
    monkeypatch.setattr(schema_module, "_SEED_PATH", seed_path)

    # Reduce FD pressure in tests: monkeypatch _conn to skip WAL
    import sqlite3
    from pathlib import Path as _Path
    from project_workflow.db import WorkflowDB
    from project_workflow.schema import ensure_phase_catalog
    from project_workflow.ui.dependencies import _AppState

    _orig_conn = WorkflowDB._conn
    def _test_conn(self):
        _Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -32000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn
    monkeypatch.setattr(WorkflowDB, "_conn", _test_conn)

    # Initialize legacy schema so the seed-sync step has a populated DB to mirror.
    wdb = WorkflowDB(str(test_db))
    wdb.init()
    ensure_phase_catalog(wdb)

    # Point the UI's SQLAlchemy-backed state at the same temp DB.
    ui_module._app_state = _AppState(database_url=f"sqlite:///{test_db}")

    yield

    # Restore original module-level singleton so later tests are not confused.
    ui_module._app_state = _AppState()
    monkeypatch.setattr(WorkflowDB, "_conn", _orig_conn)
