"""Shared pytest fixtures for repo-wide test isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from wartz_workflow import config, db as db_module, schema as schema_module, ui as ui_module


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state(tmp_path, monkeypatch):
    """Keep tests away from the user's real runtime DB/settings and mutable seed file."""
    runtime_dir = tmp_path / ".wartz-workflow"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    test_db = runtime_dir / "workflow.db"
    settings_path = runtime_dir / "settings.json"
    seed_path = runtime_dir / "seed.json"
    repo_seed = Path(__file__).resolve().parents[1] / "wartz_workflow" / "references" / "seed.json"
    seed_path.write_text(repo_seed.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(db_module.base, "DB_PATH", test_db)
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    monkeypatch.setattr(config, "WARTZ_DIR", str(runtime_dir))
    monkeypatch.setattr(config, "SETTINGS_PATH", str(settings_path))
    monkeypatch.setattr(schema_module, "_SEED_PATH", seed_path)
    monkeypatch.setattr(ui_module, "_app_state", ui_module._AppState())

    # Reduce FD pressure in tests: monkeypatch _conn to skip WAL
    import sqlite3
    from pathlib import Path as _Path
    from wartz_workflow.db import WorkflowDB
    from wartz_workflow.schema import ensure_phase_catalog

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

    # Initialize schema so every test starts with a clean DB
    wdb = WorkflowDB(str(test_db))
    wdb.init()
    ensure_phase_catalog(wdb)

    yield

    ui_module._db = None
    ui_module._srv = None
    monkeypatch.setattr(WorkflowDB, "_conn", _orig_conn)
