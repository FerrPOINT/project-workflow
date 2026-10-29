"""Profession-owned workflow collections through the public HTTP boundary."""
import json
import re

from fastapi.testclient import TestClient

from project_workflow.interfaces.ui import app
from tests._ui_source_helpers import page_source


def workflow_ids(html):
    data = json.loads(re.search(r"data-workflow-view-data>(.*?)</script>", html, re.S).group(1))
    return {item["id"] for item in data["workflows"]}


def test_profession_collection_excludes_neighbors_on_load_reload_and_save():
    with TestClient(app) as client:
        first = client.get("/api/namespaces").json()["namespaces"][0]["id"]
        second_response = client.post("/api/namespaces", json={
            "name": "A different profession", "cli_command": "workflow-neighbor",
        })
        assert second_response.status_code == 200, second_response.text
        second = second_response.json()["namespace_id"]
        first_starter = client.get(f"/api/workflows?namespace_id={first}").json()["workflows"][0]["id"]
        other = client.get(f"/api/workflows?namespace_id={second}").json()["workflows"][0]["id"]
        assert first_starter != other
        # Identical display names must not determine membership.
        for profession, neighbor in [(first, second), (second, first)]:
            created = client.post(f"/api/workflows?namespace_id={profession}", json={"name": "Дефолтный"})
            assert created.status_code == 200, created.text
            workflow = created.json()["workflow_id"]
            own = {item["id"] for item in client.get(f"/api/workflows?namespace_id={profession}").json()["workflows"]}
            assert len(own) == 2 and workflow in own
            rows = client.get(f"/api/workflows?namespace_id={profession}").json()["workflows"]
            assert all(row["namespace_count"] == 1 for row in rows)
            response = client.get(f"/workflows?namespace_id={profession}&workflow_id={workflow}")
            html = response.text
            assert workflow_ids(html) == own
            assert "namespace_id', String(professionId)" in page_source(client, response)
            assert 'id="newWorkflowButton"' in html
            saved = client.put(f"/api/workflows/{workflow}?namespace_id={profession}", json={"description": "Saved"})
            assert saved.status_code == 200
            reloaded = client.get(f"/workflows?namespace_id={profession}&workflow_id={workflow}")
            assert reloaded.status_code == 200
            assert workflow_ids(reloaded.text) == own
            denied = client.put(f"/api/workflows/{workflow}?namespace_id={neighbor}", json={"description": "Wrong"})
            assert denied.status_code == 409
            assert client.delete(f"/api/workflows/{workflow}?namespace_id={neighbor}").status_code == 409
            assert client.get(f"/phases?namespace_id={profession}&workflow_id={workflow}").status_code == 200
            phases = client.get(f"/api/phases?namespace_id={profession}&workflow_id={workflow}")
            assert phases.status_code == 200
            assert all(phase["workflow_id"] == workflow for phase in phases.json()["phases"])
            assert client.get(f"/api/phases?namespace_id={neighbor}&workflow_id={workflow}").status_code == 409
            stale = client.get(f"/workflows?namespace_id={neighbor}&workflow_id={workflow}")
            assert stale.history[0].status_code == 303
            assert workflow not in workflow_ids(stale.text)
        assert client.get("/api/workflows?namespace_id=999999").status_code == 404
        assert client.post("/api/workflows?namespace_id=999999", json={"name": "Invalid"}).status_code == 404


def test_profession_vocabulary_and_editor_has_no_workflow_selector():
    with TestClient(app) as client:
        for path in ["/", "/namespaces", "/namespaces/new", "/workflows", "/tasks", "/phases"]:
            response = client.get(path)
            assert response.status_code == 200, response.text
            assert "Профессии" in response.text
            assert "Неймспейс" not in response.text
        for path in ["/namespaces", "/namespaces/new"]:
            assert 'namespaceWorkflowId' not in client.get(path).text
