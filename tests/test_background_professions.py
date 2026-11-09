"""Explicit defaults preserve edited definitions and reject legacy identity reuse."""

import pytest

from project_workflow.infrastructure.db.background_professions import background_catalog, ensure_background_professions
from project_workflow.infrastructure.db.session import ensure_schema, get_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork


@pytest.fixture
def database_url(tmp_path):
    path = tmp_path / "background.db"
    url = f"sqlite:///{path}"
    engine = get_engine(url)
    try:
        yield url
    finally:
        engine.dispose()
        for owned in (path, path.with_name(path.name + "-journal"),
                      path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
            owned.unlink(missing_ok=True)


def test_defaults_are_editable_idempotent_and_do_not_create_tasks(database_url):
    with SAUnitOfWork(database_url) as uow:
        ensure_schema(uow.session.get_bind())
        prepared = ensure_background_professions(uow)
        uow.commit()
        for code, profession_id in prepared.items():
            profession = uow.projects.get_by_id(profession_id)
            assert profession.code == code
            assert profession.launch_profile is None
            workflow = uow.workflows.get_by_id(profession.workflow_id)
            assert workflow.name == "Дефолтный"
            assert uow.workflows.belongs_to_profession(workflow.id, profession_id)
            mode, = uow.workflows.list_modes(workflow.id)
            phases = uow.phases.list(workflow.id, mode.id)
            assert [phase.name for phase in phases] == [
                "Контекст", "Существующие находки", "Исследование",
                "Повторная сверка", "Сохранение и отчёт",
            ]
            for phase in phases:
                assert uow.phase_instructions.list(phase.id)
                assert uow.phase_checks.list(phase.id)
                assert uow.phase_evidence_requirements.list(phase.id)
            uow.projects.update(profession_id, {"name": f"Автор: {code}"})
            uow.phases.update(phases[2].id, {"name": "Моё исследование"})
        uow.commit()
        assert ensure_background_professions(uow) == prepared
        for code, profession_id in prepared.items():
            profession = uow.projects.get_by_id(profession_id)
            assert profession.name == f"Автор: {code}"
            mode, = uow.workflows.list_modes(profession.workflow_id)
            assert uow.phases.list(profession.workflow_id, mode.id)[2].name == "Моё исследование"
        assert not uow.tasks.list()


def test_legacy_identity_conflict_preserves_data_and_prevents_partial_provisioning(database_url):
    with SAUnitOfWork(database_url) as uow:
        ensure_schema(uow.session.get_bind())
        workflow_id = uow.workflows.create({"key": "fleet:bug_searcher", "name": "История"})
        profession_id = uow.projects.create({
            "workflow_id": workflow_id, "code": "BUG_SEARCHER",
            "name": "Прежняя профессия", "cli_command": "workflow-bug_searcher",
        })
        uow.workflows.assign_profession(workflow_id, profession_id)
        uow.commit()
        with pytest.raises(ValueError, match="явный переход"):
            ensure_background_professions(uow)
        assert uow.projects.get_by_id(profession_id).name == "Прежняя профессия"
        assert uow.workflows.get_by_id(workflow_id).key == "fleet:bug_searcher"
        assert uow.projects.get_by_code("REFACTORER") is None


def test_platform_initialization_installs_defaults_and_preserves_edits(database_url, monkeypatch):
    from project_workflow import config
    from scripts.init_db import main

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    config.get_settings.cache_clear()
    assert main() == 0
    with SAUnitOfWork(database_url) as uow:
        prepared = background_catalog(uow)
        assert {p["cli_command"] for p in prepared["namespaces"]} == {
            "workflow-bug_searcher", "workflow-refactorer",
        }
        assert len(uow.projects.list()) == 9
        selected = prepared["namespaces"][0]
        uow.projects.update(selected["id"], {"name": "Моя профессия"})
        uow.workflows.update(selected["workflow_id"], {"name": "Мой workflow"})
    assert main() == 0
    with SAUnitOfWork(database_url) as uow:
        assert len(uow.projects.list()) == 9
        assert background_catalog(uow)["namespaces"][0]["name"] == "Моя профессия"
        assert background_catalog(uow)["workflows"][0]["name"] == "Мой workflow"
        assert not uow.tasks.list()


def test_background_directory_never_installs_on_read_and_rejects_legacy(database_url):
    with SAUnitOfWork(database_url) as uow:
        ensure_schema(uow.session.get_bind())
        assert background_catalog(uow) == {"namespaces": [], "workflows": []}
        assert not uow.projects.list()
        workflow_id = uow.workflows.create({"key": "legacy", "name": "История"})
        uow.projects.create({
            "workflow_id": workflow_id, "code": "BUG_SEARCHER",
            "name": "Прежняя профессия", "cli_command": "workflow-bug_searcher",
        })
        with pytest.raises(ValueError, match="identity conflict"):
            background_catalog(uow)


def test_runtime_directory_includes_real_background_bindings(database_url, monkeypatch):
    from project_workflow import config
    from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog
    from project_workflow.interfaces.ui.routes import api, runtime_api

    with SAUnitOfWork(database_url) as uow:
        ensure_schema(uow.session.get_bind())
        ensure_single_task_catalog(uow)
        ensure_background_professions(uow)
        namespaces = [{"id": p.id, "cli_command": p.cli_command,
                       "theme_icon": "search", "theme_icon_path": "M0 0", "theme_color": "#EAB308"}
                      for p in uow.projects.list()]
        workflows = [{"id": w.id, "key": w.key} for w in uow.workflows.list()]
    monkeypatch.setattr(config, "CATALOG_VARIANT", "single-task-v1")
    monkeypatch.setattr(api, "api_namespaces", lambda: {"namespaces": namespaces})
    monkeypatch.setattr(api, "api_workflows", lambda: {"workflows": workflows})
    monkeypatch.setattr(runtime_api, "SAUnitOfWork", lambda: SAUnitOfWork(database_url))
    monkeypatch.setattr(runtime_api, "_authorized_service_credential", lambda _: runtime_api._ServiceCredential(
        role_key="fleet-control", kind="catalog",
    ))
    result = runtime_api.runtime_catalog("Bearer test")
    assert len(result["namespaces"]) == len(result["workflows"]) == 9
    background = [p for p in result["namespaces"] if p["cli_command"] in {
        "workflow-bug_searcher", "workflow-refactorer",
    }]
    assert len(background) == 2
    assert {p["workflow_id"] for p in background} <= {w["id"] for w in result["workflows"]}
