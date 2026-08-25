"""Regression coverage for invariants introduced with the clean baseline."""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from project_workflow.domain.exceptions import ConflictError
from project_workflow.interfaces.ui import app
from project_workflow.interfaces.ui.state import _app_state

pytestmark = [pytest.mark.ui]

client = TestClient(app)
_counter = itertools.count()


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def _workflow_with_phases(count: int = 2) -> tuple[int, list[dict]]:
    workflow = _app_state.workflow_service().create_workflow(
        {"name": _unique("workflow"), "_skip_default_phase": True}
    )
    phases = [
        _app_state.phase_service().create_phase(
            {
                "workflow_id": workflow["id"],
                "code": _unique(f"phase-{order}"),
                "name": f"Phase {order}",
                "phase_order": order,
            }
        )
        for order in range(1, count + 1)
    ]
    return workflow["id"], phases


def test_batch_reorder_is_complete_single_workflow_and_atomic():
    workflow_id, phases = _workflow_with_phases(3)
    _, foreign = _workflow_with_phases(1)
    service = _app_state.phase_service()
    original = [(phase["id"], phase["phase_order"]) for phase in service.list_phases(workflow_id)]

    invalid_batches = [
        [
            {"phase_id": phases[0]["id"], "phase_order": 1},
            {"phase_id": phases[1]["id"], "phase_order": 2},
        ],
        [
            {"phase_id": phases[0]["id"], "phase_order": 1},
            {"phase_id": phases[0]["id"], "phase_order": 2},
            {"phase_id": phases[2]["id"], "phase_order": 3},
        ],
        [
            {"phase_id": phases[0]["id"], "phase_order": 1},
            {"phase_id": phases[1]["id"], "phase_order": 3},
            {"phase_id": phases[2]["id"], "phase_order": 4},
        ],
        [
            {"phase_id": phases[0]["id"], "phase_order": 1},
            {"phase_id": phases[1]["id"], "phase_order": 2},
            {"phase_id": foreign[0]["id"], "phase_order": 3},
        ],
    ]
    for orders in invalid_batches:
        response = client.put("/api/phases/order", json={"orders": orders})
        assert response.status_code == 409
        assert [(phase["id"], phase["phase_order"]) for phase in service.list_phases(workflow_id)] == original

    valid = [
        {"phase_id": phase["id"], "phase_order": order}
        for order, phase in enumerate(reversed(phases), start=1)
    ]
    response = client.put("/api/phases/order", json={"orders": valid})
    assert response.status_code == 200
    assert [phase["id"] for phase in service.list_phases(workflow_id)] == [
        phase["id"] for phase in reversed(phases)
    ]


@pytest.mark.parametrize(
    ("extra", "status"),
    [
        ({"code": "duplicate"}, 409),
        ({"agent_id": 999999}, 404),
        ({"parallel_with": "missing"}, 409),
        ({"rollback_target": "missing"}, 409),
    ],
)
def test_phase_create_validates_references_before_shifting_order(extra, status):
    workflow_id, phases = _workflow_with_phases(2)
    service = _app_state.phase_service()
    if extra.get("code") == "duplicate":
        extra = {"code": phases[0]["code"]}
    original = [(phase["id"], phase["phase_order"]) for phase in service.list_phases(workflow_id)]

    response = client.post(
        "/api/phases",
        json={
            "workflow_id": workflow_id,
            "name": "Rejected",
            "phase_order": 1,
            **extra,
        },
    )

    assert response.status_code == status
    assert [(phase["id"], phase["phase_order"]) for phase in service.list_phases(workflow_id)] == original


