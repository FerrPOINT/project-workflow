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

    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    monkeypatch.setattr(config, "WARTZ_DIR", str(runtime_dir))
    monkeypatch.setattr(config, "SETTINGS_PATH", str(settings_path))
    monkeypatch.setattr(schema_module, "_SEED_PATH", seed_path)
    monkeypatch.setattr(ui_module, "_db", None)
    monkeypatch.setattr(ui_module, "_srv", None)

    yield

    ui_module._db = None
    ui_module._srv = None
