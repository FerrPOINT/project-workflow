"""Default profession presentation is distinct from immutable execution keys."""

import hashlib

import pytest

from project_workflow import config
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog
from project_workflow.infrastructure.db.session import ensure_schema, reset_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project
from scripts.init_db import main

EXPECTED_NAMES = [
    "Руководитель проекта", "Аналитик", "Архитектор", "Разработчик",
    "Рецензент кода", "Тестировщик", "Инженер по эксплуатации",
]


@pytest.mark.parametrize("variant", ["legacy", "base"])
def test_fresh_managed_install_has_seven_russian_professions_without_generic_starter(tmp_path, monkeypatch, variant):
    name = "hermes_sdlc_catalog_v1.json" if variant == "legacy" else "base_sdlc_catalog_v2.json"
    catalog_path = config.MANAGED_CATALOG_PATH.with_name(name)
    original_hash = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    monkeypatch.setattr(config, "MANAGED_CATALOG_PATH", catalog_path)
    with SAUnitOfWork(f"sqlite:///{tmp_path / 'fresh.db'}") as uow:
        ensure_schema(uow.session.get_bind())
        catalog = ensure_managed_catalog(uow)
        uow.commit()
        professions = list(uow.projects.list())
        assert [p.name for p in professions] == EXPECTED_NAMES
        assert len(professions) == 7
        assert all("hermes" not in p.description.casefold() for p in professions)
        assert uow.projects.get_by_cli_command("workflow-run") is None
        for definition, profession in zip(catalog.workflows, professions, strict=True):
            assert profession.cli_command == f"workflow-{definition.role_key}"
            assert profession.launch_profile == definition.hermes_profile
        # Even the explicit compatibility helper must not add RUN to a role installation.
        bootstrap_default_project(uow)
        assert uow.projects.get_by_cli_command("workflow-run") is None
        assert len(uow.projects.list()) == 7
    assert hashlib.sha256(catalog_path.read_bytes()).hexdigest() == original_hash


def test_repeated_init_localizes_only_old_defaults_and_preserves_execution_state(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config.get_settings.cache_clear()
    reset_engine()
    try:
        assert main() == 0
        with SAUnitOfWork(url) as uow:
            professions = list(uow.projects.list())
            for p in professions:
                role = p.cli_command.removeprefix("workflow-")
                uow.projects.update(p.id, {
                    "name": "hermes-" + role.replace("_", "-"),
                    "description": f"Managed namespace for hermes-sdlc:{role}",
                })
            analyst = uow.projects.get_by_cli_command("workflow-analyst")
            uow.projects.update(analyst.id, {"name": "Эксперт по данным", "description": "Авторское описание"})
            uow.commit()
            identities = {p.id: (p.code, p.workflow_id, p.cli_command, p.launch_profile) for p in uow.projects.list()}
            workflows = [(w.id, w.key, w.active_catalog_version) for w in uow.workflows.list()]
            phases = [p.to_dict() for p in uow.phases.list()]
        assert main() == 0
        assert main() == 0
        with SAUnitOfWork(url) as uow:
            professions = list(uow.projects.list())
            assert [p.name for p in professions] == [EXPECTED_NAMES[0], "Эксперт по данным", *EXPECTED_NAMES[2:]]
            assert uow.projects.get_by_cli_command("workflow-analyst").description == "Авторское описание"
            assert {p.id: (p.code, p.workflow_id, p.cli_command, p.launch_profile) for p in professions} == identities
            assert [(w.id, w.key, w.active_catalog_version) for w in uow.workflows.list()] == workflows
            assert [p.to_dict() for p in uow.phases.list()] == phases
            assert len(professions) == 7
    finally:
        config.get_settings.cache_clear()
        reset_engine()
