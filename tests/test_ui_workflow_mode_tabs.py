"""Focused UI coverage for workflow mode navigation and isolation."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from project_workflow.interfaces.ui import _app_state, app

pytestmark = [pytest.mark.ui]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _mode_ui_fixture(client: TestClient, *, rework_order: int = 2) -> dict[str, int]:
    workflow_response = client.post(
        "/api/workflows",
        json={"name": "Mode tabs workflow", "description": "UI mode isolation"},
    )
    assert workflow_response.status_code == 200
    workflow_id = workflow_response.json()["workflow_id"]

    default_mode = client.get(f"/api/workflows/{workflow_id}/modes").json()["modes"][0]
    rework_response = client.post(
        f"/api/workflows/{workflow_id}/modes",
        json={
            "key": "rework",
            "name": "Rework",
            "mode_order": rework_order,
            "role_key": "developer",
            "execution_scope": "delivery",
            "tech_workspace_policy": "required",
        },
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
    uow = _app_state.get_db()
    try:
        uow.phases.update(default_phase_id, {"name": "Default-only phase"})
        uow.phase_instructions.create(
            default_phase_id, {"description": "Default-only instruction"}
        )
        uow.commit()
    finally:
        uow.close()

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

    rework_instruction = client.post(
        "/api/instructions",
        json={"phase_id": rework_phase_ids[0], "description": "Rework-only instruction"},
    )
    assert rework_instruction.status_code == 200

    return {
        "workflow_id": workflow_id,
        "namespace_id": namespace_id,
        "default_mode_id": default_mode["id"],
        "rework_mode_id": rework_mode["id"],
        "default_phase_id": default_phase_id,
        "rework_phase_one_id": rework_phase_ids[0],
        "rework_phase_two_id": rework_phase_ids[1],
    }


def test_phases_selects_first_dispatchable_mode_and_separates_legacy_default(
    client: TestClient,
) -> None:
    fixture = _mode_ui_fixture(client)
    response = client.get(f"/phases?namespace_id={fixture['namespace_id']}")

    assert response.status_code == 200
    assert "Default-only phase" not in response.text
    assert "Rework phase one" in response.text
    assert 'aria-label="Режимы воркфлоу" data-testid="workflow-mode-tabs"' in response.text
    assert 'aria-current="page"' in response.text
    assert 'role="tab"' not in response.text
    assert 'aria-selected=' not in response.text
    assert 'data-testid="workflow-mode-tab-active"' in response.text
    assert 'data-mode-key="default"' not in response.text
    assert 'data-testid="legacy-default-mode"' in response.text
    assert "Системный режим" in response.text
    assert "<code>default</code>" in response.text
    assert 'data-testid="mode-policy-notice" data-read-only="false"' in response.text
    assert 'data-mode-key="rework"' in response.text
    assert (
        f'href="/phases?workflow_id={fixture["workflow_id"]}'
        f'&namespace_id={fixture["namespace_id"]}&mode=rework"'
    ) in response.text
    assert ".workflow-mode-tabs{display:flex" in response.text
    assert "overflow-x:auto" in response.text
    assert "event.key==='ArrowRight'" not in response.text


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
    assert "const modeReadOnly=false;" in response.text

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

    refreshed = client.get(str(response.request.url))
    assert refreshed.status_code == 200
    assert f'data-mode-id="{fixture["rework_mode_id"]}" data-mode-key="rework"' in refreshed.text
    assert "Default-only phase" not in refreshed.text


def test_unknown_and_foreign_modes_fail_closed(client: TestClient) -> None:
    fixture = _mode_ui_fixture(client)
    foreign_workflow = client.post("/api/workflows", json={"name": "Foreign modes"}).json()["workflow_id"]
    foreign_mode = client.post(
        f"/api/workflows/{foreign_workflow}/modes",
        json={"key": "foreign-only", "name": "Foreign only"},
    )
    assert foreign_mode.status_code == 200

    for mode_key in ("missing", "foreign-only", "%20"):
        response = client.get(
            f"/phases?workflow_id={fixture['workflow_id']}"
            f"&namespace_id={fixture['namespace_id']}&mode={mode_key}"
        )
        assert response.status_code == 404
        assert "Режим воркфлоу не найден" in response.text
        assert "Default-only phase" not in response.text
        assert "Rework phase one" not in response.text
        assert 'href="/phase/' not in response.text


def test_default_only_workflow_is_explicitly_legacy_and_read_only(client: TestClient) -> None:
    workflow_id = client.post(
        "/api/workflows",
        json={"name": "Legacy-only workflow"},
    ).json()["workflow_id"]
    namespace_id = client.post(
        "/api/namespaces",
        json={
            "name": "Legacy-only namespace",
            "workflow_id": workflow_id,
            "cli_command": f"legacy-only-{uuid.uuid4().hex[:8]}",
        },
    ).json()["namespace_id"]
    phase = client.get(f"/api/phases?workflow_id={workflow_id}").json()["phases"][0]

    response = client.get(f"/phases?namespace_id={namespace_id}")

    assert response.status_code == 200
    assert phase["name"] in response.text
    assert 'data-testid="workflow-mode-tabs"' not in response.text
    assert 'data-testid="legacy-default-mode"' in response.text
    assert 'data-testid="mode-policy-notice" data-read-only="true"' in response.text
    assert "Системный режим сохранён для чтения перенесённых данных" in response.text
    assert "const modeReadOnly=true;" in response.text
    assert 'onclick="addPhaseAfter(this)"' in response.text
    assert 'disabled title="Режим доступен только для чтения"' in response.text

    detail = client.get(f"/phase/{phase['id']}?mode=default&namespace_id={namespace_id}")
    instructions = client.get(
        f"/instructions?phase_id={phase['id']}&mode=default&namespace_id={namespace_id}"
    )
    assert detail.status_code == instructions.status_code == 200
    assert 'disabled data-testid="mode-editor-read-only"' in detail.text
    assert 'disabled data-testid="mode-editor-read-only"' in instructions.text


def test_incomplete_mode_is_visible_but_never_selected_over_dispatchable_mode(
    client: TestClient,
) -> None:
    fixture = _mode_ui_fixture(client, rework_order=3)
    incomplete = client.post(
        f"/api/workflows/{fixture['workflow_id']}/modes",
        json={"key": "draft", "name": "Draft", "mode_order": 2},
    )
    assert incomplete.status_code == 200
    draft_mode = incomplete.json()["mode"]
    uow = _app_state.get_db()
    try:
        uow.phases.create(
            {
                "workflow_id": fixture["workflow_id"],
                "mode_id": draft_mode["id"],
                "phase_order": 1,
                "code": f"draft-{uuid.uuid4().hex[:8]}",
                "name": "Draft-only phase",
                "description": "",
                "execution_type": "sync",
            }
        )
        uow.commit()
    finally:
        uow.close()

    automatic = client.get(f"/phases?namespace_id={fixture['namespace_id']}")
    assert automatic.status_code == 200
    assert "Rework phase one" in automatic.text
    assert "Draft-only phase" not in automatic.text

    direct = client.get(
        f"/phases?workflow_id={fixture['workflow_id']}"
        f"&namespace_id={fixture['namespace_id']}&mode=draft"
    )
    assert direct.status_code == 200
    assert "Draft-only phase" in direct.text
    assert "Rework phase one" not in direct.text
    assert 'class="workflow-mode-tab is-invalid"' in direct.text
    assert "Конфигурация неполна · только чтение" in direct.text
    assert 'data-read-only="true"' in direct.text
    assert "const modeReadOnly=true;" in direct.text


def test_explicit_legacy_deep_link_never_implies_dispatchability(client: TestClient) -> None:
    fixture = _mode_ui_fixture(client)
    response = client.get(
        f"/phases?workflow_id={fixture['workflow_id']}"
        f"&namespace_id={fixture['namespace_id']}&mode=default"
    )

    assert response.status_code == 200
    assert "Default-only phase" in response.text
    assert "Rework phase one" not in response.text
    assert 'data-testid="legacy-default-mode"' in response.text
    assert "не используется для новых назначений" in response.text
    assert 'data-read-only="true"' in response.text


def test_detail_and_instruction_navigation_keep_owning_mode_without_cross_mode_content(
    client: TestClient,
) -> None:
    fixture = _mode_ui_fixture(client)
    phase_id = fixture["rework_phase_one_id"]
    detail = client.get(f"/phase/{phase_id}?namespace_id={fixture['namespace_id']}")

    assert detail.status_code == 200
    assert "Rework-only instruction" in detail.text
    assert "Default-only instruction" not in detail.text
    assert 'data-testid="mode-policy-notice" data-read-only="false"' in detail.text
    assert 'data-testid="mode-editor-read-only"' not in detail.text
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
    assert 'data-testid="mode-editor-read-only"' not in instructions.text
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
