"""Focused contracts for the versioned seven-role managed catalog."""

from __future__ import annotations

import copy
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
    load_managed_catalog,
)
from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

pytestmark = [pytest.mark.unit]


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
            assert all(
                marker in terminal
                for marker in ("workflow_phase", "complete=true", "outcome", "evidence")
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
    assert all(namespace.theme_icon == "folder" for namespace in namespaces)
    assert all(namespace.theme_color == "#5E6AD2" for namespace in namespaces)
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


@pytest.mark.parametrize("migrated_key", [True, False])
def test_managed_bootstrap_preserves_exact_legacy_catalog_task_and_history(
    empty_uow, migrated_key
):
    workflow_id, mode_id, phase_id, namespace_id = _bootstrap_versioned_legacy_catalog(
        empty_uow, migrated_key=migrated_key
    )
    legacy_namespace = empty_uow.projects.get_by_id(namespace_id)
    assert legacy_namespace is not None
    assert legacy_namespace.to_dict() == {
        "id": namespace_id,
        "workflow_id": workflow_id,
        "code": config.DEFAULT_PROJECT_CODE,
        "name": config.DEFAULT_PROJECT_NAME,
        "description": "",
        "theme_icon": "folder",
        "theme_color": "#5E6AD2",
        "cli_command": config.DEFAULT_NAMESPACE_CLI_COMMAND,
        "key_prefixes": config.DEFAULT_TASK_KEY_PREFIXES,
        "workflow_name": config.LEGACY_UNMANAGED_WORKFLOW_NAME,
    }
    task_id = empty_uow.tasks.create(
        {
            "project_id": namespace_id,
            "workflow_id": workflow_id,
            "mode_id": mode_id,
            "task_key": "RUN-LEGACY-1",
            "title": "Legacy task",
            "current_phase_id": phase_id,
            "status": "active",
        }
    )
    history_id = empty_uow.record_step(
        task_id=task_id,
        phase_id=phase_id,
        verdict="pass",
        worker_report="preserve this report",
        covered_item_ids=[],
        missing_item_ids=[],
        blocker_messages=[],
        evaluation_snapshot={"legacy": True},
        supervisor_response={"verdict": "PASS"},
    )
    empty_uow.tasks.record_phase_event(
        task_id, phase_id, "completed", step_history_id=history_id
    )
    empty_uow.commit()
    before_task = empty_uow.tasks.get_by_id(task_id).to_dict()
    before_history = empty_uow.step_history.list(task_id=task_id, limit=None)[0].to_dict()
    before_events = [item.to_dict() for item in empty_uow.tasks.list_phase_events(task_id)]
    legacy_reviewer = empty_uow.agents.get_by_name("reviewer")
    assert legacy_reviewer is not None and legacy_reviewer.id is not None

    ensure_managed_catalog(empty_uow)
    empty_uow.commit()
    ensure_managed_catalog(empty_uow)
    empty_uow.commit()

    assert empty_uow.tasks.get_by_id(task_id).to_dict() == before_task
    assert empty_uow.step_history.list(task_id=task_id, limit=None)[0].to_dict() == before_history
    assert [item.to_dict() for item in empty_uow.tasks.list_phase_events(task_id)] == before_events
    assert empty_uow.workflows.get_default().id == workflow_id
    assert empty_uow.agents.get_by_id(legacy_reviewer.id).name == "legacy-reviewer"
    managed_reviewer = empty_uow.agents.get_by_name("reviewer")
    assert managed_reviewer is not None and managed_reviewer.id != legacy_reviewer.id
    assert managed_reviewer.hermes_profile == "hermes-sdlc-reviewer"
    assert len(
        [
            workflow
            for workflow in empty_uow.workflows.list()
            if workflow.key in MANAGED_WORKFLOW_KEYS
        ]
    ) == 7


def test_legacy_reconcile_rejects_foreign_trash_before_renaming_or_bootstrap(empty_uow):
    _bootstrap_versioned_legacy_catalog(empty_uow)
    trash_id = empty_uow.agents.create(
        {
            "name": "test-trash-agent",
            "description": "Must not survive managed reconciliation",
            "hermes_profile": "test-trash-profile",
        }
    )
    empty_uow.commit()
    legacy_reviewer = empty_uow.agents.get_by_name("reviewer")
    assert legacy_reviewer is not None and legacy_reviewer.id is not None

    with pytest.raises(ValueError, match="test-trash-agent"):
        ensure_managed_catalog(empty_uow)

    assert empty_uow.agents.get_by_id(legacy_reviewer.id).name == "reviewer"
    assert empty_uow.agents.get_by_id(trash_id).name == "test-trash-agent"
    assert not [
        workflow
        for workflow in empty_uow.workflows.list()
        if workflow.key in MANAGED_WORKFLOW_KEYS
    ]


def test_managed_bootstrap_rejects_zero_reference_foreign_default_workflow_without_mutation(
    empty_uow,
):
    foreign_id = empty_uow.workflows.create(
        {
            "key": "legacy:foreign-default",
            "name": "Foreign default",
            "is_default": True,
        }
    )
    empty_uow.commit()

    with pytest.raises(ValueError) as exc_info:
        ensure_managed_catalog(empty_uow)

    message = str(exc_info.value)
    assert (
        f"workflow(id={foreign_id}, key='legacy:foreign-default', name='Foreign default', "
        "default=true, references=zero, owned_modes=1, owned_phases=0)"
    ) in message
    assert [workflow.key for workflow in empty_uow.workflows.list()] == [
        "legacy:foreign-default"
    ]
    assert empty_uow.workflows.get_default().id == foreign_id
    assert not empty_uow.agents.list()
    assert not empty_uow.projects.list()


def test_managed_bootstrap_rejects_zero_reference_foreign_agent_without_mutation(empty_uow):
    foreign_id = empty_uow.agents.create(
        {
            "name": "coder",
            "description": "Legacy test agent",
            "hermes_profile": "legacy-test-profile",
        }
    )
    empty_uow.commit()

    with pytest.raises(ValueError) as exc_info:
        ensure_managed_catalog(empty_uow)

    assert (
        f"agent(id={foreign_id}, name='coder', profile='legacy-test-profile', references=zero)"
        in str(exc_info.value)
    )
    assert [agent.name for agent in empty_uow.agents.list()] == ["coder"]
    assert not empty_uow.workflows.list()
    assert not empty_uow.projects.list()


def test_managed_bootstrap_rejects_foreign_namespace_without_mutating_managed_catalog(empty_uow):
    ensure_managed_catalog(empty_uow)
    empty_uow.commit()
    project_manager = next(
        workflow
        for workflow in empty_uow.workflows.list()
        if workflow.key == "hermes-sdlc:project_manager"
    )
    foreign_id = empty_uow.projects.create(
        {
            "workflow_id": project_manager.id,
            "code": "TMP",
            "name": "Temporary namespace",
            "cli_command": "workflow-temporary",
            "key_prefixes": [],
        }
    )
    empty_uow.commit()

    with pytest.raises(ValueError) as exc_info:
        ensure_managed_catalog(empty_uow)

    assert (
        f"namespace(id={foreign_id}, code='TMP', cli_command='workflow-temporary', "
        f"name='Temporary namespace', workflow_id={project_manager.id}, references=zero)"
        in str(exc_info.value)
    )
    assert len(empty_uow.workflows.list()) == 7
    assert len(empty_uow.agents.list()) == 7
    assert len(empty_uow.projects.list()) == 8


def test_managed_bootstrap_reports_reference_bearing_foreign_objects_without_mutation(empty_uow):
    agent_id = empty_uow.agents.create(
        {
            "name": "coder",
            "description": "Legacy test agent",
            "hermes_profile": "legacy-test-profile",
        }
    )
    workflow_id = empty_uow.workflows.create(
        {"key": "legacy:referenced", "name": "Referenced legacy workflow"}
    )
    mode = empty_uow.workflows.get_mode_by_key(workflow_id, "default")
    assert mode is not None and mode.id is not None
    phase_id = empty_uow.phases.create(
        {
            "workflow_id": workflow_id,
            "mode_id": mode.id,
            "code": "legacy-phase",
            "name": "Legacy phase",
            "phase_order": 1,
            "execution_type": "sync",
            "agent_id": agent_id,
        }
    )
    namespace_id = empty_uow.projects.create(
        {
            "workflow_id": workflow_id,
            "code": "LEG",
            "name": "Legacy namespace",
            "cli_command": "workflow-legacy",
            "key_prefixes": ["LEG"],
        }
    )
    empty_uow.tasks.create(
        {
            "project_id": namespace_id,
            "workflow_id": workflow_id,
            "mode_id": mode.id,
            "cycle_number": 0,
            "task_key": "LEG-1",
            "title": "Referenced legacy task",
            "current_phase_id": phase_id,
            "status": "active",
        }
    )
    empty_uow.commit()

    with pytest.raises(ValueError) as exc_info:
        ensure_managed_catalog(empty_uow)

    message = str(exc_info.value)
    assert (
        f"workflow(id={workflow_id}, key='legacy:referenced', "
        "name='Referenced legacy workflow', default=false, "
        "references=namespaces:1,tasks:1, owned_modes=1, owned_phases=1)"
    ) in message
    assert (
        f"agent(id={agent_id}, name='coder', profile='legacy-test-profile', "
        "references=phases:1)"
    ) in message
    assert (
        f"namespace(id={namespace_id}, code='LEG', cli_command='workflow-legacy', "
        f"name='Legacy namespace', workflow_id={workflow_id}, references=tasks:1)"
    ) in message
    assert len(empty_uow.workflows.list()) == 1
    assert len(empty_uow.agents.list()) == 1
    assert len(empty_uow.projects.list()) == 1
    assert len(empty_uow.tasks.list()) == 1


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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("code", "DRIFT"),
        ("name", "Drifted legacy namespace"),
        ("description", "Drifted legacy description"),
        ("theme_icon", "rocket"),
        ("theme_icon", "project"),
        ("theme_color", "#22C55E"),
        ("theme_color", "#5e6ad2"),
        ("cli_command", "workflow-drift"),
        ("key_prefixes", ["DRIFT"]),
    ],
)
def test_managed_bootstrap_rejects_legacy_namespace_identity_drift(
    empty_uow, field, value
):
    _workflow_id, _mode_id, _phase_id, namespace_id = (
        _bootstrap_versioned_legacy_catalog(empty_uow)
    )
    empty_uow.projects.update(namespace_id, {field: value})
    empty_uow.commit()

    with pytest.raises(ValueError, match="legacy namespace identity differs"):
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


