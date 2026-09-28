"""Focused contracts for the versioned seven-role managed catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_workflow import config
from project_workflow.application.execution_mode import resolve_execution_selection
from project_workflow.application.task import TaskService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import (
    MANAGED_ROLE_MODE_SCOPES,
    MANAGED_WORKFLOW_KEYS,
    normalize_role_key,
)
from project_workflow.infrastructure.db.managed_catalog import (
    ensure_managed_catalog,
    load_managed_catalog,
)
from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork

pytestmark = [pytest.mark.unit]


@pytest.fixture
def empty_uow(tmp_path: Path):
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'managed-catalog.db'}")
    ensure_schema(uow.session.get_bind())
    try:
        yield uow
    finally:
        uow.close()


def test_source_catalog_has_exact_canonical_inventory_and_phase_contracts():
    catalog = load_managed_catalog()
    raw_catalog = config.MANAGED_CATALOG_PATH.read_text(encoding="utf-8").casefold()

    assert catalog.catalog_version == 1
    assert [workflow.role_key for workflow in catalog.workflows] == list(
        MANAGED_ROLE_MODE_SCOPES
    )
    assert {workflow.key for workflow in catalog.workflows} == MANAGED_WORKFLOW_KEYS
    assert sum(len(workflow.modes) for workflow in catalog.workflows) == 13
    assert sum(
        len(mode.phases)
        for workflow in catalog.workflows
        for mode in workflow.modes
    ) == 39
    assert '"repeatable"' not in raw_catalog

    for workflow in catalog.workflows:
        assert {mode.key: mode.execution_scope for mode in workflow.modes} == (
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
            assert "one concrete question" in terminal
            if workflow.role_key == "project_manager":
                assert "publishdraft" in terminal
            else:
                assert "completeassignedstage" in terminal
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


def test_managed_bootstrap_persists_exact_catalog_and_is_idempotent(empty_uow):
    catalog = ensure_managed_catalog(empty_uow)
    empty_uow.commit()

    workflows = list(empty_uow.workflows.list())
    agents = list(empty_uow.agents.list())
    namespaces = list(empty_uow.projects.list())
    assert len(workflows) == 7
    assert len(agents) == 7
    assert len(namespaces) == 7
    assert [workflow.key for workflow in workflows] == [item.key for item in catalog.workflows]
    assert {agent.name for agent in agents} == set(MANAGED_ROLE_MODE_SCOPES)
    assert {namespace.cli_command for namespace in namespaces} == {
        f"workflow-{role_key}" for role_key in MANAGED_ROLE_MODE_SCOPES
    }
    assert all(namespace.key_prefixes == [] for namespace in namespaces)
    assert sum(len(empty_uow.workflows.list_modes(workflow.id)) for workflow in workflows) == 13
    assert all(
        mode.key != "default"
        for workflow in workflows
        for mode in empty_uow.workflows.list_modes(workflow.id)
    )

    all_phases = [
        phase
        for workflow in workflows
        for mode in empty_uow.workflows.list_modes(workflow.id)
        for phase in empty_uow.phases.list(workflow.id, mode_id=mode.id)
    ]
    phase_count = len(all_phases)
    instruction_count = sum(
        len(empty_uow.phase_instructions.list(phase.id))
        for phase in all_phases
    )
    ensure_managed_catalog(empty_uow)
    empty_uow.commit()

    assert len(empty_uow.workflows.list()) == 7
    assert len(empty_uow.projects.list()) == 7
    workflows_after = list(empty_uow.workflows.list())
    phases_after = [
        phase
        for workflow in workflows_after
        for mode in empty_uow.workflows.list_modes(workflow.id)
        for phase in empty_uow.phases.list(workflow.id, mode_id=mode.id)
    ]
    assert len(phases_after) == phase_count == 39
    assert sum(
        len(empty_uow.phase_instructions.list(phase.id))
        for phase in phases_after
    ) == instruction_count


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


def test_managed_bootstrap_rejects_agent_identity_drift(empty_uow):
    ensure_managed_catalog(empty_uow)
    project_manager = empty_uow.agents.get_by_name("project_manager")
    assert project_manager is not None and project_manager.id is not None
    empty_uow.agents.update(project_manager.id, {"description": "Drifted managed role"})
    empty_uow.commit()

    with pytest.raises(ValueError, match="another identity"):
        ensure_managed_catalog(empty_uow)


def test_managed_bootstrap_rejects_namespace_identity_drift(empty_uow):
    ensure_managed_catalog(empty_uow)
    namespace = empty_uow.projects.get_by_cli_command("workflow-project_manager")
    assert namespace is not None and namespace.id is not None
    empty_uow.projects.update(namespace.id, {"description": "Drifted managed namespace"})
    empty_uow.commit()

    with pytest.raises(ValueError, match="another identity"):
        ensure_managed_catalog(empty_uow)


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


def test_project_manager_assignment_uses_canonical_identity_and_slotless_business_scope(empty_uow):
    ensure_managed_catalog(empty_uow)
    namespace = empty_uow.projects.get_by_cli_command("workflow-project_manager")
    assert namespace is not None and namespace.id is not None
    request = {
        "project_id": namespace.id,
        "task_key": "PM-1",
        "mode_key": "draft",
        "role_key": "project_manager",
        "workflow_key": "hermes-sdlc:project_manager",
        "execution_scope": "business",
        "stage_key": "draft",
        "cycle_number": 0,
        "attempt_number": 1,
        "operation_key": "assign:pm-1:draft:0",
        "business_task_ref": "business-task:PM-1@1",
        "root_task_ref": "business-task:PM-1@1",
        "work_item_ref": "business-task:PM-1@1",
        "work_item_revision": 1,
        "queue_item_ref": "queue-item:PM-1:draft:0",
        "task_workspace_ref": "task-workspace:PM-1",
        "workspace_revision": 1,
        "tech_execution_workspace_ref": None,
        "tech_execution_attempt_ref": None,
        "decomposition_revision_ref": "decomposition:PM-1@0",
        "stage_revision": "stage:PM-1:draft@1",
        "assignment_ref": "assignment:PM-1@1",
        "workspace_generation": 0,
        "lease_generation": 0,
        "exact_input_refs": [
            {
                "kind": "business_task",
                "ref": "business-task:PM-1",
                "revision": "1",
                "hash": "a" * 64,
            }
        ],
        "expected_revision": 0,
        "expected_status": "missing",
    }

    assigned = TaskService(empty_uow).assign_runtime_task(**request)

    assert assigned["role_key"] == "project_manager"
    assert assigned["mode_key"] == "draft"
    assert assigned["execution_scope"] == "business"
    assert assigned["tech_execution_workspace_ref"] is None
    assert assigned["tech_execution_attempt_ref"] is None


def test_legacy_unmanaged_workflow_keeps_default_mode_compatibility(empty_uow):
    workflow_id = empty_uow.workflows.create({"name": "Local unmanaged"})

    selection = resolve_execution_selection(empty_uow, workflow_id)

    assert selection.mode_key == "default"
    assert selection.cycle_number == 0


def test_project_manager_is_the_only_accepted_underscore_role_key():
    assert normalize_role_key("project_manager") == "project_manager"
    with pytest.raises(ValueError, match="каноническим project_manager"):
        normalize_role_key("project_manager_extra")
    with pytest.raises(ValueError, match="каноническим project_manager"):
        normalize_role_key("project-manager_extra")


def test_managed_startup_has_no_legacy_seed_fallback():
    root = Path(__file__).resolve().parents[1]
    init_source = (root / "scripts" / "init_db.py").read_text(encoding="utf-8")

    assert "ensure_managed_catalog" in init_source
    assert "ensure_phase_catalog" not in init_source
    assert not (root / "project_workflow" / "references" / "seed.json").exists()
    assert config.MANAGED_CATALOG_PATH.name == "hermes_sdlc_catalog_v1.json"
    assert config.LEGACY_UNMANAGED_SEED_PATH.name == "legacy_unmanaged_seed.json"


def test_agent_cli_surface_is_still_step_and_history_only():
    from project_workflow.interfaces.cli.core import cli

    assert set(cli.commands) == {"step", "history"}
