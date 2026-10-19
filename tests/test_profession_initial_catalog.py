"""Initial professions, current Base actions and immutable historical task references."""

import copy
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select

from project_workflow import config
from project_workflow.application.base_binding import observe_base_namespace_binding
from project_workflow.application.task import TaskService
from project_workflow.domain.base_catalog import BASE_CATALOG_SKILLS
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.project_theme import MANAGED_PROFESSION_THEMES
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import (
    ManagedCatalog,
    ensure_managed_catalog,
    load_managed_catalog,
    validate_managed_catalog_state,
)
from project_workflow.infrastructure.db.session import ensure_migrated, run_alembic_command
from project_workflow.infrastructure.db.uow import SAUnitOfWork

ROOT = Path(__file__).resolve().parents[1]
NEW = ROOT / "project_workflow/references/base_sdlc_catalog_v2.json"
OLD = NEW.with_name("base_sdlc_catalog_v1.json")


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'initial.db'}")
    ensure_migrated(engine)
    yield engine
    engine.dispose()


def rows(uow, table):
    return [dict(row) for row in uow.session.execute(select(table).order_by(table.c.id)).mappings()]


@pytest.mark.parametrize("filename", ["hermes_sdlc_catalog_v1.json", "base_sdlc_catalog_v1.json",
                                      "base_sdlc_catalog_v2.json"])
def test_fresh_initial_data_has_all_roles_modes_actions_and_distinct_themes(database, filename):
    with SAUnitOfWork(database) as uow:
        catalog = ensure_managed_catalog(uow, NEW.with_name(filename))
        professions = {role: uow.projects.get_by_cli_command(f"workflow-{role}") for role in MANAGED_PROFESSION_THEMES}
        assert len(professions) == len(catalog.workflows) == 7
        assert {(p.theme_icon, p.theme_color) for p in professions.values()} == set(MANAGED_PROFESSION_THEMES.values())
        assert len({p.theme_icon for p in professions.values()}) == 7
        assert len({p.theme_color for p in professions.values()}) == 7
        all_modes, all_phases = [], []
        for definition in catalog.workflows:
            profession = professions[definition.role_key]
            workflow = uow.workflows.get_by_id(profession.workflow_id)
            assert workflow.name == "Дефолтный"
            assert uow.workflows.belongs_to_profession(workflow.id, profession.id)
            modes = uow.workflows.list_modes(workflow.id)
            assert [mode.key for mode in modes] == [mode.key for mode in definition.modes]
            all_modes.extend(modes)
            for mode in modes:
                phases = uow.phases.list(workflow.id, mode_id=mode.id)
                all_phases.extend(phases)
                assert len(phases) == 3
                assert all(uow.phase_instructions.list(phase.id) for phase in phases)
                assert all(uow.phases.get_checks(phase.id) and uow.phases.get_evidence(phase.id) for phase in phases)
        assert len(all_modes) == 11 and len(all_phases) == 33
        assert validate_managed_catalog_state(uow, catalog)
        before = rows(uow, m.Project.__table__)
        ensure_managed_catalog(uow, NEW.with_name(filename))
        assert rows(uow, m.Project.__table__) == before


@pytest.mark.parametrize("problem", ["admission", "pm-confirmation", "handoff", "contract", "legacy-capability"])
def test_current_base_recipe_rejects_missing_admission_or_owner_handoff(problem):
    data = json.loads(NEW.read_text("utf-8"))
    if problem == "admission":
        item = data["workflows"][0]["modes"][0]["phases"][0]["instructions"][0]
        item["description"] = "Read Task comments attachments"
    elif problem == "pm-confirmation":
        item = data["workflows"][0]["modes"][0]["phases"][-1]["instructions"][-1]
        item["description"] = item["description"].replace("никогда не вызывает confirm", "сам вызывает confirm")
    elif problem == "handoff":
        item = data["workflows"][3]["modes"][0]["phases"][-1]["instructions"][-1]
        item["description"] = item["description"].replace("guarded Tracker terminal tool", "текстовый ответ")
    elif problem == "contract":
        data["workflows"][0]["terminal_contract"] = None
    else:
        data["workflows"][0]["modes"][0]["phases"][-1]["instructions"][-1]["description"] += " publishDraft"
    with pytest.raises(ValidationError):
        ManagedCatalog.model_validate(data)


