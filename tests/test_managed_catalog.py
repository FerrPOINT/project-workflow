"""Focused contracts for the versioned seven-role managed catalog."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from project_workflow import config
from project_workflow.application.execution_mode import resolve_execution_selection
from project_workflow.application.task import TaskService
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.runtime_assignment import (
    MANAGED_ROLE_MODE_SCOPES,
    MANAGED_WORKFLOW_KEYS,
    normalize_role_key,
)
from project_workflow.infrastructure.db import models as db_models
from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.managed_catalog import (
    ensure_managed_catalog,
    export_runtime_catalog,
    load_managed_catalog,
)
from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

pytestmark = [pytest.mark.unit]


def test_runtime_export_freezes_exact_semantic_compatibility_and_canonical_capabilities():
    catalog = load_managed_catalog()
    manifest = {"roles": {item.role_key: {"physicalSkills": item.skill_allowlist} for item in catalog.workflows}}
    revision = "a" * 40
    skills_revision = catalog.skills_source.revision
    runtime, phases = export_runtime_catalog(catalog, manifest=manifest, workflow_revision=revision,
                                             skills_revision=skills_revision, source_artifacts={})
    descriptor = runtime["runtimeCompatibility"]
    assert descriptor["catalogVersion"] == 2
    assert descriptor["catalogRevision"] == revision
    assert descriptor["skillsRevision"] == skills_revision
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    assert descriptor["catalogSha256"] == digest({"roles": runtime["roles"], "phase_sets": phases["phase_sets"]})
    assert descriptor["capabilitySha256"] == digest(runtime["runtimeCapabilities"])
    assert "candidate_publish" in runtime["runtimeCapabilities"]["phaseTools"]["DV-INITIAL-03"]
    assert "candidate_publish" not in runtime["runtimeCapabilities"]["phaseTools"]["DV-INITIAL-01"]
    assert "workspace_read" in runtime["runtimeCapabilities"]["phaseTools"]["TS-TEST-02"]
    with pytest.raises(ValueError, match="exact committed"):
        export_runtime_catalog(catalog, manifest=manifest, workflow_revision="moving-branch",
                               skills_revision=skills_revision, source_artifacts={})
    with pytest.raises(ValueError, match="canonical source pin"):
        export_runtime_catalog(catalog, manifest=manifest, workflow_revision=revision,
                               skills_revision="b" * 40, source_artifacts={})


@pytest.fixture
def empty_uow(tmp_path: Path):
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'managed-catalog.db'}")
    ensure_schema(uow.session.get_bind())
    try:
        yield uow
    finally:
        uow.close()


def _write_catalog(tmp_path: Path, raw: dict) -> Path:
    path = tmp_path / "managed-catalog.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


def _bootstrap_versioned_legacy_catalog(
    uow: SAUnitOfWork, *, migrated_key: bool = True
) -> tuple[int, int, int, int]:
    schema.ensure_phase_catalog(uow, seed_path=config.LEGACY_UNMANAGED_SEED_PATH)
    bootstrap_default_project(uow)
    workflow = uow.workflows.get_default()
    namespace = uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE)
    assert workflow is not None and workflow.id is not None
    assert namespace is not None and namespace.id is not None
    mode = uow.workflows.get_mode_by_key(workflow.id, "default")
    assert mode is not None and mode.id is not None
    phase = uow.phases.get_by_code(workflow.id, "1.INTAKE", mode_id=mode.id)
    assert phase is not None and phase.id is not None
    workflow_row = uow.session.get(db_models.Workflow, workflow.id)
    assert workflow_row is not None
    if migrated_key:
        workflow_row.key = f"legacy:{workflow.id}"
    uow.session.flush()
    return workflow.id, mode.id, phase.id, namespace.id


def test_source_catalog_has_exact_canonical_inventory_and_phase_contracts():
    catalog = load_managed_catalog()
    raw_catalog = config.MANAGED_CATALOG_PATH.read_text(encoding="utf-8").casefold()

    assert catalog.catalog_version == 2
    assert [workflow.role_key for workflow in catalog.workflows] == list(
        MANAGED_ROLE_MODE_SCOPES
    )
    assert {workflow.key for workflow in catalog.workflows} == MANAGED_WORKFLOW_KEYS
    assert sum(len(workflow.modes) for workflow in catalog.workflows) == 11
    assert sum(
        len(mode.phases)
        for workflow in catalog.workflows
        for mode in workflow.modes
    ) == 33
    assert '"repeatable"' not in raw_catalog

    for workflow in catalog.workflows:
        assert {mode.key: tuple(mode.execution_scopes) for mode in workflow.modes} == (
            MANAGED_ROLE_MODE_SCOPES[workflow.role_key]
        )
        allowed_skills = set(workflow.skill_allowlist)
        for mode in workflow.modes:
            assert [phase.phase_order for phase in mode.phases] == list(
                range(1, len(mode.phases) + 1)
            )
            first = mode.phases[0].instructions[0].description.casefold()
            assert all(marker in first for marker in ("task", "comment", "attachment"))
            terminal = mode.phases[-1].instructions[-1].description.casefold()
            assert "business markdown comment" in terminal
            assert all(
                marker in terminal
                for marker in ("project-workflow", "complete=true", "outcome", "evidence")
            )
            assert "one concrete question" in terminal
            if workflow.role_key == "project_manager":
                assert "publishdraft" in terminal
                assert terminal.index("complete=true") < terminal.index("publishdraft")
            else:
                assert "completeassignedstage" in terminal
                assert terminal.index("complete=true") < terminal.index(
                    "completeassignedstage"
                )
            for phase in mode.phases:
                assert phase.instructions and phase.checks and phase.evidence
                for instruction in phase.instructions:
                    assert "project-workflow-executor" in instruction.skills
                    assert set(instruction.skills) <= allowed_skills


def test_catalog_matches_versioned_agent_skills_compatibility_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "agent_skills_catalog_v1.json"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    catalog = load_managed_catalog()

    assert catalog.skills_source.repository == expected["source_repository"]
    assert catalog.skills_source.revision == expected["source_revision"]
    assert catalog.skills_source.manifest_path == expected["source_manifest"]
    assert catalog.skills_source.manifest_schema == expected["source_schema"]
    assert set(expected["roles"]) == {workflow.role_key for workflow in catalog.workflows}
    for workflow in catalog.workflows:
        role = expected["roles"][workflow.role_key]
        assert workflow.hermes_namespace == role["namespace"]
        assert workflow.hermes_profile == role["profile"]
        assert [mode.key for mode in workflow.modes] == role["modes"]
        assert set(workflow.skill_allowlist) == set(role["skills"])


def test_managed_bootstrap_rejects_divergent_existing_registry(empty_uow):
    definition = load_managed_catalog().workflows[0]
    empty_uow.workflows.create(
        {
            "key": definition.key,
            "name": definition.name,
            "description": definition.description,
        }
    )
    empty_uow.commit()

    with pytest.raises(ValueError, match="different mode registry"):
        ensure_managed_catalog(empty_uow)


def test_managed_bootstrap_rejects_phase_contract_drift(empty_uow):
    ensure_managed_catalog(empty_uow)
    project_manager = next(
        workflow
        for workflow in empty_uow.workflows.list()
        if workflow.key == "hermes-sdlc:project_manager"
    )
    draft = empty_uow.workflows.get_mode_by_key(project_manager.id, "draft")
    phase = empty_uow.phases.list(project_manager.id, mode_id=draft.id)[0]
    empty_uow.phases.update(phase.id, {"name": "Drifted outside versioned catalog"})
    empty_uow.commit()

    with pytest.raises(ValueError, match="different identity"):
        ensure_managed_catalog(empty_uow)


def test_managed_bootstrap_rejects_workflow_identity_drift(empty_uow):
    ensure_managed_catalog(empty_uow)
    project_manager = next(
        workflow
        for workflow in empty_uow.workflows.list()
        if workflow.key == "hermes-sdlc:project_manager"
    )
    empty_uow.workflows.update(project_manager.id, {"name": "Drifted managed name"})
    empty_uow.commit()

    with pytest.raises(ValueError, match="different identity"):
        ensure_managed_catalog(empty_uow)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code", "DRIFT"),
        ("name", "Drifted managed namespace"),
        ("description", "Drifted managed description"),
        ("theme_icon", "rocket"),
        ("theme_icon", "project"),
        ("theme_color", "#22C55E"),
        ("theme_color", "#5e6ad2"),
        ("cli_command", "workflow-drift"),
        ("key_prefixes", ["DRIFT"]),
    ],
)
def test_managed_bootstrap_rejects_namespace_identity_drift(empty_uow, field, value):
    ensure_managed_catalog(empty_uow)
    namespace = empty_uow.projects.get_by_cli_command("workflow-project_manager")
    assert namespace is not None and namespace.id is not None
    empty_uow.projects.update(namespace.id, {field: value})
    empty_uow.commit()

    with pytest.raises(ValueError):
        ensure_managed_catalog(empty_uow)


def test_catalog_rejects_a_fortieth_phase(tmp_path: Path):
    raw = json.loads(config.MANAGED_CATALOG_PATH.read_text(encoding="utf-8"))
    mode = raw["workflows"][0]["modes"][0]
    extra_phase = copy.deepcopy(mode["phases"][-1])
    extra_phase.update(
        {
            "code": "pm-extra-terminal",
            "name": "Extra terminal phase",
            "phase_order": 4,
        }
    )
    mode["phases"].append(extra_phase)

    with pytest.raises(ValueError, match="at most 3"):
        load_managed_catalog(_write_catalog(tmp_path, raw))


def test_catalog_rejects_duplicate_allowed_terminal_action(tmp_path: Path):
    raw = json.loads(config.MANAGED_CATALOG_PATH.read_text(encoding="utf-8"))
    first_instruction = raw["workflows"][0]["modes"][0]["phases"][0]["instructions"][0]
    first_instruction["description"] += " Then call publishDraft early."

    with pytest.raises(ValueError, match="exactly one publishdraft"):
        load_managed_catalog(_write_catalog(tmp_path, raw))


def test_catalog_rejects_disallowed_terminal_action(tmp_path: Path):
    raw = json.loads(config.MANAGED_CATALOG_PATH.read_text(encoding="utf-8"))
    first_instruction = raw["workflows"][0]["modes"][0]["phases"][0]["instructions"][0]
    first_instruction["description"] += " Never call completeAssignedStage here."

    with pytest.raises(ValueError, match="cannot mention terminal action completeassignedstage"):
        load_managed_catalog(_write_catalog(tmp_path, raw))


def test_catalog_rejects_terminal_action_before_project_workflow_completion(tmp_path: Path):
    raw = json.loads(config.MANAGED_CATALOG_PATH.read_text(encoding="utf-8"))
    terminal = raw["workflows"][0]["modes"][0]["phases"][-1]["instructions"][-1]
    terminal["description"] = (
        "Prepare one precise final Business Markdown comment with outcome and evidence, "
        "then call only publishDraft before project-workflow returns complete=true. "
        "If input is insufficient, ask one concrete question and do not complete."
    )

    with pytest.raises(ValueError, match="only after project-workflow complete=true"):
        load_managed_catalog(_write_catalog(tmp_path, raw))


def test_managed_workflow_requires_explicit_assigned_mode(empty_uow):
    ensure_managed_catalog(empty_uow)
    developer = next(
        workflow
        for workflow in empty_uow.workflows.list()
        if workflow.key == "hermes-sdlc:developer"
    )
    assert developer.id is not None

    with pytest.raises(ConflictError, match="backend-assigned mode_key"):
        resolve_execution_selection(empty_uow, developer.id)

    selection = resolve_execution_selection(
        empty_uow, developer.id, mode_key="rework", cycle_number=4
    )
    assert selection.mode_key == "rework"
    assert selection.cycle_number == 4








def test_legacy_unmanaged_workflow_keeps_default_mode_compatibility(empty_uow):
    workflow_id = empty_uow.workflows.create({"name": "Local unmanaged"})

    selection = resolve_execution_selection(empty_uow, workflow_id)

    assert selection.mode_key == "default"
    assert selection.cycle_number == 0


@pytest.mark.parametrize(
    "override",
    [
        {"workflow_id": True},
        {"workflow_id": 0},
        {"workflow_id": 999},
        {"project_id": True},
        {"project_id": 0},
        {"project_id": 999},
        {"task_key": None},
        {"task_key": "invalid"},
        {"current_phase_id": True},
        {"current_phase_id": -1},
        {"current_phase_id": 999},
    ],
)
def test_legacy_task_creation_rejects_invalid_catalog_identity_and_recovers(empty_uow, override):
    workflow_id, _mode_id, _phase_id, namespace_id = _bootstrap_versioned_legacy_catalog(empty_uow)
    empty_uow.commit()
    payload = {"workflow_id": workflow_id, "project_id": namespace_id, "task_key": "RUN-901", "title": "Keep"}
    with pytest.raises((ValueError, ConflictError, NotFoundError)):
        TaskService(empty_uow).create_task({**payload, **override})
    assert empty_uow.tasks.list() == []
    created = TaskService(empty_uow).create_task(payload)
    assert created["task_key"] == "RUN-901"
    assert created["assignment_revision"] == 0
    assert created["assignment_operation_key"] is None




def test_project_manager_is_the_only_accepted_underscore_role_key():
    assert normalize_role_key("project_manager") == "project_manager"
    with pytest.raises(ValueError, match="каноническим project_manager"):
        normalize_role_key("project_manager_extra")
    with pytest.raises(ValueError, match="каноническим project_manager"):
        normalize_role_key("project-manager_extra")


def test_init_db_keeps_installed_catalog_presentation_edits(
    tmp_path, monkeypatch
):
    from project_workflow.config import get_settings
    from project_workflow.infrastructure.db.session import reset_engine
    from scripts.init_db import main

    database_url = f"sqlite:///{tmp_path / 'managed-init-drift.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    reset_engine()
    try:
        assert main() == 0
        with SAUnitOfWork(database_url) as uow:
            namespace = uow.projects.get_by_cli_command("workflow-project_manager")
            assert namespace is not None and namespace.id is not None
            uow.projects.update(namespace.id, {"theme_color": "#22C55E"})

        assert main() == 0
        with SAUnitOfWork(database_url) as uow:
            namespace = uow.projects.get_by_cli_command("workflow-project_manager")
            assert namespace is not None
            assert namespace.theme_color == "#22C55E"
            assert len(
                [
                    workflow
                    for workflow in uow.workflows.list()
                    if workflow.key in MANAGED_WORKFLOW_KEYS
                ]
            ) == 7
    finally:
        get_settings.cache_clear()
        reset_engine()


def test_agent_cli_surface_is_still_step_and_history_only():
    from project_workflow.interfaces.cli.core import cli

    assert set(cli.commands) == {"step", "history"}
