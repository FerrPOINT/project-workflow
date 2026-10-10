"""The installed catalog must remain editable through the normal human API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app

pytestmark = pytest.mark.unit


def test_installed_instruction_and_phase_edits_survive_readback_and_restart(monkeypatch):
    monkeypatch.setattr(
        "project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True,
    )
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow)
        namespace = uow.projects.get_by_cli_command("workflow-architect")
        assert namespace is not None and namespace.id is not None
        mode = uow.workflows.list_modes(namespace.workflow_id)[0]
        phase = uow.phases.list(namespace.workflow_id, mode_id=mode.id)[0]
        assert phase.id is not None
        instruction = uow.phase_instructions.list(phase.id)[0]
        namespace_id, phase_id, instruction_id = namespace.id, phase.id, instruction["id"]

    with TestClient(create_app()) as client:
        saved = client.put(
            f"/api/instructions/{instruction_id}?namespace_id={namespace_id}",
            json={"description": "Saved instruction text"},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["instruction"]["description"] == "Saved instruction text"
        saved_phase = client.put(
            f"/api/phases/{phase_id}?namespace_id={namespace_id}",
            json={"name": "Saved phase name", "description": "Saved phase description"},
        )
        assert saved_phase.status_code == 200, saved_phase.text

    with TestClient(create_app()) as restarted:
        detail = restarted.get(f"/phase/{phase_id}?namespace_id={namespace_id}")
        assert detail.status_code == 200, detail.text
        assert "Saved instruction text" in detail.text
        assert "Saved phase name" in detail.text
        assert "Saved phase description" in detail.text
        health = restarted.get("/health")
        assert health.status_code == 200, health.text


def test_installed_catalog_does_not_block_unrelated_crud():
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow)
    with TestClient(create_app()) as client:
        workflow = client.post("/api/workflows", json={"name": "Another workflow"})
        assert workflow.status_code == 200, workflow.text
        agent = client.post("/api/agents", json={"name": "another-agent"})
        assert agent.status_code == 200, agent.text


def test_init_db_preserves_saved_catalog_edits(tmp_path, monkeypatch):
    from project_workflow import config
    from project_workflow.infrastructure.db.session import ensure_migrated, get_engine, reset_engine
    from scripts import init_db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'saved-catalog.db'}")
    config.get_settings.cache_clear()
    reset_engine()
    ensure_migrated(get_engine())

    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow)
        workflow = uow.workflows.list()[0]
        mode = uow.workflows.list_modes(workflow.id)[0]
        phase = uow.phases.list(workflow.id, mode_id=mode.id)[0]
        instruction = uow.phase_instructions.list(phase.id)[0]
        uow.phase_instructions.update(instruction["id"], {"description": "Saved before migration"})
        instruction_id = instruction["id"]

    assert init_db.main() == 0
    with SAUnitOfWork() as readback:
        assert readback.phase_instructions.get_by_id(instruction_id)["description"] == "Saved before migration"