def test_phase_counter_includes_all_active_modes_and_excludes_archived_generations(database):
    with SAUnitOfWork(database) as uow:
        ensure_managed_catalog(uow, OLD)
        old_phases = rows(uow, m.Phase.__table__)
        current = ensure_managed_catalog(uow, NEW)
        counts = uow.phases.count_all_modes_by_workflow()
        for definition in current.workflows:
            profession = uow.projects.get_by_cli_command(f"workflow-{definition.role_key}")
            assert counts[profession.workflow_id] == len(definition.modes) * 3
        assert len(rows(uow, m.Phase.__table__)) == 66
        assert all(uow.phases.get_by_id(row["id"]) is not None for row in old_phases)


def assert_theme_migration_updates_only_untouched_managed_professions(database):
    from sqlalchemy import text

    run_alembic_command("upgrade", database, "0011_profession_workflows")
    with database.begin() as connection:
        for index, role in enumerate(MANAGED_PROFESSION_THEMES, start=1):
            connection.execute(text("INSERT INTO workflows (id,key,name) VALUES (:id,:key,'Preset')"),
                               {"id": index, "key": f"hermes-sdlc:{role}"})
            connection.execute(text("INSERT INTO projects (id,workflow_id,code,name,cli_command) "
                                    "VALUES (:id,:id,:code,'Profession',:cli)"),
                               {"id": index, "code": f"ROLE{index}", "cli": f"workflow-{role}"})
        connection.execute(text("UPDATE projects SET theme_icon='layers',theme_color='#D2608E' WHERE id=1"))
    run_alembic_command("upgrade", database, "0012_profession_themes")
    with database.connect() as connection:
        records = connection.execute(text("SELECT cli_command,theme_icon,theme_color FROM projects")).all()
        for command, icon, color in records:
            role = command.removeprefix("workflow-")
            expected = ("layers", "#D2608E") if role == "project_manager" else MANAGED_PROFESSION_THEMES[role]
            assert (icon, color) == expected



def test_theme_migration_updates_only_untouched_managed_professions(tmp_path):
    database = create_engine(f"sqlite:///{tmp_path / 'themes.db'}")
    try:
        assert_theme_migration_updates_only_untouched_managed_professions(database)
    finally:
        database.dispose()