def test_phase_delete_rejects_links_current_tasks_and_history():
    workflow_id, phases = _workflow_with_phases(3)
    first, second, third = phases
    service = _app_state.phase_service()

    service.update_phase(first["id"], {"execution_type": "parallel"})
    service.update_phase(
        second["id"],
        {"execution_type": "parallel", "parallel_with": first["code"]},
    )
    assert client.delete(f"/api/phases/{first['id']}").status_code == 409
    service.update_phase(second["id"], {"parallel_with": None})

    prefix = _unique("DEL").upper()
    project = _app_state.project_service().create_project(
        {
            "workflow_id": workflow_id,
            "code": _unique("project-delete"),
            "name": "Delete guards",
            "key_prefixes": [prefix],
        }
    )
    task = _app_state.task_service().create_task(
        {
            "project_id": project["id"],
            "task_key": f"{prefix}-1",
            "current_phase": first["code"],
        }
    )
    assert client.delete(f"/api/phases/{first['id']}").status_code == 409

    uow = _app_state.get_db()
    uow.tasks.update(task["id"], {"current_phase": third["code"]})
    uow.tasks.add_history(task["id"], first["id"], "done")
    uow.commit()
    assert client.delete(f"/api/phases/{first['id']}").status_code == 409


def test_project_description_workflow_and_prefix_guards():
    workflow_id, phases = _workflow_with_phases(1)
    other_workflow_id, _ = _workflow_with_phases(1)
    prefix = f"PRJ{next(_counter)}"
    response = client.post(
        "/api/projects",
        json={
            "workflow_id": workflow_id,
            "code": _unique("project"),
            "name": "Project",
            "description": "Persist me",
            "key_prefixes": [prefix],
        },
    )
    assert response.status_code == 200
    project = response.json()["project"]
    assert project["description"] == "Persist me"

    task = _app_state.task_service().create_task(
        {
            "project_id": project["id"],
            "task_key": f"{prefix}-42",
            "current_phase": phases[0]["code"],
        }
    )
    assert task["task_key"] == f"{prefix}-42"

    workflow_change = client.put(
        f"/api/projects/{project['id']}", json={"workflow_id": other_workflow_id}
    )
    assert workflow_change.status_code == 409
    prefix_change = client.put(
        f"/api/projects/{project['id']}", json={"key_prefixes": [f"NEW{next(_counter)}"]}
    )
    assert prefix_change.status_code == 409
    unchanged = _app_state.project_service().get_project(project["id"])
    assert unchanged["workflow_id"] == workflow_id
    assert unchanged["key_prefixes"] == [prefix]


def test_project_explicit_null_non_nullable_fields_are_rejected():
    create = client.post(
        "/api/projects",
        json={"code": _unique("null-project"), "key_prefixes": [f"NULL{next(_counter)}"], "workflow_id": None},
    )
    assert create.status_code == 422
    create_description = client.post(
        "/api/projects",
        json={
            "code": _unique("null-description-project"),
            "key_prefixes": [f"NULL{next(_counter)}"],
            "description": None,
        },
    )
    assert create_description.status_code == 422

    workflow_id, _ = _workflow_with_phases(1)
    prefix = f"KEEP{next(_counter)}"
    project = _app_state.project_service().create_project(
        {
            "workflow_id": workflow_id,
            "code": _unique("keep-project"),
            "name": "Keep workflow",
            "key_prefixes": [prefix],
        }
    )
    update = client.put(f"/api/projects/{project['id']}", json={"workflow_id": None})
    assert update.status_code == 422
    update_description = client.put(f"/api/projects/{project['id']}", json={"description": None})
    assert update_description.status_code == 422
    assert _app_state.project_service().get_project(project["id"])["workflow_id"] == workflow_id


def test_task_filter_returns_nonempty_workflow_specific_dto():
    first_workflow, first_phases = _workflow_with_phases(1)
    second_workflow, second_phases = _workflow_with_phases(1)
    expected: dict[int, str] = {}
    for workflow_id, phases in (
        (first_workflow, first_phases),
        (second_workflow, second_phases),
    ):
        prefix = _unique("FILTER").upper()
        project = _app_state.project_service().create_project(
            {
                "workflow_id": workflow_id,
                "code": _unique("filter-project"),
                "name": "Filter project",
                "key_prefixes": [prefix],
            }
        )
        task_key = f"{prefix}-1"
        _app_state.task_service().create_task(
            {
                "project_id": project["id"],
                "task_key": task_key,
                "current_phase": phases[0]["code"],
            }
        )
        expected[workflow_id] = task_key

    for workflow_id, task_key in expected.items():
        tasks = client.get(f"/api/tasks?workflow_id={workflow_id}").json()["tasks"]
        assert [task["task_key"] for task in tasks] == [task_key]
        assert tasks[0]["workflow_id"] == workflow_id


