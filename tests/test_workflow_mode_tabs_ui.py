"""Focused UI/API coverage for Workflow -> Mode -> Phases navigation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from project_workflow.interfaces.ui import _app_state, app

pytestmark = [pytest.mark.ui]

client = TestClient(app)


def _developer_catalog() -> dict[str, int]:
    uow = _app_state.get_db()
    try:
        workflow_id = uow.workflows.create(
            {
                "key": "hermes-sdlc:developer-ui-test",
                "name": "Developer",
                "description": "Developer mode navigation",
            }
        )
        default = uow.workflows.get_mode_by_key(workflow_id, "default")
        assert default is not None and default.id is not None
        initial_id = uow.workflows.create_mode(
            {
                "workflow_id": workflow_id,
                "key": "initial",
                "name": "Первичная разработка",
                "mode_order": 2,
            }
        )
        rework_id = uow.workflows.create_mode(
            {
                "workflow_id": workflow_id,
                "key": "rework",
                "name": "Доработка",
                "mode_order": 3,
            }
        )
        default_phase_id = uow.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": default.id,
                "code": "default-start",
                "name": "Default phase",
                "phase_order": 1,
            }
        )
        initial_phase_id = uow.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": initial_id,
                "code": "initial-start",
                "name": "Initial phase",
                "phase_order": 1,
            }
        )
        rework_phase_id = uow.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": rework_id,
                "code": "rework-start",
                "name": "Rework phase",
                "phase_order": 1,
            }
        )
        uow.commit()
        return {
            "workflow_id": workflow_id,
            "default_mode_id": default.id,
            "initial_mode_id": initial_id,
            "rework_mode_id": rework_id,
            "default_phase_id": default_phase_id,
            "initial_phase_id": initial_phase_id,
            "rework_phase_id": rework_phase_id,
        }
    finally:
        uow.close()


def test_existing_workflow_opens_default_mode_with_stable_accessible_controls():
    catalog = _developer_catalog()

    response = client.get(f"/phases?workflow_id={catalog['workflow_id']}")

    assert response.status_code == 200
    assert 'data-testid="workflow-mode-navigation"' in response.text
    assert 'data-testid="workflow-mode-tabs"' in response.text
    assert 'data-testid="workflow-mode-tab-default"' in response.text
    assert 'data-testid="workflow-mode-select"' in response.text
    assert 'role="tab"' in response.text
    default_tab = response.text.split('data-testid="workflow-mode-tab-default"', 1)[0].rsplit("<a", 1)[1]
    assert 'aria-selected="true"' in default_tab
    assert "Default phase" in response.text
    assert "Initial phase" not in response.text
    assert "Rework phase" not in response.text


def test_developer_initial_and_rework_tabs_scope_phase_content_and_refresh():
    catalog = _developer_catalog()
    initial_url = (
        f"/phases?workflow_id={catalog['workflow_id']}"
        f"&mode_id={catalog['initial_mode_id']}"
    )
    rework_url = (
        f"/phases?workflow_id={catalog['workflow_id']}"
        f"&mode_id={catalog['rework_mode_id']}"
    )

    initial = client.get(initial_url)
    rework = client.get(rework_url)
    refreshed_rework = client.get(rework_url)

    assert initial.status_code == rework.status_code == refreshed_rework.status_code == 200
    assert "Initial phase" in initial.text
    assert "Rework phase" not in initial.text
    assert "Rework phase" in rework.text
    assert "Initial phase" not in rework.text
    assert rework.text == refreshed_rework.text
    assert f'data-mode-id="{catalog["rework_mode_id"]}"' in rework.text
    assert rework.text.index("Default") < rework.text.index("Первичная разработка") < rework.text.index("Доработка")


def test_phase_api_filters_and_creates_inside_selected_mode_while_legacy_defaults():
    catalog = _developer_catalog()

    created = client.post(
        "/api/phases",
        json={
            "workflow_id": catalog["workflow_id"],
            "mode_id": catalog["rework_mode_id"],
            "phase_order": 2,
            "name": "Second rework phase",
        },
    )
    legacy = client.post(
        "/api/phases",
        json={
            "workflow_id": catalog["workflow_id"],
            "phase_order": 2,
            "name": "Second default phase",
        },
    )
    rework = client.get(
        f"/api/phases?workflow_id={catalog['workflow_id']}&mode_id={catalog['rework_mode_id']}"
    )
    default = client.get(f"/api/phases?workflow_id={catalog['workflow_id']}")

    assert created.status_code == legacy.status_code == rework.status_code == default.status_code == 200
    assert created.json()["phase"]["mode_id"] == catalog["rework_mode_id"]
    assert legacy.json()["phase"]["mode_id"] == catalog["default_mode_id"]
    assert rework.json()["mode"]["key"] == "rework"
    assert [item["name"] for item in rework.json()["phases"]] == [
        "Rework phase",
        "Second rework phase",
    ]
    assert [item["name"] for item in default.json()["phases"]] == [
        "Default phase",
        "Second default phase",
    ]


def test_phase_detail_returns_to_its_mode_and_keeps_mode_local_graph():
    catalog = _developer_catalog()

    response = client.get(f"/phase/{catalog['rework_phase_id']}")

    assert response.status_code == 200
    assert (
        f'href="/phases?workflow_id={catalog["workflow_id"]}'
        f'&mode_id={catalog["rework_mode_id"]}'
    ) in response.text
    assert "Rework phase" in response.text
    assert "Initial phase" not in response.text


@pytest.mark.parametrize("raw_mode_id", ["bad", "0", "-1"])
def test_malformed_mode_deep_link_fails_safely(raw_mode_id: str):
    catalog = _developer_catalog()

    response = client.get(
        f"/phases?workflow_id={catalog['workflow_id']}&mode_id={raw_mode_id}"
    )

    assert response.status_code == 422
    assert "Некорректный mode_id" in response.text
    assert "Initial phase" not in response.text
    assert "Rework phase" not in response.text


def test_deleted_or_foreign_mode_deep_link_does_not_fall_through_to_other_phases():
    catalog = _developer_catalog()
    uow = _app_state.get_db()
    try:
        other_workflow_id = uow.workflows.create({"name": "Other workflow"})
        foreign_mode = uow.workflows.get_mode_by_key(other_workflow_id, "default")
        assert foreign_mode is not None and foreign_mode.id is not None
        foreign_mode_id = foreign_mode.id
        uow.commit()
    finally:
        uow.close()

    for mode_id in (999_999, foreign_mode_id):
        page = client.get(
            f"/phases?workflow_id={catalog['workflow_id']}&mode_id={mode_id}"
        )
        api = client.get(
            f"/api/phases?workflow_id={catalog['workflow_id']}&mode_id={mode_id}"
        )
        assert page.status_code == 404
        assert "Режим воркфлоу не найден" in page.text
        assert "Initial phase" not in page.text
        assert "Rework phase" not in page.text
        assert api.status_code == 404
        assert api.json() == {
            "ok": False,
            "error": "Режим не найден в выбранном воркфлоу",
        }