@pytest.mark.parametrize("artifact", ["base_sdlc_catalog_v1.json", "base_sdlc_catalog_v1_frozen.json"])
@pytest.mark.parametrize("instruction_execution", ["sync", "parallel"])
def test_adoption_preserves_profession_edits_old_tasks_history_and_user_collections(
    database, artifact, instruction_execution,
):
    previous = OLD.with_name(artifact)
    with SAUnitOfWork(database) as uow:
        ensure_managed_catalog(uow, previous)
        profession = uow.projects.get_by_cli_command("workflow-developer")
        mode = uow.workflows.get_mode_by_key(profession.workflow_id, "initial")
        phase = uow.phases.list(profession.workflow_id, mode_id=mode.id)[0]
        instruction = uow.phase_instructions.list(phase.id)[0]
        uow.phase_instructions.update(instruction["id"], {"execution_type": instruction_execution})
        task_id = uow.tasks.create({
            "project_id": profession.id, "workflow_id": profession.workflow_id, "mode_id": mode.id,
            "task_key": "DEV-42", "title": "Keep historical references",
            "current_phase_id": phase.id, "status": "active",
        })
        uow.record_step(task_id=task_id, phase_id=phase.id, verdict="pass", worker_report="Historical report",
                        covered_item_ids=[], missing_item_ids=[], blocker_messages=[],
                        evaluation_snapshot={}, supervisor_response={})
        uow.projects.update(profession.id, {"name": "Custom developer", "description": "Custom metadata",
                                           "theme_icon": "heart", "theme_color": "#D2608E"})
        extra = uow.workflows.create({"key": "user:extra", "name": "My workflow", "is_default": False})
        uow.workflows.assign_profession(extra, profession.id)
        uow.commit()
        protected = {table.name: rows(uow, table) for table in (
            m.Project.__table__, m.WorkflowMode.__table__, m.Phase.__table__, m.PhaseInstruction.__table__,
            m.Task.__table__, m.TaskStepHistoryEntry.__table__,
        )}
        catalog = ensure_managed_catalog(uow, NEW)
        assert catalog.catalog_version == 4
        for table in (m.Task.__table__, m.TaskStepHistoryEntry.__table__):
            assert rows(uow, table) == protected[table.name]
        from project_workflow.domain.project_theme import MANAGED_PROFESSION_PRESENTATION

        purposes = {role: value[1] for role, value in MANAGED_PROFESSION_PRESENTATION.items()}
        for before, after in zip(protected["projects"], rows(uow, m.Project.__table__), strict=True):
            role = before["cli_command"].removeprefix("workflow-")
            expected = dict(before)
            if before["name"] == "hermes-" + role.replace("_", "-"):
                expected["name"] = MANAGED_PROFESSION_PRESENTATION[role][0]
            if before["description"] == f"Managed namespace for hermes-sdlc:{role}":
                expected["description"] = purposes[role]
            assert after == expected
        for table in (m.WorkflowMode.__table__, m.Phase.__table__, m.PhaseInstruction.__table__):
            old_rows = protected[table.name]
            assert rows(uow, table)[:len(old_rows)] == old_rows
        assert uow.workflows.belongs_to_profession(extra, profession.id)
        assert uow.workflows.get_by_id(extra).name == "My workflow"
        if instruction_execution == "sync":
            assert validate_managed_catalog_state(uow, load_managed_catalog(previous), historical=True)
        else:
            with pytest.raises(ValueError, match="different instructions/checks/evidence"):
                validate_managed_catalog_state(uow, load_managed_catalog(previous), historical=True)
        with pytest.raises(ValueError, match="active catalog version"):
            validate_managed_catalog_state(uow, load_managed_catalog(previous))
        uow.commit()
        with pytest.raises(ConflictError, match="owner-issued admission"):
            TaskService(uow).create_task({"project_id": profession.id, "task_key": "DEV-43", "title": "No bypass"})
        ensure_managed_catalog(uow, NEW)
        assert len(uow.workflows.list_modes(profession.workflow_id)) == 2


def test_unrecognized_frozen_v3_edits_stop_adoption(database):
    with SAUnitOfWork(database) as uow:
        ensure_managed_catalog(uow, OLD.with_name("base_sdlc_catalog_v1_frozen.json"))
        profession = uow.projects.get_by_cli_command("workflow-developer")
        mode = uow.workflows.get_mode_by_key(profession.workflow_id, "initial")
        phase = uow.phases.list(profession.workflow_id, mode_id=mode.id)[0]
        instruction = uow.phase_instructions.list(phase.id)[0]
        uow.phase_instructions.update(instruction["id"], {"description": "Unrecognized changed recipe"})
        uow.commit()
        with pytest.raises(ValueError, match="does not match any immutable published recipe"):
            ensure_managed_catalog(uow, NEW)
        assert not uow.workflows.list_modes(profession.workflow_id, catalog_version=4)
        assert uow.workflows.get_by_id(profession.workflow_id).active_catalog_version == 3


