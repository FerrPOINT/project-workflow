"""Shared pytest fixtures for repo-wide test isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from project_workflow import config


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state(tmp_path, monkeypatch):
    """Keep tests away from the user's real runtime DB/settings and mutable seed file."""
    runtime_dir = tmp_path / ".project-workflow"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    test_db = runtime_dir / "workflow.db"
    settings_path = runtime_dir / "settings.json"
    seed_path = runtime_dir / "seed.json"
    smoke_seed_path = runtime_dir / "smoke_seed.json"
    repo_seed = Path(__file__).resolve().parents[1] / "project_workflow" / "references" / "seed.json"
    repo_smoke_seed = Path(__file__).resolve().parents[1] / "project_workflow" / "references" / "smoke_seed.json"
    seed_path.write_text(repo_seed.read_text(encoding="utf-8"), encoding="utf-8")
    smoke_seed_path.write_text(repo_smoke_seed.read_text(encoding="utf-8"), encoding="utf-8")

    database_url = f"sqlite:///{test_db}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.get_settings.cache_clear()

    monkeypatch.setattr(config, "WORKFLOW_DIR", str(runtime_dir))
    monkeypatch.setattr(config, "SETTINGS_PATH", str(settings_path))
    monkeypatch.setattr(config, "SEED_PATH", seed_path)
    monkeypatch.setattr(config, "SMOKE_SEED_PATH", smoke_seed_path)

    from project_workflow.infrastructure import db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", test_db)

    from project_workflow.application import state as app_state
    from project_workflow.infrastructure.db.session import reset_engine

    reset_engine()
    original_app_state = app_state._app_state
    app_state._app_state = app_state._AppState(database_url=database_url)

    
    from project_workflow.infrastructure.db.schema import ensure_phase_catalog
    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    uow = SAUnitOfWork(database_url)
    uow.create_all()
    ensure_phase_catalog(uow)

    yield

    # Restore original shared state so later tests are not confused.
    app_state._app_state = original_app_state
    reset_engine()
    config.get_settings.cache_clear()
