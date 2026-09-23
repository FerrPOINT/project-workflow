"""HTTP regression coverage for workflow-mode mutation policy."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from project_workflow.interfaces.ui import _app_state, app

pytestmark = [pytest.mark.ui]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _create_workflow(client: TestClient, name: str) -> tuple[int, dict[str, Any]]:
    response = client.post("/api/workflows", json={"name": name})
    assert response.status_code == 200
    workflow_id = response.json()["workflow_id"]
    default_mode = client.get(f"/api/workflows/{workflow_id}/modes").json()["modes"][0]
    return workflow_id, default_mode


def _create_mode(
    client: TestClient,
    workflow_id: int,
    *,
    key: str,
    configured: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"key": key, "name": key.title(), "mode_order": 2}
    if configured:
        payload.update(
            role_key="developer",
            execution_scope="delivery",
            tech_workspace_policy="required",
        )
    response = client.post(f"/api/workflows/{workflow_id}/modes", json=payload)
    assert response.status_code == 200
    return response.json()["mode"]


def _seed_mode_content(
    workflow_id: int,
    mode_id: int,
    *,
    existing_phase_id: int | None = None,
) -> dict[str, Any]:
    uow = _app_state.get_db()
    try:
        if existing_phase_id is None:
            first_phase_id = uow.phases.create(
                {
                    "workflow_id": workflow_id,
                    "mode_id": mode_id,
                    "code": f"seed-{mode_id}-one",
                    "name": "Первая фаза",
                    "description": "",
                    "phase_order": 1,
                    "execution_type": "sync",
                }
            )
        else:
            first_phase_id = existing_phase_id
            uow.phases.update(first_phase_id, {"name": "Первая фаза"})
        second_phase_id = uow.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": mode_id,
                "code": f"seed-{mode_id}-two",
                "name": "Вторая фаза",
                "description": "",
                "phase_order": 2,
                "execution_type": "sync",
            }
        )
        first_instruction_id = uow.phase_instructions.create(
            first_phase_id, {"description": "Первая инструкция"}
        )
        second_instruction_id = uow.phase_instructions.create(
            first_phase_id, {"description": "Вторая инструкция"}
        )
        uow.commit()
        return {
            "workflow_id": workflow_id,
            "mode_id": mode_id,
            "phase_ids": [first_phase_id, second_phase_id],
            "instruction_ids": [first_instruction_id, second_instruction_id],
        }
    finally:
        uow.close()


def _snapshot(client: TestClient, seeded: dict[str, Any]) -> tuple[Any, Any]:
    phases_response = client.get(
        f"/api/phases?workflow_id={seeded['workflow_id']}&modeId={seeded['mode_id']}"
    )
    instructions_response = client.get(
        f"/api/phases/{seeded['phase_ids'][0]}/instructions"
    )
    assert phases_response.status_code == instructions_response.status_code == 200
    return phases_response.json()["phases"], instructions_response.json()["instructions"]


def _all_mutations(client: TestClient, seeded: dict[str, Any]) -> list[Any]:
    first_phase_id, second_phase_id = seeded["phase_ids"]
    first_instruction_id, second_instruction_id = seeded["instruction_ids"]
    return [
        client.post(
            "/api/phases",
            json={
                "workflow_id": seeded["workflow_id"],
                "mode_id": seeded["mode_id"],
                "phase_order": 3,
                "name": "Новая фаза",
            },
        ),
        client.put(f"/api/phases/{first_phase_id}", json={"name": "Изменённая фаза"}),
        client.delete(f"/api/phases/{second_phase_id}"),
        client.put(
            "/api/phases/order",
            json={
                "orders": [
                    {"phase_id": second_phase_id, "phase_order": 1},
                    {"phase_id": first_phase_id, "phase_order": 2},
                ]
            },
        ),
        client.post(
            "/api/instructions",
            json={"phase_id": first_phase_id, "description": "Новая инструкция"},
        ),
        client.put(
            f"/api/instructions/{first_instruction_id}",
            json={"description": "Изменённая инструкция"},
        ),
        client.delete(f"/api/instructions/{second_instruction_id}"),
        client.put(
            f"/api/phases/{first_phase_id}/instructions/reorder",
            json={"instruction_ids": [second_instruction_id, first_instruction_id]},
        ),
    ]


@pytest.mark.parametrize(
    ("mode_kind", "expected_error"),
    [
        (
            "legacy",
            "Режим 'default' предназначен только для совместимости и доступен только для чтения",
        ),
        ("incomplete", "Режим 'draft' доступен только для чтения: серверная политика неполна"),
        (
            "inconsistent",
            "Режим 'broken' доступен только для чтения: серверная политика противоречива",
        ),
    ],
)
def test_read_only_mode_rejects_every_phase_and_instruction_mutation_without_db_change(
    client: TestClient,
    mode_kind: str,
    expected_error: str,
) -> None:
    workflow_id, default_mode = _create_workflow(client, f"Read only {mode_kind}")
    if mode_kind == "legacy":
        default_phase = client.get(
            f"/api/phases?workflow_id={workflow_id}&modeId={default_mode['id']}"
        ).json()["phases"][0]
        seeded = _seed_mode_content(
            workflow_id, default_mode["id"], existing_phase_id=default_phase["id"]
        )
    else:
        mode = _create_mode(
            client,
            workflow_id,
            key="draft" if mode_kind == "incomplete" else "broken",
            configured=mode_kind == "inconsistent",
        )
        if mode_kind == "inconsistent":
            uow = _app_state.get_db()
            try:
                uow.session.execute(text("PRAGMA ignore_check_constraints = ON"))
                uow.session.execute(
                    text(
                        "UPDATE workflow_modes SET tech_workspace_policy = 'forbidden' WHERE id = :id"
                    ),
                    {"id": mode["id"]},
                )
                uow.commit()
            finally:
                uow.close()
        seeded = _seed_mode_content(workflow_id, mode["id"])

    before = _snapshot(client, seeded)
    responses = _all_mutations(client, seeded)

    assert [response.status_code for response in responses] == [409] * 8
    assert [response.json()["error"] for response in responses] == [expected_error] * 8
    assert _snapshot(client, seeded) == before


def test_configured_mode_allows_every_phase_and_instruction_mutation_route(
    client: TestClient,
) -> None:
    workflow_id, _ = _create_workflow(client, "Configured mutations")
    mode = _create_mode(client, workflow_id, key="delivery", configured=True)

    first_phase = client.post(
        "/api/phases",
        json={
            "workflow_id": workflow_id,
            "mode_id": mode["id"],
            "phase_order": 1,
            "name": "Первая фаза",
        },
    )
    second_phase = client.post(
        "/api/phases",
        json={
            "workflow_id": workflow_id,
            "mode_id": mode["id"],
            "phase_order": 2,
            "name": "Вторая фаза",
        },
    )
    assert first_phase.status_code == second_phase.status_code == 200
    first_phase_id = first_phase.json()["phase_id"]
    second_phase_id = second_phase.json()["phase_id"]

    phase_update = client.put(
        f"/api/phases/{first_phase_id}", json={"name": "Первая фаза обновлена"}
    )
    phase_reorder = client.put(
        "/api/phases/order",
        json={
            "orders": [
                {"phase_id": second_phase_id, "phase_order": 1},
                {"phase_id": first_phase_id, "phase_order": 2},
            ]
        },
    )
    first_instruction = client.post(
        "/api/instructions",
        json={"phase_id": first_phase_id, "description": "Первая инструкция"},
    )
    second_instruction = client.post(
        "/api/instructions",
        json={"phase_id": first_phase_id, "description": "Вторая инструкция"},
    )
    assert first_instruction.status_code == second_instruction.status_code == 200
    first_instruction_id = first_instruction.json()["instruction"]["id"]
    second_instruction_id = second_instruction.json()["instruction"]["id"]
    instruction_update = client.put(
        f"/api/instructions/{first_instruction_id}",
        json={"description": "Первая инструкция обновлена"},
    )
    instruction_reorder = client.put(
        f"/api/phases/{first_phase_id}/instructions/reorder",
        json={"instruction_ids": [second_instruction_id, first_instruction_id]},
    )
    instruction_delete = client.delete(f"/api/instructions/{second_instruction_id}")
    phase_delete = client.delete(f"/api/phases/{second_phase_id}")

    assert [
        phase_update.status_code,
        phase_reorder.status_code,
        instruction_update.status_code,
        instruction_reorder.status_code,
        instruction_delete.status_code,
        phase_delete.status_code,
    ] == [200] * 6
