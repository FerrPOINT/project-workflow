"""Fail-closed contracts for the immutable managed workflow catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.application.agent import AgentService
from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.managed_catalog_policy import (
    MANAGED_CATALOG_IMMUTABLE_ERROR,
)
from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.phase_service import PhaseService
from project_workflow.application.project import ProjectService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db import models as db_models
from project_workflow.infrastructure.db.managed_catalog import (
    ensure_managed_catalog,
    validate_managed_catalog_state,
)
from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests.test_runtime_capabilities import _install_manifest, _valid_compatibility, _valid_manifest

pytestmark = [pytest.mark.unit]


@pytest.fixture
def empty_uow(tmp_path: Path):
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'managed-hardening.db'}")
    ensure_schema(uow.session.get_bind())
    try:
        yield uow
    finally:
        uow.close()


def _bootstrap_global_managed_catalog() -> None:
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow)


def _managed_objects(uow: SAUnitOfWork):
    workflow = next(
        item for item in uow.workflows.list() if item.key == "hermes-sdlc:project_manager"
    )
    assert workflow.id is not None
    mode = uow.workflows.get_mode_by_key(workflow.id, "draft")
    assert mode is not None and mode.id is not None
    phases = list(uow.phases.list(workflow.id, mode_id=mode.id))
    phase = phases[0]
    assert phase.id is not None
    instruction = list(uow.phase_instructions.list(phase.id))[0]
    agent = uow.agents.get_by_name("project_manager")
    namespace = uow.projects.get_by_cli_command("workflow-project_manager")
    assert agent is not None and agent.id is not None
    assert namespace is not None and namespace.id is not None
    return workflow, mode, phases, phase, instruction, agent, namespace


def _managed_snapshot(uow: SAUnitOfWork) -> tuple[object, ...]:
    workflows = list(uow.workflows.list())
    modes = [
        mode.to_dict()
        for workflow in workflows
        if workflow.id is not None
        for mode in uow.workflows.list_modes(workflow.id)
    ]
    phases = [phase.to_dict() for phase in uow.phases.list()]
    phase_ids = [int(phase["id"]) for phase in phases]
    return (
        tuple(json.dumps(item.to_dict(), sort_keys=True) for item in workflows),
        tuple(json.dumps(item, sort_keys=True) for item in modes),
        tuple(json.dumps(item, sort_keys=True) for item in phases),
        tuple(
            json.dumps(item, sort_keys=True)
            for phase_id in phase_ids
            for item in uow.phase_instructions.list(phase_id)
        ),
        tuple(
            json.dumps(item, sort_keys=True)
            for phase_id in phase_ids
            for item in uow.phase_checks.list(phase_id)
        ),
        tuple(
            json.dumps(item, sort_keys=True)
            for phase_id in phase_ids
            for item in uow.phase_evidence_requirements.list(phase_id)
        ),
        tuple(json.dumps(item.to_dict(), sort_keys=True) for item in uow.agents.list()),
        tuple(json.dumps(item.to_dict(), sort_keys=True) for item in uow.projects.list()),
    )


def test_all_public_catalog_mutations_are_rejected_before_write(empty_uow):
    ensure_managed_catalog(empty_uow)
    empty_uow.commit()
    workflow, mode, phases, phase, instruction, agent, namespace = _managed_objects(empty_uow)
    before = _managed_snapshot(empty_uow)
    phase_ids = [int(item.id) for item in phases if item.id is not None]

    operations = [
        lambda: WorkflowService(empty_uow).create_workflow({"name": "TEST TRASH WORKFLOW"}),
        lambda: WorkflowService(empty_uow).update_workflow(int(workflow.id), {"name": "drift"}),
        lambda: WorkflowService(empty_uow).delete_workflow(int(workflow.id)),
        lambda: WorkflowService(empty_uow).create_mode(
            int(workflow.id), {"key": "trash", "name": "Trash"}
        ),
        lambda: PhaseServiceApp(empty_uow).create_phase(
            {"workflow_id": int(workflow.id), "mode_id": int(mode.id), "name": "trash"}
        ),
        lambda: PhaseServiceApp(empty_uow).update_phase(int(phase.id), {"name": "drift"}),
        lambda: PhaseServiceApp(empty_uow).delete_phase(int(phase.id)),
        lambda: PhaseServiceApp(empty_uow).reorder_phases(
            [(phase_id, index) for index, phase_id in enumerate(reversed(phase_ids), 1)]
        ),
        lambda: InstructionService(empty_uow).create_instruction(
            int(phase.id), {"description": "trash"}
        ),
        lambda: InstructionService(empty_uow).update_instruction(
            int(instruction["id"]), {"description": "drift"}
        ),
        lambda: InstructionService(empty_uow).delete_instruction(int(instruction["id"])),
        lambda: InstructionService(empty_uow).reorder_instructions(
            int(phase.id),
            [
                int(item["id"])
                for item in reversed(list(empty_uow.phase_instructions.list(int(phase.id))))
            ],
        ),
        lambda: PhaseService(empty_uow).update_phase_detail(
            int(phase.id), {"instructions": [], "checks": [], "evidence": []}
        ),
        lambda: AgentService(empty_uow).create_agent({"name": "test-trash-agent"}),
        lambda: AgentService(empty_uow).update_agent(int(agent.id), {"name": "drift"}),
        lambda: AgentService(empty_uow).delete_agent(int(agent.id)),
        lambda: ProjectService(empty_uow).create_project(
            {"code": "TMP", "name": "trash", "workflow_id": int(workflow.id)}
        ),
        lambda: ProjectService(empty_uow).update_project(int(namespace.id), {"name": "drift"}),
        lambda: ProjectService(empty_uow).update_project(
            int(namespace.id), {"workflow_id": int(workflow.id)}
        ),
        lambda: ProjectService(empty_uow).delete_project(int(namespace.id)),
    ]

    for operation in operations:
        with pytest.raises(ConflictError, match=MANAGED_CATALOG_IMMUTABLE_ERROR):
            operation()
        assert _managed_snapshot(empty_uow) == before
        assert validate_managed_catalog_state(empty_uow) is True


def test_unmanaged_database_keeps_crud_and_default_mode_compatibility(empty_uow):
    workflow = WorkflowService(empty_uow).create_workflow({"name": "Local workflow"})
    workflow_id = int(workflow["id"])
    WorkflowService(empty_uow).update_workflow(workflow_id, {"description": "editable"})
    mode = WorkflowService(empty_uow).create_mode(
        workflow_id, {"key": "second", "name": "Second"}
    )
    phase = PhaseServiceApp(empty_uow).create_phase(
        {"workflow_id": workflow_id, "mode_id": int(mode["id"]), "name": "Editable"}
    )
    AgentService(empty_uow).create_agent({"name": "local-agent"})
    namespace = ProjectService(empty_uow).create_project(
        {"code": "LOC", "workflow_id": workflow_id}
    )

    assert phase["mode_id"] == mode["id"]
    assert namespace["workflow_id"] == workflow_id
    assert validate_managed_catalog_state(empty_uow) is False


@pytest.mark.parametrize(
    "drift_kind",
    ["mode", "instruction", "skills", "check", "evidence", "profile"],
)
def test_validator_rejects_full_managed_content_drift(empty_uow, drift_kind: str):
    ensure_managed_catalog(empty_uow)
    empty_uow.commit()
    _workflow, mode, _phases, phase, instruction, agent, _namespace = _managed_objects(
        empty_uow
    )

    if drift_kind == "mode":
        row = empty_uow.session.get(db_models.WorkflowMode, int(mode.id))
        assert row is not None
        row.name = "Drifted mode"
    elif drift_kind == "instruction":
        empty_uow.phase_instructions.update(
            int(instruction["id"]), {"description": "drifted instruction"}
        )
    elif drift_kind == "skills":
        empty_uow.phase_instructions.update(
            int(instruction["id"]), {"skills": ["test-trash-skill"]}
        )
    elif drift_kind == "check":
        check = list(empty_uow.phase_checks.list(int(phase.id)))[0]
        empty_uow.phase_checks.update(int(check["id"]), {"description": "drifted check"})
    elif drift_kind == "evidence":
        evidence = list(empty_uow.phase_evidence_requirements.list(int(phase.id)))[0]
        empty_uow.phase_evidence_requirements.update(
            int(evidence["id"]), {"description": "drifted evidence"}
        )
    else:
        empty_uow.agents.update(int(agent.id), {"hermes_profile": "drifted-profile"})
    empty_uow.commit()

    with pytest.raises(ValueError):
        validate_managed_catalog_state(empty_uow)


def _install_runtime_credentials(monkeypatch, tmp_path: Path) -> tuple[str, str]:
    runtime_token = "r" * 48
    catalog_token = "c" * 48
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", catalog_token)
    config.get_settings.cache_clear()
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())
    return runtime_token, catalog_token


def test_runtime_capabilities_require_installed_managed_catalog(
    monkeypatch, tmp_path: Path
):
    runtime_token, _catalog_token = _install_runtime_credentials(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True
    )

    with TestClient(create_app()) as client:
        response = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {runtime_token}"},
        )

    assert response.status_code == 503
    assert response.json()["readiness"] == {
        "service": "not_ready",
        "schema": "ready",
        "catalog": "not_ready",
    }


def test_managed_catalog_keeps_runtime_step_and_history_available(monkeypatch, tmp_path):
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())
    _bootstrap_global_managed_catalog()
    runtime_token = "r" * 48
    assignment_token = "a" * 48
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"project_manager": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"project_manager": assignment_token}),
    )
    config.get_settings.cache_clear()
    assignment_payload = {
        "runtime_compatibility": _valid_compatibility(),
        "task": "PM-901",
        "workflow_key": "hermes-sdlc:project_manager",
        "role_key": "project_manager",
        "mode_key": "draft",
        "stage_key": "draft",
        "execution_scope": "business",
        "cycle_number": 0,
        "attempt_number": 1,
        "operation_key": "assign:pm-immutable-1",
        "business_task_ref": "business-task:pm-immutable-1@1",
        "root_task_ref": "business-task:pm-immutable-1@1",
        "work_item_ref": "business-task:pm-immutable-1@1",
        "work_item_revision": 1,
        "queue_item_ref": "queue-item:pm-immutable-1",
        "task_workspace_ref": "task-workspace:pm-immutable-1",
        "workspace_revision": 1,
        "decomposition_revision_ref": "decomposition:pm-immutable-1@1",
        "stage_revision": "draft@1",
        "assignment_ref": "assignment:pm-immutable-1",
        "workspace_generation": 0,
        "lease_generation": 0,
        "exact_input_refs": [
            {"kind": "business_task", "ref": "business-task:pm-immutable-1", "revision": "1"}
        ],
        "expected_revision": 0,
        "expected_status": "missing",
    }

    with TestClient(create_app()) as client:
        assigned_response = client.post(
            "/internal/runtime/assign",
            headers={"Authorization": f"Bearer {assignment_token}"},
            json=assignment_payload,
        )
        assert assigned_response.status_code == 200, assigned_response.text
        assigned = assigned_response.json()["result"]
        bind_response = client.post(
            "/internal/runtime/bind",
            headers={"Authorization": f"Bearer {assignment_token}"},
            json={
                "task": assigned["task_key"],
                "bind_operation_key": "bind:pm-immutable-1",
                "assignment_operation_key": assigned["assignment_operation_key"],
                "assignment_revision": assigned["assignment_revision"],
                "assignment_ref": assigned["assignment_ref"],
                "binding_ref": "binding:pm-immutable-1",
                "hermes_run_ref": "hermes-run:pm-immutable-1",
                "mode_key": assigned["mode_key"],
                "cycle_number": assigned["cycle_number"],
                "attempt_number": assigned["attempt_number"],
                "expected_binding_state": "unbound",
            },
        )
        assert bind_response.status_code == 200, bind_response.text
        bound = bind_response.json()["result"]
        step = client.post(
            "/internal/runtime/step",
            headers={"Authorization": f"Bearer {runtime_token}"},
            json={
                "task": bound["task_key"],
                "step_operation_key": "step:pm-immutable-1:instructions",
                "assignment_revision": bound["assignment_revision"],
                "assignment_ref": bound["assignment_ref"],
                "binding_ref": bound["binding_ref"],
                "hermes_run_ref": bound["hermes_run_ref"],
                "mode_key": bound["mode_key"],
                "cycle_number": bound["cycle_number"],
                "attempt_number": bound["attempt_number"],
                "expected_phase_code": bound["current_phase_code"],
                "expected_status": bound["status"],
            },
        )
        history = client.get(
            "/internal/runtime/history",
            headers={"Authorization": f"Bearer {runtime_token}"},
            params={"task": bound["task_key"]},
        )

    assert step.status_code == 200, step.text
    assert step.json()["result"]["mode_key"] == "draft"
    assert history.status_code == 200, history.text
    assert history.json()["result"]["count"] == 0


def test_live_catalog_drift_closes_health_capabilities_and_catalog(
    monkeypatch, tmp_path: Path
):
    _bootstrap_global_managed_catalog()
    runtime_token, catalog_token = _install_runtime_credentials(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True
    )

    with TestClient(create_app()) as client:
        with SAUnitOfWork() as drift:
            _workflow, _mode, _phases, _phase, _instruction, _agent, namespace = (
                _managed_objects(drift)
            )
            row = drift.session.get(db_models.Project, int(namespace.id))
            assert row is not None
            row.theme_color = "#22C55E"

        health = client.get("/health")
        capabilities = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {runtime_token}"},
        )
        catalog = client.get(
            "/internal/runtime/catalog",
            headers={"Authorization": f"Bearer {catalog_token}"},
        )

    assert health.status_code == 503
    assert health.json()["catalog"] == "error"
    assert capabilities.status_code == 503
    assert capabilities.json()["error_code"] == "runtime-capabilities-not-ready"
    assert capabilities.json()["readiness"]["catalog"] == "not_ready"
    assert catalog.status_code == 503
    assert catalog.json() == {"ok": False, "error": "Managed каталог временно недоступен"}


def test_startup_fails_closed_when_managed_catalog_drifted(monkeypatch):
    _bootstrap_global_managed_catalog()
    monkeypatch.setattr(
        "project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True
    )
    with SAUnitOfWork() as drift:
        _workflow, _mode, _phases, _phase, _instruction, _agent, namespace = (
            _managed_objects(drift)
        )
        row = drift.session.get(db_models.Project, int(namespace.id))
        assert row is not None
        row.theme_icon = "rocket"

    with pytest.raises(RuntimeError, match="Managed catalog is not ready"):
        with TestClient(create_app()):
            pass