def test_historical_admission_uses_its_frozen_recipe_digest(database, monkeypatch, tmp_path):
    from project_workflow.application import base_admission
    from project_workflow.infrastructure.base_package import digest

    path = OLD.with_name("base_sdlc_catalog_v1_frozen.json")
    catalog = load_managed_catalog(path)
    definition = next(item for item in catalog.workflows if item.role_key == "developer")
    role = {"namespace": definition.hermes_namespace, "profile": definition.hermes_profile,
            "modes": [mode.key for mode in definition.modes], "physicalSkills": definition.skill_allowlist,
            "roleInstruction": {"sha256": "d" * 64}}
    monkeypatch.setattr(base_admission, "load_pinned_package", lambda *_: {"roles": {"developer": role}})
    monkeypatch.setattr(base_admission.GitPackage, "read", lambda *_: b"synthetic manifest")
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", str(tmp_path / "agent-skills"))
    config.get_settings.cache_clear()
    with SAUnitOfWork(database) as uow:
        ensure_managed_catalog(uow, path)
        profession = uow.projects.get_by_cli_command("workflow-developer")
        mode = uow.workflows.get_mode_by_key(profession.workflow_id, "initial")
        ensure_managed_catalog(uow, NEW)
        admission = {
            "contract": "base-sdlc-admission/v1", "config_ref": "fleet-config:synthetic@1",
            "config_sha256": "a" * 64, "concrete_agent_ref": "11111111-1111-4111-8111-111111111111",
            "namespace": definition.hermes_namespace, "profile": definition.hermes_profile,
            "catalog_sha256": digest(path.read_bytes()), "skills_revision": catalog.skills_source.revision,
            "skills_manifest_sha256": digest(b"synthetic manifest"), "role_instruction_sha256": "d" * 64,
            "physical_skills": definition.skill_allowlist,
        }
        arguments = dict(project_id=profession.id, role_key="developer", workflow_key=definition.key,
                         mode_key="initial", execution_scope=definition.modes[0].execution_scopes[0],
                         historical_mode_id=mode.id)
        assert base_admission.validate_base_admission(uow, admission, **arguments) == admission
        with pytest.raises(ConflictError, match="pinned package/config validation failed"):
            base_admission.validate_base_admission(uow, {**admission, "catalog_sha256": "0" * 64}, **arguments)


def test_v4_source_and_binding_use_exact_current_package_and_keep_runtime_blocked(database, monkeypatch, tmp_path):
    from project_workflow.application import base_source
    catalog = load_managed_catalog(NEW)
    manifest = {"roles": {
        w.role_key: {"namespace": w.hermes_namespace, "profile": w.hermes_profile,
                     "modes": [mode.key for mode in w.modes], "physicalSkills": w.skill_allowlist,
                     "roleInstruction": {"sha256": "d" * 64}}
        for w in catalog.workflows
    }, "sources": {"native": {"skills": {skill: "e" * 64 for w in catalog.workflows for skill in w.skill_allowlist}}}}
    monkeypatch.setattr(base_source, "load_pinned_package", lambda *_: copy.deepcopy(manifest))
    monkeypatch.setattr(base_source.GitPackage, "read", lambda *_: b"test manifest")
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", str(tmp_path / "agent-skills"))
    config.get_settings.cache_clear()
    source = base_source.export_base_source(4)
    assert source["catalogVersion"] == 4 and source["skillsCatalogRevision"] == BASE_CATALOG_SKILLS[4]
    assert source["runtimeReady"] is False and source["sourceOnly"] is True
    assert sum(len(phases) for phases in source["phaseSets"].values()) == 33
    with SAUnitOfWork(database) as uow:
        ensure_managed_catalog(uow, NEW)
        profession = uow.projects.get_by_cli_command("workflow-developer")
        uow.projects.update(profession.id, {"name": "A user label", "theme_icon": "star", "theme_color": "#D2608E"})
        uow.commit()
        before = rows(uow, m.Project.__table__)
        binding = observe_base_namespace_binding(uow, profession.id)
        assert binding.catalog_version == 4 and binding.skills_revision == BASE_CATALOG_SKILLS[4]
        assert binding.namespace_name == "hermes-developer"
        assert binding.runtime_ready is False
        assert rows(uow, m.Project.__table__) == before


@pytest.mark.skipif(not os.environ.get("WORKFLOW_BASE_PACKAGE_TEST_ROOT"), reason="Private package is explicit opt-in")
def test_refreshed_catalog_uses_actual_pinned_base_role_instructions_and_all_skills(monkeypatch):
    from project_workflow.application import base_source
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_SKILLS_ROOT", os.environ["WORKFLOW_BASE_PACKAGE_TEST_ROOT"])
    config.get_settings.cache_clear()
    source = base_source.export_base_source(4)
    assert source["skillsCatalogRevision"] == BASE_CATALOG_SKILLS[4]
    assert len(source["roles"]) == 7 and len(source["skillsSha256"]) == 14
    assert sum(len(phases) for phases in source["phaseSets"].values()) == 33
    assert sum(len(p["instructions"]) for phases in source["phaseSets"].values() for p in phases) == 116
    assert all(len(role["roleInstructionSha256"]) == 64 for role in source["roles"].values())
    assert source["sourceOnly"] is True and source["runtimeReady"] is False
