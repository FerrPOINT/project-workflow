"""Focused UI coverage for workflow mode navigation and isolation."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from project_workflow.interfaces.ui import app

pytestmark = [pytest.mark.ui]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _mode_ui_fixture(client: TestClient) -> dict[str, int]:
    workflow_response = client.post(
        "/api/workflows",
        json={"name": "Mode tabs workflow", "description": "UI mode isolation"},
    )
    assert workflow_response.status_code == 200
    workflow_id = workflow_response.json()["workflow_id"]

    default_mode = client.get(f"/api/workflows/{workflow_id}/modes").json()["modes"][0]
    rework_response = client.post(
        f"/api/workflows/{workflow_id}/modes",
        json={"key": "rework", "name": "Rework", "mode_order": 2},
    )
    assert rework_response.status_code == 200
    rework_mode = rework_response.json()["mode"]

    namespace_response = client.post(
        "/api/namespaces",
        json={
            "name": "Mode tabs namespace",
            "workflow_id": workflow_id,
            "cli_command": f"mode-tabs-{uuid.uuid4().hex[:8]}",
        },
    )
    assert namespace_response.status_code == 200
    namespace_id = namespace_response.json()["namespace_id"]

    default_phases = client.get(
        f"/api/phases?workflow_id={workflow_id}&modeId={default_mode['id']}"
    ).json()["phases"]
    assert len(default_phases) == 1
    default_phase_id = default_phases[0]["id"]
    assert client.put(
        f"/api/phases/{default_phase_id}",
        json={"name": "Default-only phase"},
    ).status_code == 200

    rework_phase_ids = []
    for order, name in enumerate(("Rework phase one", "Rework phase two"), 1):
        response = client.post(
            "/api/phases",
            json={
                "workflow_id": workflow_id,
                "mode_id": rework_mode["id"],
                "phase_order": order,
                "name": name,
            },
        )
        assert response.status_code == 200
        rework_phase_ids.append(response.json()["phase_id"])

    default_instruction = client.post(
        "/api/instructions",
        json={"phase_id": default_phase_id, "description": "Default-only instruction"},
    )
    rework_instruction = client.post(
        "/api/instructions",
        json={"phase_id": rework_phase_ids[0], "description": "Rework-only instruction"},
    )
    assert default_instruction.status_code == rework_instruction.status_code == 200

    return {
        "workflow_id": workflow_id,
        "namespace_id": namespace_id,
        "default_mode_id": default_mode["id"],
        "rework_mode_id": rework_mode["id"],
        "default_phase_id": default_phase_id,
        "rework_phase_one_id": rework_phase_ids[0],
        "rework_phase_two_id": rework_phase_ids[1],
    }


def test_phases_defaults_to_default_mode_and_renders_ordered_accessible_tabs(client: TestClient) -> None:
    fixture = _mode_ui_fixture(client)
    response = client.get(f"/phases?namespace_id={fixture['namespace_id']}")

    assert response.status_code == 200
    assert "Default-only phase" in response.text
    assert "Rework phase one" not in response.text
    assert 'role="tablist" aria-label="Режим воркфлоу" data-testid="workflow-mode-tabs"' in response.text
    assert 'aria-selected="true" aria-current="page" data-testid="workflow-mode-tab-active"' in response.text
    assert response.text.index(">Default<") < response.text.index(">Rework<")
    assert (
        f'href="/phases?workflow_id={fixture["workflow_id"]}'
        f'&namespace_id={fixture["namespace_id"]}&mode=rework"'
    ) in response.text
    assert ".workflow-mode-tabs{display:flex" in response.text
    assert "overflow-x:auto" in response.text
    assert "event.key==='ArrowRight'" in response.text


def test_mode_switch_filters_disjoint_phases_and_preserves_create_scope(client: TestClient) -> None:
    fixture = _mode_ui_fixture(client)
    response = client.get(
        f"/phases?workflow_id={fixture['workflow_id']}&namespace_id={fixture['namespace_id']}&mode=rework"
    )

    assert response.status_code == 200
    assert "Rework phase one" in response.text
    assert "Rework phase two" in response.text
    assert "Default-only phase" not in response.text
    assert f'data-mode-id="{fixture["rework_mode_id"]}" data-mode-key="rework"' in response.text
    assert "mode_id:parseInt(modeId,10)" in response.text
    assert f'/phase/{fixture["rework_phase_one_id"]}?mode=rework' in response.text

    reorder = client.put(
        "/api/phases/order",
        json={
            "orders": [
                {"phase_id": fixture["rework_phase_two_id"], "phase_order": 1},
                {"phase_id": fixture["rework_phase_one_id"], "phase_order": 2},
            ]
        },
    )
    assert reorder.status_code == 200
    default_phases = client.get(
        f"/api/phases?workflow_id={fixture['workflow_id']}&modeId={fixture['default_mode_id']}"
    ).json()["phases"]
    assert [(phase["id"], phase["phase_order"]) for phase in default_phases] == [
        (fixture["default_phase_id"], 1)
    ]


def test_unknown_and_foreign_modes_fail_closed(client: TestClient) -> None:
    fixture = _mode_ui_fixture(client)
    foreign_workflow = client.post("/api/workflows", json={"name": "Foreign modes"}).json()["workflow_id"]
    foreign_mode = client.post(
        f"/api/workflows/{foreign_workflow}/modes",
        json={"key": "foreign-only", "name": "Foreign only"},
    )
    assert foreign_mode.status_code == 200

    for mode_key in ("missing", "foreign-only"):
        response = client.get(
            f"/phases?workflow_id={fixture['workflow_id']}"
            f"&namespace_id={fixture['namespace_id']}&mode={mode_key}"
        )
        assert response.status_code == 404
        assert "Режим воркфлоу не найден" in response.text
        assert "Default-only phase" not in response.text
        assert "Rework phase one" not in response.text
        assert 'href="/phase/' not in response.text


def test_detail_and_instruction_navigation_keep_owning_mode_without_cross_mode_content(
    client: TestClient,
) -> None:
    fixture = _mode_ui_fixture(client)
    phase_id = fixture["rework_phase_one_id"]
    detail = client.get(f"/phase/{phase_id}?namespace_id={fixture['namespace_id']}")

    assert detail.status_code == 200
    assert "Rework-only instruction" in detail.text
    assert "Default-only instruction" not in detail.text
    assert (
        f'href="/phases?workflow_id={fixture["workflow_id"]}&mode=rework'
        f'&namespace_id={fixture["namespace_id"]}"'
    ) in detail.text

    instructions = client.get(
        f"/instructions?phase_id={phase_id}&namespace_id={fixture['namespace_id']}&mode=rework"
    )
    assert instructions.status_code == 200
    assert "Rework-only instruction" in instructions.text
    assert "Default-only instruction" not in instructions.text
    assert (
        f'href="/phase/{phase_id}?mode=rework&namespace_id={fixture["namespace_id"]}"'
    ) in instructions.text

    for path in (
        f"/phase/{phase_id}?namespace_id={fixture['namespace_id']}&mode=default",
        f"/instructions?phase_id={phase_id}&namespace_id={fixture['namespace_id']}&mode=default",
    ):
        rejected = client.get(path)
        assert rejected.status_code == 404
        assert "Фаза недоступна в выбранном режиме воркфлоу" in rejected.text
        assert "Rework-only instruction" not in rejected.text

    default_instructions = client.get(
        f"/api/phases/{fixture['default_phase_id']}/instructions"
    ).json()["instructions"]
    assert [item["description"] for item in default_instructions] == ["Default-only instruction"]
