"""Preserve accepted sidebar behavior with profession-owned workflow collections."""
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from project_workflow.interfaces.ui import _app_state, app


@pytest.fixture
def client():
    with TestClient(app) as browser_client:
        yield browser_client


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


def test_sidebar_keeps_cli_and_has_no_removed_registry(client):
    response = client.get("/settings")
    sidebar = response.text.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0]
    links = Links()
    links.feed(sidebar)
    assert not any(link.get("href") in {"/phases", "/agents"} for link in links.links)
    assert any(link.get("aria-label") == "Процессы" for link in links.links)
    assert any(link.get("aria-label") == "Выполнения задач" for link in links.links)
    assert any(link.get("href") == "/settings" for link in links.links)
    assert "Сервис работает" not in sidebar


def test_unified_phases_target_nonstarter_workflow_in_same_profession(client):
    profession = client.get("/api/namespaces").json()["namespaces"][0]
    created = client.post(f'/api/workflows?namespace_id={profession["id"]}', json={"name":"Extra process"})
    assert created.status_code == 200
    workflow_id = created.json()["workflow_id"]
    response = client.get(f'/workflows?namespace_id={profession["id"]}&workflow_id={workflow_id}')
    assert response.status_code == 200
    links = Links()
    links.feed(response.text)
    phases = client.get(f'/api/phases?namespace_id={profession["id"]}&workflow_id={workflow_id}').json()
    phase_links = [link for link in links.links if link.get("href", "").startswith("/phase/")]
    assert {int(link["href"].split("/phase/", 1)[1].split("?", 1)[0]) for link in phase_links} == {
        phase["id"] for phase in phases["phases"]
    }
    assert all(f'profession_id={profession["id"]}' in link["href"] for link in phase_links)
    assert 'id="workflowForm"' in response.text
    assert f'id="phasesTimeline" data-workflow-id="{workflow_id}"' in response.text


@pytest.mark.parametrize("scope", ["all", "selected"])
def test_phase_modes_and_sidebar_preserve_explicit_all_scope(client, scope):
    profession = client.get("/api/namespaces").json()["namespaces"][0]
    with _app_state.get_db() as uow:
        uow.workflows.create_mode({
            "workflow_id": profession["workflow_id"], "key": "follow-up",
            "name": "Follow-up", "mode_order": 2,
        })
        uow.commit()
    response = client.get(f'/phases?namespace_id={profession["id"]}&project_scope={scope}')
    assert response.status_code == 200
    links = Links()
    links.feed(response.text)
    modes = [link for link in links.links if "data-mode-id" in link]
    assert modes
    assert all(link["href"].startswith("/workflows?") for link in modes)
    assert all(("project_scope=all" in link["href"]) == (scope == "all") for link in modes)
    sidebar = Links()
    sidebar.feed(response.text.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0])
    assert all(("project_scope=all" in link.get("href", "")) == (scope == "all")
               for link in sidebar.links)


@pytest.mark.parametrize("path", ["/", "/namespaces", "/workflows", "/tasks", "/settings"])
def test_platform_namespace_is_not_interpreted_as_a_profession(client, path):
    response = client.get(path, params={
        "registry_instance_id": "11111111-1111-4111-8111-111111111111",
        "namespace_id": "22222222-2222-4222-8222-222222222222",
        "project_scope": "all",
    })
    assert response.status_code == 200
    assert "Некорректный namespace_id" not in response.text


@pytest.mark.parametrize("query", ["profession_id", "namespace_id"])
def test_profession_selection_accepts_canonical_and_legacy_links(client, query):
    profession = client.get("/api/namespaces").json()["namespaces"][0]
    response = client.get("/workflows", params={query: profession["id"]})
    assert response.status_code == 200
    links = Links()
    links.feed(response.text)
    phases = [link for link in links.links if link.get("href", "").startswith("/phase/")]
    assert phases
    assert all(f'profession_id={profession["id"]}' in link["href"] for link in phases)


@pytest.mark.parametrize("query", ["profession_id=invalid", "profession_id=1&profession_id=2"])
def test_invalid_profession_selection_does_not_choose_another_profession(client, query):
    response = client.get("/workflows?" + query)
    assert response.status_code == 422