def test_explicit_project_task_validates_prefix_and_scoped_phase_before_write():
    workflow_id, _ = _workflow_with_phases(1)
    prefix = _unique("STRICT").upper()
    project = _app_state.project_service().create_project(
        {
            "workflow_id": workflow_id,
            "code": _unique("strict-project"),
            "name": "Strict project",
            "key_prefixes": [prefix],
        }
    )
    service = _app_state.task_service()
    with pytest.raises(ConflictError, match="не соответствует"):
        service.create_task({"project_id": project["id"], "task_key": "WRONG-1"})
    with pytest.raises(ValueError, match="не найдена в воркфлоу"):
        service.create_task(
            {
                "project_id": project["id"],
                "task_key": f"{prefix}-1",
                "current_phase": "missing",
            }
        )
    assert not any(task["task_key"] in {"WRONG-1", f"{prefix}-1"} for task in service.list_tasks())


def test_nullable_phase_fields_distinguish_omitted_from_explicit_null():
    workflow_id, phases = _workflow_with_phases(2)
    first, second = phases
    agent = _app_state.agent_service().create_agent({"name": _unique("agent")})
    service = _app_state.phase_service()
    service.update_phase(first["id"], {"execution_type": "parallel"})
    service.update_phase(
        second["id"],
        {
            "description": "Present",
            "execution_type": "parallel",
            "parallel_with": first["code"],
            "rollback_target": first["code"],
            "next_recommendation": "Next",
            "agent_id": agent["id"],
        },
    )

    response = client.put(
        f"/api/phases/{second['id']}",
        json={
            "description": None,
            "parallel_with": None,
            "rollback_target": None,
            "next_recommendation": None,
            "agent_id": None,
        },
    )
    assert response.status_code == 200
    updated = service.get_phase(second["id"])
    assert updated["description"] is None
    assert updated["parallel_with"] is None
    assert updated["rollback_target"] is None
    assert updated["next_recommendation"] is None
    assert updated["agent_id"] is None

    with pytest.raises(ConflictError):
        service.update_phase(first["id"], {"parallel_with": "missing"})
    assert service.get_phase(first["id"])["parallel_with"] is None


def test_projects_page_exposes_description_editor():
    response = client.get("/projects")
    assert response.status_code == 200
    assert 'id="projectDescription"' in response.text
    assert "description: document.getElementById('projectDescription').value.trim()" in response.text


def test_phase_detail_exposes_explicit_parallel_partner_editor():
    phase = next(
        phase for phase in _app_state.phase_service().list_phases() if phase["code"] == "7.PLAN_GATE"
    )
    response = client.get(f"/phase/{phase['id']}")
    assert response.status_code == 200
    assert 'id="parallelPartnerSelect"' in response.text
    assert "— изолированная фаза —" in response.text
    assert 'value="6.TEST_PLAN"' in response.text
    assert 'value="10.REVIEW"' not in response.text
    assert "partnerSelect.value = '';" in response.text


@pytest.mark.parametrize("raw_skills", ["{broken", ""])
def test_corrupted_persisted_instruction_skills_fail_loudly(raw_skills):
    _, phases = _workflow_with_phases(1)
    instruction = _app_state.instruction_service().create_instruction(
        phases[0]["id"],
        {"description": "Corrupt me", "skills": ["testing"]},
    )
    uow = _app_state.get_db()
    uow.session.execute(
        text("UPDATE instructions SET skills = :skills WHERE id = :id"),
        {"id": instruction["id"], "skills": raw_skills},
    )
    uow.commit()

    with pytest.raises(ValueError, match="некорректный JSON"):
        _app_state.instruction_service().get_instruction(instruction["id"])
