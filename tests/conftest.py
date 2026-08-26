"""Shared pytest fixtures for repo-wide test isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from project_workflow import config
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from tests._db_helpers import prepare_sqlite_uow


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state(tmp_path, monkeypatch):
    """Keep tests away from the user's real runtime DB/settings and mutable seed file."""
    runtime_dir = tmp_path / ".project-workflow"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    test_db = runtime_dir / "workflow.db"
    seed_path = runtime_dir / "seed.json"
    repo_seed = Path(__file__).resolve().parents[1] / "project_workflow" / "references" / "seed.json"
    seed_path.write_text(repo_seed.read_text(encoding="utf-8"), encoding="utf-8")

    database_url = f"sqlite:///{test_db}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.get_settings.cache_clear()

    monkeypatch.setattr(config, "SEED_PATH", seed_path)

    from project_workflow.application import state as app_state
    from project_workflow.infrastructure.db.session import reset_engine
    from project_workflow.interfaces import ui as ui_package
    from project_workflow.interfaces.ui import state as ui_state

    reset_engine()
    original_app_state = app_state._app_state
    original_ui_app_state = ui_state._app_state
    original_ui_package_app_state = ui_package._app_state
    sqlite_app_state = app_state._AppState(database_url=database_url)
    app_state._app_state = sqlite_app_state
    ui_state._app_state = sqlite_app_state
    ui_package._app_state = sqlite_app_state

    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    uow = SAUnitOfWork(database_url)
    prepare_sqlite_uow(uow)
    uow.close()

    yield

    # Restore original shared state so later tests are not confused.
    app_state._app_state = original_app_state
    ui_state._app_state = original_ui_app_state
    ui_package._app_state = original_ui_package_app_state
    reset_engine()
    config.get_settings.cache_clear()


@pytest.fixture
def supervisor_llm(monkeypatch):
    """Install an explicit LLM verdict for tests that evaluate reports."""

    def install(
        verdict: str,
        *,
        covered: list[str] | None = None,
        missing: list[str] | None = None,
        blockers: list[str] | None = None,
    ) -> None:
        def chat(*_args, **kwargs):
            items: list[tuple[str, str]] = []
            for line in str(kwargs.get("user", "")).splitlines():
                stripped = line.strip()
                if stripped.startswith('ID: "') and '" — ' in stripped:
                    item_id, text = stripped[5:].split('" — ', 1)
                    items.append((item_id, text))
            ids = [item_id for item_id, _ in items]
            by_text = {text: item_id for item_id, text in items}

            def resolve(values: list[str] | None, available: list[str]) -> list[str]:
                resolved: list[str] = []
                for value in values or []:
                    item_id = value if value in ids else by_text.get(value)
                    if item_id is None and available:
                        item_id = available.pop(0)
                    if item_id is not None and item_id not in resolved:
                        resolved.append(item_id)
                return resolved

            available = list(ids)
            covered_ids = resolve(covered, available)
            available = [item_id for item_id in available if item_id not in covered_ids]
            missing_ids = resolve(missing, available)
            if verdict == "PASS":
                covered_ids = ids
                missing_ids = []
            else:
                missing_ids.extend(
                    item_id for item_id in ids if item_id not in covered_ids and item_id not in missing_ids
                )

            return {
                "verdict": verdict,
                "covered": covered_ids,
                "missing": missing_ids,
                "blockers": blockers or (["Test blocker"] if verdict == "BLOCKED" else []),
                "message": f"Test Supervisor verdict: {verdict}",
                "confidence": 1.0,
            }

        monkeypatch.setattr(
            OpenAICompatibleClient,
            "chat",
            chat,
        )

    return install
