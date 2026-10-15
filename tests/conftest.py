"""Shared pytest fixtures for repo-wide test isolation."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from project_workflow import config
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from tests._db_helpers import prepare_sqlite_uow

# An explicit reviewed allowlist prevents new boundary tests entering the build lane.
_LANES = json.loads((Path(__file__).with_name("lanes.json")).read_text(encoding="utf-8"))


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        relative = Path(item.path).relative_to(Path(__file__).parent).as_posix()
        tier = "unit" if relative in _LANES["unit"] else "integration"
        item.add_marker(getattr(pytest.mark, tier))
        if relative in _LANES["slow"]:
            item.add_marker(pytest.mark.slow)
        if relative == _LANES["postgres"]:
            item.add_marker(pytest.mark.postgres)


@pytest.fixture(scope="session")
def ui_runtime_templates(tmp_path_factory):
    """Cache only the immutable initial fixture, never a test's modified database."""
    return tmp_path_factory.mktemp("ui-runtime-templates"), {}


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state(request, tmp_path, monkeypatch, ui_runtime_templates):
    """Keep tests away from the user's real runtime DB/settings and mutable seed file."""
    if request.node.get_closest_marker("unit") and not request.node.get_closest_marker("integration"):
        # Pure tests must not pay for or silently depend on the SQLite/UI fixture.
        yield
        return
    created_uows: list[SAUnitOfWork] = []
    original_uow_init = SAUnitOfWork.__init__

    def tracked_uow_init(self: SAUnitOfWork, *args: Any, **kwargs: Any) -> None:
        original_uow_init(self, *args, **kwargs)
        created_uows.append(self)

    monkeypatch.setattr(SAUnitOfWork, "__init__", tracked_uow_init)

    runtime_dir = tmp_path / ".project-workflow"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    test_db = runtime_dir / "workflow.db"
    seed_path = runtime_dir / "legacy_unmanaged_seed.json"
    repo_seed = (
        Path(__file__).resolve().parents[1]
        / "project_workflow"
        / "references"
        / "legacy_unmanaged_seed.json"
    )
    seed_path.write_text(repo_seed.read_text(encoding="utf-8"), encoding="utf-8")

    database_url = f"sqlite:///{test_db}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("PLATFORM_SERVICES_URL", "")
    config.get_settings.cache_clear()

    monkeypatch.setattr(config, "LEGACY_UNMANAGED_SEED_PATH", seed_path)

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

    template_directory, templates = ui_runtime_templates
    seed_digest = hashlib.sha256(seed_path.read_bytes()).hexdigest()
    template = templates.get(seed_digest)
    if template is None:
        uow = SAUnitOfWork(database_url)
        prepare_sqlite_uow(uow)
        uow.close()
        template = template_directory / (seed_digest + ".db")
        # SQLite backup includes committed WAL data; plain copying a live DB does not.
        with closing(sqlite3.connect(test_db)) as source, closing(sqlite3.connect(template)) as target:
            source.backup(target)
        templates[seed_digest] = template
    else:
        shutil.copyfile(template, test_db)

    yield

    # Restore original shared state so later tests are not confused.
    app_state._app_state = original_app_state
    ui_state._app_state = original_ui_app_state
    ui_package._app_state = original_ui_package_app_state
    for tracked_uow in reversed(created_uows):
        tracked_uow.close()
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
