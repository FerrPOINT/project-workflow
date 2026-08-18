"""Shared pytest fixtures for repo-wide test isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from project_workflow import config
from project_workflow.infrastructure import llm as llm_module
from project_workflow.infrastructure.llm import OllamaClient


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state(tmp_path, monkeypatch):
    """Keep tests away from the user's real runtime DB/settings and mutable seed file."""
    runtime_dir = tmp_path / ".project-workflow"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(llm_module, "OLLAMA_MODEL", "test-model")
    monkeypatch.setattr(llm_module, "OLLAMA_API_STYLE", "native")
    test_db = runtime_dir / "workflow.db"
    seed_path = runtime_dir / "seed.json"
    repo_seed = Path(__file__).resolve().parents[1] / "project_workflow" / "references" / "seed.json"
    seed_path.write_text(repo_seed.read_text(encoding="utf-8"), encoding="utf-8")

    database_url = f"sqlite:///{test_db}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("WORKFLOW_DIR", str(runtime_dir))
    config.get_settings.cache_clear()

    monkeypatch.setattr(config, "SEED_PATH", seed_path)

    from project_workflow.infrastructure import db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", test_db)

    from project_workflow.application import state as app_state
    from project_workflow.infrastructure.db.session import reset_engine
    from project_workflow.interfaces.ui import state as ui_state

    reset_engine()
    original_app_state = app_state._app_state
    original_ui_app_state = ui_state._app_state
    sqlite_app_state = app_state._AppState(database_url=database_url)
    app_state._app_state = sqlite_app_state
    ui_state._app_state = sqlite_app_state

    from project_workflow.infrastructure.db.schema import ensure_phase_catalog
    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    uow = SAUnitOfWork(database_url)
    uow.create_all()
    ensure_phase_catalog(uow)
    default_workflow = uow.workflows.get_default()
    assert default_workflow is not None
    for code in ("AAT", "TASK", "DB"):
        uow.projects.create(
            {
                "workflow_id": default_workflow.id,
                "code": code,
                "name": f"Test project {code}",
                "key_prefixes": [code],
            }
        )
    uow.commit()
    uow.close()

    yield

    # Restore original shared state so later tests are not confused.
    app_state._app_state = original_app_state
    ui_state._app_state = original_ui_app_state
    reset_engine()
    config.get_settings.cache_clear()


@pytest.fixture
def wizard_llm(monkeypatch):
    """Install an explicit semantic verdict; production has no test fallback."""

    def install(
        verdict: str,
        *,
        covered: list[str] | None = None,
        missing: list[str] | None = None,
        blockers: list[str] | None = None,
    ) -> None:
        monkeypatch.setattr(
            OllamaClient,
            "chat",
            lambda *_args, **_kwargs: {
                "verdict": verdict,
                "covered": covered or [],
                "missing": missing or [],
                "blockers": blockers or [],
                "message": f"Test Wizard verdict: {verdict}",
                "confidence": 1.0,
            },
        )

    return install
