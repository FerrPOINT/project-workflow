"""Fail-closed contracts for the immutable managed workflow catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.project import ProjectService
from project_workflow.application.workflow import WorkflowService
from project_workflow.infrastructure.db import models as db_models
from project_workflow.infrastructure.db.managed_catalog import (
    ensure_managed_catalog,
    validate_managed_catalog_state,
)
from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests.test_configured_cli import configured as configured
from tests.test_runtime_capabilities import _install_manifest, _valid_manifest

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
    namespace = uow.projects.get_by_cli_command("workflow-project_manager")
    assert namespace is not None and namespace.id is not None
    return workflow, mode, phases, phase, instruction, namespace, namespace


@pytest.mark.parametrize(
    "drift_kind",
    ["mode", "instruction", "skills", "check", "evidence"],
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
        row.role_key = "architect"
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
        raise AssertionError("Unexpected drift kind")
    empty_uow.commit()

    with pytest.raises(ValueError):
        validate_managed_catalog_state(empty_uow)


def _install_runtime_credentials(monkeypatch, tmp_path: Path) -> tuple[str, str]:
    runtime_token = "r" * 48
    catalog_token = "c" * 48
    from project_workflow.infrastructure import namespace_auth

    runtime_token = "sdlc_pat_" + runtime_token
    subject = "99999999-9999-4999-8999-999999999999"
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON", json.dumps({subject: "developer"}))
    def introspect(authorization, *, require_service_account=False):
        assert require_service_account and authorization == "Bearer " + runtime_token
        return namespace_auth.NamespacePrincipal("https://auth.test", subject), ["project-workflow:read"]
    monkeypatch.setattr(namespace_auth, "introspect", introspect)
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




@pytest.mark.parametrize("theme", [{"theme_color": "#22C55E"}, {"theme_icon": "folder"},
                                  {"theme_color": "#DD5577", "theme_icon": "code"}])
def test_namespace_theme_edits_keep_editor_and_executor_available(
    configured, monkeypatch, tmp_path: Path, theme
):
    runtime_token, catalog_token = _install_runtime_credentials(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True
    )

    with TestClient(create_app()) as client:
        with SAUnitOfWork() as drift:
            from project_workflow.infrastructure.db.single_task_catalog import observe_installation

            installation = observe_installation(drift)
            namespace = next(item for item in installation.bindings if item.role_key == "developer")
            row = drift.session.get(db_models.Project, int(namespace.namespace_id))
            assert row is not None
            for field, value in theme.items():
                setattr(row, field, value)
            drift.commit()

        health = client.get("/health")
        capabilities = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {runtime_token}"},
        )
        catalog = client.get(
            "/internal/runtime/catalog",
            headers={"Authorization": f"Bearer {catalog_token}"},
        )

    assert health.status_code == 200
    assert health.json()["catalog"] == "ok"
    assert capabilities.status_code == 200, capabilities.text
    assert capabilities.json()["readiness"]["catalog"] == "ready"
    assert catalog.status_code == 200, catalog.text


def test_startup_keeps_saved_namespace_theme(monkeypatch):
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

    with TestClient(create_app()) as client:
        assert client.get("/namespaces").status_code == 200
    with SAUnitOfWork() as readback:
        assert readback.projects.get_by_id(int(namespace.id)).theme_icon == "rocket"


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
    namespace = ProjectService(empty_uow).create_project(
        {"code": "LOC", "workflow_id": workflow_id}
    )

    assert phase["mode_id"] == mode["id"]
    assert namespace["workflow_id"] == workflow_id
    assert validate_managed_catalog_state(empty_uow) is False
