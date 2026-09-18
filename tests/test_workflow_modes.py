"""Workflow mode and cycle regression tests."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from project_workflow.interfaces.ui import app

    return TestClient(app)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_workflow_creation_always_creates_default_mode(client):
    from project_workflow.interfaces.ui import _app_state

    workflow = _app_state.workflow_service().create_workflow(
        {"name": _unique("modes"), "_skip_default_phase": True}
    )
    modes = _app_state.workflow_mode_service().list_modes(workflow["id"])

    assert [(mode["key"], mode["mode_order"]) for mode in modes] == [("default", 1)]


def test_same_phase_code_is_unique_inside_mode_not_workflow(client):
    from project_workflow.interfaces.ui import _app_state

    workflow = _app_state.workflow_service().create_workflow(
        {"name": _unique("developer"), "_skip_default_phase": True}
    )
    default_mode = _app_state.workflow_mode_service().list_modes(workflow["id"])[0]
    rework_mode = _app_state.workflow_mode_service().create_mode(
        workflow["id"], {"key": "rework", "name": "Доработка"}
    )

    initial = _app_state.phase_service().create_phase(
        {
            "workflow_id": workflow["id"],
            "mode_id": default_mode["id"],
            "code": "inspect",
            "name": "Изучить задачу",
            "phase_order": 1,
        }
    )
    rework = _app_state.phase_service().create_phase(
        {
            "workflow_id": workflow["id"],
            "mode_id": rework_mode["id"],
            "code": "inspect",
            "name": "Изучить замечания",
            "phase_order": 1,
        }
    )

    assert initial["mode_key"] == "default"
    assert rework["mode_key"] == "rework"
    assert [p["id"] for p in _app_state.phase_service().list_phases(workflow["id"])] == [initial["id"]]
    assert [p["id"] for p in _app_state.phase_service().list_phases(workflow["id"], rework_mode["id"])] == [
        rework["id"]
    ]


def test_history_keeps_rework_cycles_separate(client):
    from project_workflow.interfaces.ui import _app_state

    uow = _app_state.get_db()
    workflow = _app_state.workflow_service().create_workflow(
        {"name": _unique("cycles"), "_skip_default_phase": True}
    )
    rework_mode = _app_state.workflow_mode_service().create_mode(
        workflow["id"], {"key": "rework", "name": "Доработка"}
    )
    phase = _app_state.phase_service().create_phase(
        {
            "workflow_id": workflow["id"],
            "mode_id": rework_mode["id"],
            "code": "fix",
            "name": "Исправить дефекты",
            "phase_order": 1,
        }
    )
    project = _app_state.project_service().create_project(
        {"workflow_id": workflow["id"], "code": _unique("PRJ"), "name": "Cycle project"}
    )
    task = _app_state.task_service().create_task(
        {
            "project_id": project["id"],
            "task_key": _unique("TASK"),
            "current_phase": "fix",
            "current_mode_id": rework_mode["id"],
            "cycle_number": 1,
        }
    )

    uow.tasks.add_history(task["id"], phase["id"], "done", rework_mode["id"], 1)
    uow.tasks.add_history(task["id"], phase["id"], "done", rework_mode["id"], 2)
    uow.commit()

    history = uow.tasks.get_history(task["id"])
    assert {(row["mode_id"], row["cycle_number"], row["phase_id"]) for row in history} == {
        (rework_mode["id"], 1, phase["id"]),
        (rework_mode["id"], 2, phase["id"]),
    }


def test_mode_api_and_phase_tabs(client):
    workflow = client.post("/api/workflows", json={"name": _unique("api-modes")}).json()["workflow"]

    created = client.post(
        f"/api/workflows/{workflow['id']}/modes",
        json={"key": "rework", "name": "Доработка"},
    )
    assert created.status_code == 200
    mode = created.json()["mode"]

    response = client.get(f"/phases?workflow_id={workflow['id']}&mode_id={mode['id']}")
    assert response.status_code == 200
    assert 'data-testid="workflow-mode-tabs"' in response.text
    assert 'data-mode-key="rework"' in response.text


def test_mode_api_rejects_duplicate_and_invalid_keys(client):
    workflow = client.post("/api/workflows", json={"name": _unique("api-invalid")}).json()["workflow"]

    assert client.post(
        f"/api/workflows/{workflow['id']}/modes", json={"key": "Rework!", "name": "Bad"}
    ).status_code == 400
    assert client.post(
        f"/api/workflows/{workflow['id']}/modes", json={"key": "rework", "name": "Доработка"}
    ).status_code == 200
    assert client.post(
        f"/api/workflows/{workflow['id']}/modes", json={"key": "rework", "name": "Again"}
    ).status_code == 409


def test_legacy_phase_listing_uses_first_canonical_mode_without_creating_default(client):
    from project_workflow.interfaces.ui import _app_state

    workflow = _app_state.workflow_service().create_workflow(
        {
            "name": _unique("canonical-no-default"),
            "_skip_default_phase": True,
            "_default_mode_key": "initial",
            "_default_mode_name": "Первичная разработка",
        }
    )
    mode = _app_state.workflow_mode_service().list_modes(workflow["id"])[0]
    _app_state.phase_service().create_phase(
        {
            "workflow_id": workflow["id"],
            "mode_id": mode["id"],
            "code": "initial.context",
            "name": "Контекст",
            "phase_order": 1,
        }
    )

    phases = _app_state.phase_service().list_phases(workflow["id"])
    modes = _app_state.workflow_mode_service().list_modes(workflow["id"])

    assert [phase["code"] for phase in phases] == ["initial.context"]
    assert [item["key"] for item in modes] == ["initial"]
