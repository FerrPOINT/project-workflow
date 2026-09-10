from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests._db_helpers import phase_by_code, prepare_sqlite_uow
from tests._phase_helpers import create_empty_workflow

pytestmark = [pytest.mark.ui]


@pytest.fixture
def restricted_ui(monkeypatch):
    db_url = config.get_settings().DATABASE_URL
    monkeypatch.setenv("UI_VISIBLE_NAMESPACE_CODES", "target")
    config.get_settings.cache_clear()

    with SAUnitOfWork(db_url) as uow:
        prepare_sqlite_uow(uow)
        legacy_workflow = uow.workflows.get_default()
        legacy_namespace = uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE)
        legacy_phase = phase_by_code(uow, "1.INTAKE", legacy_workflow.id)
        assert legacy_workflow and legacy_workflow.id
        assert legacy_namespace and legacy_namespace.id
        assert legacy_phase and legacy_phase.id

        legacy_agent_id = uow.agents.create(
            {"name": "Legacy agent", "hermes_profile": "legacy-agent"}
        )
        uow.phases.update(legacy_phase.id, {"agent_id": legacy_agent_id})
        legacy_instruction = uow.phase_instructions.list(legacy_phase.id)[0]
        assert legacy_instruction["id"] is not None
        legacy_task_id = uow.tasks.create(
            {
                "project_id": legacy_namespace.id,
                "workflow_id": legacy_workflow.id,
                "task_key": "RUN-1",
                "title": "Legacy task",
                "current_phase_id": legacy_phase.id,
            }
        )

        target_workflow = create_empty_workflow(uow, "Target workflow")
        target_agent_id = uow.agents.create(
            {"name": "Target agent", "hermes_profile": "target-agent"}
        )
        target_phase_id = uow.phases.create(
            {
                "workflow_id": target_workflow["id"],
                "code": "TARGET",
                "name": "Target phase",
                "phase_order": 1,
                "agent_id": target_agent_id,
                "execution_type": "sync",
            }
        )
        target_namespace_id = uow.projects.create(
            {
                "workflow_id": target_workflow["id"],
                "code": "TARGET",
                "name": "Target namespace",
                "cli_command": "workflow-target",
                "key_prefixes": ["TGT"],
            }
        )
        target_task_id = uow.tasks.create(
            {
                "project_id": target_namespace_id,
                "workflow_id": target_workflow["id"],
                "task_key": "TGT-1",
                "title": "Target task",
                "current_phase_id": target_phase_id,
            }
        )
        uow.commit()

    ids = {
        "legacy_workflow": legacy_workflow.id,
        "legacy_namespace": legacy_namespace.id,
        "legacy_phase": legacy_phase.id,
        "legacy_agent": legacy_agent_id,
        "legacy_instruction": legacy_instruction["id"],
        "legacy_task": legacy_task_id,
        "target_workflow": target_workflow["id"],
        "target_namespace": target_namespace_id,
        "target_phase": target_phase_id,
        "target_agent": target_agent_id,
        "target_task": target_task_id,
    }
    with TestClient(create_app()) as client:
        yield client, ids, db_url
    config.get_settings.cache_clear()


def test_restricted_ui_lists_only_the_allowlisted_namespace_graph(restricted_ui):
    client, ids, _db_url = restricted_ui

    namespaces = client.get("/api/namespaces").json()["namespaces"]
    workflows = client.get("/api/workflows").json()["workflows"]
    agents = client.get("/api/agents").json()["agents"]
    tasks = client.get("/api/tasks").json()["tasks"]

    assert [item["id"] for item in namespaces] == [ids["target_namespace"]]
    assert [item["id"] for item in workflows] == [ids["target_workflow"]]
    assert [item["id"] for item in agents] == [ids["target_agent"]]
    assert [item["id"] for item in tasks] == [ids["target_task"]]


def test_hidden_namespace_graph_is_not_accessible_by_direct_ui_or_api_urls(restricted_ui):
    client, ids, _db_url = restricted_ui

    assert client.get(f"/api/namespaces/{ids['legacy_namespace']}").status_code == 404
    assert client.get(f"/api/phases?workflow_id={ids['legacy_workflow']}").status_code == 404
    assert client.get(f"/api/phases/{ids['legacy_phase']}").status_code == 404
    assert client.get(f"/phase/{ids['legacy_phase']}").status_code == 404
    assert (
        client.get(
            "/task/RUN-1", params={"namespace_id": ids["legacy_namespace"]}
        ).status_code
        == 404
    )


