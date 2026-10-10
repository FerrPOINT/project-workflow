"""Explicit catalog navigation must take precedence over a remembered UI selection."""

import pytest
from fastapi.testclient import TestClient

from project_workflow.interfaces.ui.app import create_app

pytestmark = pytest.mark.ui


@pytest.mark.parametrize("assigned", [False, True])
@pytest.mark.parametrize("page", ["phases", "phase", "instructions"])
def test_catalog_navigation_ignores_another_namespace_cookie(monkeypatch, assigned, page):
    monkeypatch.setattr("project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True)
    with TestClient(create_app()) as client:
        selected = client.get("/api/namespaces").json()["namespaces"][0]
        created = client.post("/api/workflows", json={"name": "Independent catalog"})
        assert created.status_code == 200, created.text
        workflow_id = created.json()["workflow_id"]
        if assigned:
            linked = client.post("/api/namespaces", json={
                "name": "Another namespace", "workflow_id": workflow_id, "cli_command": "workflow-other",
            })
            assert linked.status_code == 200, linked.text
        phase_id = client.get(f"/api/phases?workflow_id={workflow_id}").json()["phases"][0]["id"]
        path = {
            "phases": f"/phases?workflow_id={workflow_id}",
            "phase": f"/phase/{phase_id}",
            "instructions": f"/instructions?phase_id={phase_id}",
        }[page]
        client.cookies.set("workflow_namespace_id", str(selected["id"]), domain="testserver.local")
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert f'namespace_id={selected["id"]}' not in response.text
        assert response.text.count('value="" disabled selected>Каталог воркфлоу</option>') == 2
        assert client.cookies.get("workflow_namespace_id") == str(selected["id"])

        scoped = client.get(path + ("&" if "?" in path else "?") + f'namespace_id={selected["id"]}')
        assert scoped.status_code == 404, scoped.text
        owner_path = f'/phases?namespace_id={selected["id"]}&workflow_id={selected["workflow_id"]}'
        assert client.get(owner_path).status_code == 200