def test_catalog_rejects_terminal_action_before_workflow_phase_completion(tmp_path: Path):
    raw = json.loads(config.MANAGED_CATALOG_PATH.read_text(encoding="utf-8"))
    terminal = raw["workflows"][0]["modes"][0]["phases"][-1]["instructions"][-1]
    terminal["description"] = (
        "Prepare one precise final Business Markdown comment with outcome and evidence, "
        "then call only publishDraft before workflow_phase returns complete=true. "
        "If input is insufficient, ask one concrete question and do not complete."
    )

    with pytest.raises(ValueError, match="only after workflow_phase complete=true"):
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


def _project_manager_request(namespace_id: int, attempt_number: int = 18) -> dict:
    return {
        "project_id": namespace_id,
        "task_key": "PM-1",
        "mode_key": "draft",
        "role_key": "project_manager",
        "workflow_key": "hermes-sdlc:project_manager",
        "execution_scope": "business",
        "stage_key": "draft",
        "cycle_number": 0,
        "attempt_number": attempt_number,
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


@pytest.mark.parametrize("attempt_number", [1, 18])
@pytest.mark.parametrize("preexisting_task", [False, True])
def test_project_manager_assignment_uses_canonical_identity_and_slotless_business_scope(
    empty_uow, attempt_number, preexisting_task
):
    ensure_managed_catalog(empty_uow)
    namespace = empty_uow.projects.get_by_cli_command("workflow-project_manager")
    assert namespace is not None and namespace.id is not None
    request = _project_manager_request(namespace.id, attempt_number)

    if preexisting_task:
        workflow = empty_uow.workflows.get_by_id(namespace.workflow_id)
        assert workflow is not None and workflow.id is not None
        mode = empty_uow.workflows.get_mode_by_key(workflow.id, "draft")
        assert mode is not None and mode.id is not None
        phase = list(empty_uow.phases.list(workflow.id, mode_id=mode.id))[0]
        empty_uow.tasks.create(
            {
                "project_id": namespace.id,
                "workflow_id": workflow.id,
                "mode_id": mode.id,
                "cycle_number": 0,
                "task_key": "PM-1",
                "title": "PM-1",
                "current_phase_id": phase.id,
                "status": "active",
            }
        )
        empty_uow.commit()
        request["expected_status"] = "active"

    with pytest.raises(ConflictError):
        TaskService(empty_uow).assign_runtime_task(**{**request, "expected_revision": 1})

    assigned = TaskService(empty_uow).assign_runtime_task(**request)

    assert assigned["role_key"] == "project_manager"
    assert assigned["attempt_number"] == attempt_number
    assert assigned["mode_key"] == "draft"
    assert assigned["execution_scope"] == "business"
    assert assigned["tech_execution_workspace_ref"] is None
    assert assigned["tech_execution_attempt_ref"] is None
    assert TaskService(empty_uow).assign_runtime_task(**request) == assigned
    assert len(empty_uow.tasks.list_assignments(assigned["id"])) == 1
    with pytest.raises(ConflictError, match="другого runtime assignment"):
        TaskService(empty_uow).assign_runtime_task(**{**request, "attempt_number": attempt_number + 1})


@pytest.mark.parametrize(
    "override",
    [
        {"operation_key": " "},
        {"operation_key": "x" * 129},
        {"mode_key": " "},
        {"mode_key": "x" * 129},
        {"mode_key": "unknown-mode"},
        {"workflow_key": "hermes-sdlc:analyst"},
        {"role_key": "project-manager"},
        {"project_id": 999},
        {"task_key": "invalid"},
        {"cycle_number": -1},
        {"cycle_number": True},
        {"cycle_number": 1},
        {"expected_revision": -1},
        {"expected_revision": True},
        {"expected_status": "active"},
        {"attempt_number": 0},
        {"attempt_number": True},
        {"attempt_number": 1.5},
        {"work_item_revision": -1},
        {"work_item_revision": True},
        {"workspace_revision": 0},
        {"workspace_revision": True},
        {"workspace_generation": -1},
        {"workspace_generation": True},
        {"lease_generation": -1},
        {"lease_generation": True},
        {"business_task_ref": " "},
        {"stage_revision": "x" * 129},
        {"assignment_ref": "x" * 513},
        {"exact_input_refs": {}},
        {"exact_input_refs": [{"kind": "task", "ref": "task-1"}] * 129},
        {"exact_input_refs": ["task-1"]},
        {"exact_input_refs": [{"kind": "task", "ref": "task-1", "unknown": "field"}]},
        {"exact_input_refs": [{"kind": "task", "ref": "task-1", "revision": " "}]},
        {"exact_input_refs": [{"kind": "task", "ref": "task-1", "hash": " "}]},
        {"exact_input_refs": [{"kind": "task", "ref": "task-1"}] * 2},
    ],
)
def test_invalid_owner_assignment_leaves_no_task_or_ledger_and_allows_valid_recovery(empty_uow, override):
    ensure_managed_catalog(empty_uow)
    empty_uow.commit()
    namespace = empty_uow.projects.get_by_cli_command("workflow-project_manager")
    assert namespace is not None and namespace.id is not None
    request = _project_manager_request(namespace.id)

    with pytest.raises((ConflictError, ValueError, NotFoundError)):
        TaskService(empty_uow).assign_runtime_task(**{**request, **override})

    assert empty_uow.tasks.get_by_key("PM-1", project_id=namespace.id) is None
    assert empty_uow.tasks.get_assignment_by_operation_key(request["operation_key"]) is None
    accepted = TaskService(empty_uow).assign_runtime_task(**request)
    assert accepted["assignment_revision"] == 1
    assert accepted["attempt_number"] == 18
    assert TaskService(empty_uow).assign_runtime_task(**request) == accepted


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


@pytest.mark.parametrize(
    "status,override",
    [
        ("active", {"expected_mode_key": "analysis"}),
        ("active", {"expected_cycle_number": 1}),
        ("active", {"cycle_number": 1}),
        ("done", {}),
        ("done", {"cycle_number": 2}),
        ("done", {"cycle_number": 1, "attempt_number": 2}),
    ],
)
def test_owner_adoption_rejects_stale_prior_state_and_unsupported_retry(empty_uow, status, override):
    ensure_managed_catalog(empty_uow)
    namespace = empty_uow.projects.get_by_cli_command("workflow-project_manager")
    assert namespace is not None and namespace.id is not None
    mode = empty_uow.workflows.get_mode_by_key(namespace.workflow_id, "draft")
    phase = list(empty_uow.phases.list(namespace.workflow_id, mode_id=mode.id))[0]
    task_id = empty_uow.tasks.create(
        {"project_id": namespace.id, "workflow_id": namespace.workflow_id, "mode_id": mode.id,
         "task_key": "PM-1", "current_phase_id": phase.id, "status": status}
    )
    empty_uow.commit()
    before = empty_uow.tasks.get_by_id(task_id).to_dict()
    request = {**_project_manager_request(namespace.id), "expected_status": status, **override}
    with pytest.raises(ConflictError):
        TaskService(empty_uow).assign_runtime_task(**request)
    assert empty_uow.tasks.get_by_id(task_id).to_dict() == before
    assert empty_uow.tasks.list_assignments(task_id) == []


def test_project_manager_is_the_only_accepted_underscore_role_key():
    assert normalize_role_key("project_manager") == "project_manager"
    with pytest.raises(ValueError, match="каноническим project_manager"):
        normalize_role_key("project_manager_extra")
    with pytest.raises(ValueError, match="каноническим project_manager"):
        normalize_role_key("project-manager_extra")


@pytest.mark.parametrize(
    "edits",
    [
        [(("skills_source", "revision"), " ")],
        [(("schema",), "relevanter-project-workflow-catalog/v99")],
        [(("workflows", 0, "name"), " ")],
        [(("workflows", 0, "workflow_order"), 2)],
        [(("workflows", 0, "key"), "hermes-sdlc:foreign")],
        [(("workflows", 0, "role_key"), "foreign"), (("workflows", 0, "key"), "hermes-sdlc:foreign")],
        [(("workflows", 0, "skill_allowlist"), ["project-workflow-executor"] * 2)],
        [(("workflows", 0, "skill_allowlist"), ["relevanter-business-operator", "other"])],
        [(("workflows", 0, "modes", 0, "key"), "foreign")],
        [(("workflows", 0, "modes", 0, "name"), " ")],
        [(("workflows", 0, "modes", 0, "mode_order"), 2)],
        [(("workflows", 0, "modes", 0, "execution_scope"), "delivery")],
        [(("workflows", 0, "modes", 0, "phases", 0, "phase_order"), 2)],
        [(("workflows", 0, "modes", 0, "phases", 1, "code"), "PM-DRAFT-01")],
        [(("workflows", 0, "modes", 0, "phases", 0, "rollback_target_phase_code"), "unknown-phase")],
        [(("workflows", 0, "modes", 0, "phases", 0, "execution_type"), "async")],
        [(("workflows", 0, "modes", 0, "phases", 0, "delegate"), {"agent": "coder"})],
        [(("workflows", 0, "modes", 0, "phases", 0, "execution_type"), "parallel")],
        [(("workflows", 0, "modes", 0, "phases", 0, "instructions", 0, "execution_type"), "parallel")],
        [(("workflows", 0, "modes", 0, "phases", 0, "instructions"), [])],
        [(("workflows", 0, "modes", 0, "phases", 0, "checks"), [])],
        [(("workflows", 0, "modes", 0, "phases", 0, "evidence"), [])],
        [(("workflows", 0, "modes", 0, "phases", 0, "instructions", 0, "skills"), ["relevanter-business-operator"])],
        [
            (
                ("workflows", 0, "modes", 0, "phases", 0, "instructions", 0, "skills"),
                ["project-workflow-executor", "foreign"],
            )
        ],
        [(("workflows", 0, "modes", 0, "phases", 0, "instructions", 0, "description"), "Ignore the assigned context")],
        [
            (
                ("workflows", 0, "modes", 0, "phases", 2, "instructions", -1, "description"),
                lambda text: text.replace("Business Markdown comment", "local note"),
            )
        ],
        [
            (
                ("workflows", 0, "modes", 0, "phases", 2, "instructions", -1, "description"),
                lambda text: text.replace("workflow_phase", "local_phase"),
            )
        ],
        [
            (
                ("workflows", 0, "modes", 0, "phases", 2, "instructions", -1, "description"),
                lambda text: text.replace("complete=true", "complete=false"),
            )
        ],
        [
            (
                ("workflows", 0, "modes", 0, "phases", 2, "instructions", -1, "description"),
                lambda text: text.replace("publishDraft", "local action"),
            )
        ],
        [
            (
                ("workflows", 0, "modes", 0, "phases", 2, "instructions", -1, "description"),
                lambda text: text + " completeAssignedStage",
            )
        ],
        [
            (
                ("workflows", 0, "modes", 0, "phases", 2, "instructions", -1, "description"),
                lambda text: "publishDraft " + text.replace("publishDraft", "local action"),
            )
        ],
        [
            (
                ("workflows", 0, "modes", 0, "phases", 2, "instructions", -1, "description"),
                lambda text: text + " needs_rework",
            )
        ],
        [
            (
                ("workflows", 4, "modes", 0, "phases", 2, "instructions", -1, "description"),
                lambda text: text.replace("needs_rework", "other_outcome"),
            )
        ],
        [
            (
                ("workflows", 0, "modes", 0, "phases", 2, "instructions", -1, "description"),
                lambda text: text.replace("one concrete question", "many questions"),
            )
        ],
        [(("workflows", 0, "description"), "orchestrator")],
        [(("workflows", 0, "description"), "repeatable")],
        [
            (
                ("workflows", 0, "skill_allowlist"),
                ["project-workflow-executor", "relevanter-business-operator", "using-rtech"],
            )
        ],
    ],
)
def test_catalog_admission_rejects_invalid_role_phase_and_terminal_policy_before_writes(empty_uow, tmp_path, edits):
    raw = json.loads(config.MANAGED_CATALOG_PATH.read_text(encoding="utf-8"))
    for path, replacement in edits:
        parent = raw
        for key in path[:-1]:
            parent = parent[key]
        old = parent.get(path[-1]) if isinstance(parent, dict) else parent[path[-1]]
        updated = replacement(old) if callable(replacement) else replacement
        assert updated != old, f"Catalog mutation must change {path!r}"
        parent[path[-1]] = updated
    path = _write_catalog(tmp_path, raw)

    with pytest.raises(ValueError):
        ensure_managed_catalog(empty_uow, catalog_path=path)

    assert empty_uow.workflows.list() == []
    assert empty_uow.projects.list() == []
    assert empty_uow.agents.list() == []


@pytest.mark.parametrize("shape", ["missing", "extension", "invalid-json", "not-object", "missing-role"])
def test_catalog_loader_rejects_invalid_file_before_any_database_changes(empty_uow, tmp_path, shape):
    path = tmp_path / "catalog.json"
    if shape == "extension":
        path = tmp_path / "catalog.yaml"
        path.write_text("{}", encoding="utf-8")
    elif shape == "invalid-json":
        path.write_text("{", encoding="utf-8")
    elif shape == "not-object":
        path.write_text("[]", encoding="utf-8")
    elif shape == "missing-role":
        raw = json.loads(config.MANAGED_CATALOG_PATH.read_text(encoding="utf-8"))
        raw["workflows"].pop()
        path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises((ValueError, FileNotFoundError)):
        ensure_managed_catalog(empty_uow, catalog_path=path)
    assert empty_uow.workflows.list() == []
    assert empty_uow.projects.list() == []
    assert empty_uow.agents.list() == []


@pytest.mark.parametrize("drift", ["workflow", "mode", "phase", "namespace-count", "agent-alias"])
def test_legacy_catalog_adoption_rejects_ambiguous_or_divergent_state_before_renaming(empty_uow, drift):
    workflow_id, mode_id, phase_id, _namespace_id = _bootstrap_versioned_legacy_catalog(empty_uow)
    if drift == "workflow":
        second_id = empty_uow.workflows.create({"name": config.LEGACY_UNMANAGED_WORKFLOW_NAME})
        empty_uow.session.get(db_models.Workflow, second_id).key = f"legacy:{second_id}"
    elif drift == "mode":
        mode = empty_uow.session.get(db_models.WorkflowMode, mode_id)
        mode.name = "Foreign mode"
    elif drift == "phase":
        empty_uow.phases.update(phase_id, {"name": "Foreign phase"})
    elif drift == "namespace-count":
        empty_uow.projects.create(
            {"workflow_id": workflow_id, "code": "FOREIGN", "name": "Foreign", "cli_command": "workflow-foreign"}
        )
    else:
        empty_uow.agents.create({"name": "legacy-reviewer", "description": "Foreign agent"})
    empty_uow.commit()
    before_agents = [agent.to_dict() for agent in empty_uow.agents.list()]
    before_workflows = [workflow.to_dict() for workflow in empty_uow.workflows.list()]
    with pytest.raises(ValueError, match="Legacy compatibility catalog is"):
        ensure_managed_catalog(empty_uow)
    assert [agent.to_dict() for agent in empty_uow.agents.list()] == before_agents
    assert [workflow.to_dict() for workflow in empty_uow.workflows.list()] == before_workflows
    assert empty_uow.agents.get_by_name("reviewer") is not None


def test_init_db_executes_managed_catalog_validation_and_fails_closed_on_drift(
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

        assert main() == 1
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