def test_hidden_namespace_cannot_create_or_advance_a_task(restricted_ui):
    client, ids, db_url = restricted_ui

    response = client.post(
        "/api/tasks/step",
        json={"namespace_id": ids["legacy_namespace"], "task": "RUN-NEW"},
    )

    assert response.status_code == 404
    with SAUnitOfWork(db_url) as uow:
        assert uow.tasks.get_by_key("RUN-NEW", project_id=ids["legacy_namespace"]) is None


def test_allowlisted_namespace_can_read_current_task_step(restricted_ui):
    client, ids, _db_url = restricted_ui

    response = client.post(
        "/api/tasks/step",
        json={"namespace_id": ids["target_namespace"], "task": "TGT-1"},
    )

    assert response.status_code == 200
    assert response.json()["result"]["task_key"] == "TGT-1"


def test_hidden_runtime_wrapper_is_read_only_when_allowlist_is_enabled(
    restricted_ui, monkeypatch
):
    _client, ids, db_url = restricted_ui
    token = "x" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"run": token})
    )
    config.get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/runtime/step",
            headers={"Authorization": f"Bearer {token}"},
            json={"task": "RUN-NEW"},
        )

    assert response.status_code == 404
    with SAUnitOfWork(db_url) as uow:
        assert uow.tasks.get_by_key("RUN-NEW", project_id=ids["legacy_namespace"]) is None


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("put", "namespace", {"name": "mutated"}),
        ("delete", "namespace", None),
        ("put", "workflow", {"name": "mutated"}),
        ("delete", "workflow", None),
        ("put", "phase", {"name": "mutated"}),
        ("delete", "phase", None),
        ("put", "agent", {"name": "mutated"}),
        ("delete", "agent", None),
    ],
)
def test_hidden_catalog_entities_are_read_only(restricted_ui, method, path, payload):
    client, ids, _db_url = restricted_ui
    entity_id = ids[f"legacy_{path}"]
    response = client.request(
        method.upper(), f"/api/{path}s/{entity_id}", json=payload
    )

    assert response.status_code == 403


def test_hidden_phase_instructions_are_not_accessible(restricted_ui):
    client, ids, _db_url = restricted_ui

    assert (
        client.get(
            f"/api/phases/{ids['legacy_phase']}/instructions"
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/instructions",
            json={
                "phase_id": ids["legacy_phase"],
                "description": "must stay hidden",
            },
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/instructions/{ids['legacy_instruction']}",
            json={"description": "mutated"},
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/instructions/{ids['legacy_instruction']}"
        ).status_code
        == 403
    )


def test_visible_catalog_cannot_attach_hidden_graph_entities(restricted_ui):
    client, ids, _db_url = restricted_ui

    namespace = client.post(
        "/api/namespaces",
        json={
            "name": "Hidden workflow alias",
            "workflow_id": ids["legacy_workflow"],
            "cli_command": "workflow-hidden-alias",
            "key_prefixes": ["HID"],
        },
    )
    phase = client.post(
        "/api/phases",
        json={
            "workflow_id": ids["target_workflow"],
            "phase_order": 2,
            "name": "Hidden agent phase",
            "agent_id": ids["legacy_agent"],
        },
    )

    assert namespace.status_code == 403
    assert phase.status_code == 403


def test_restricted_ui_blocks_new_top_level_catalog_entries(restricted_ui):
    client, _ids, _db_url = restricted_ui

    assert client.post("/api/workflows", json={"name": "Junk"}).status_code == 403
    assert client.post("/api/agents", json={"name": "Junk"}).status_code == 403
    assert client.get("/namespace/new").status_code == 404

    namespace_html = client.get("/namespace").text
    workflow_html = client.get("/workflows").text
    agents_html = client.get("/agents").text
    assert 'id="newProjectButton"' not in namespace_html
    assert 'id="newWorkflowButton"' not in workflow_html
    assert "Добавить агента" not in agents_html
    assert 'href="/namespace/new' not in namespace_html


def test_allowlisted_catalog_is_also_immutable(restricted_ui):
    client, ids, _db_url = restricted_ui

    responses = [
        client.put(
            f"/api/namespaces/{ids['target_namespace']}",
            json={"name": "mutated"},
        ),
        client.put(
            f"/api/workflows/{ids['target_workflow']}",
            json={"name": "mutated"},
        ),
        client.put(
            f"/api/phases/{ids['target_phase']}",
            json={"name": "mutated"},
        ),
        client.put(
            f"/api/agents/{ids['target_agent']}",
            json={"name": "mutated"},
        ),
        client.post(
            "/api/instructions",
            json={
                "phase_id": ids["target_phase"],
                "description": "mutated",
            },
        ),
    ]

    assert [response.status_code for response in responses] == [403] * len(responses)
