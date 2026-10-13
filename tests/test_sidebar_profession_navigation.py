"""Preserve accepted sidebar behavior with profession-owned workflow collections."""
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from project_workflow.interfaces.ui import app


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


def test_phases_link_targets_nonstarter_workflow_in_same_profession(client):
    profession = client.get("/api/namespaces").json()["namespaces"][0]
    created = client.post(f'/api/workflows?namespace_id={profession["id"]}', json={"name":"Extra process"})
    assert created.status_code == 200
    workflow_id = created.json()["workflow_id"]
    response = client.get(f'/workflows?namespace_id={profession["id"]}&workflow_id={workflow_id}')
    assert response.status_code == 200
    links = Links()
    links.feed(response.text)
    phase_links = [link for link in links.links if "data-workflow-phases" in link]
    assert len(phase_links) == 2
    assert all(f'workflow_id={workflow_id}' in link["href"] and
               f'namespace_id={profession["id"]}' in link["href"] for link in phase_links)


@pytest.mark.parametrize("scope", ["all", "selected"])
def test_phase_modes_and_sidebar_preserve_explicit_all_scope(client, scope):
    profession = client.get("/api/namespaces").json()["namespaces"][0]
    response = client.get(f'/phases?namespace_id={profession["id"]}&project_scope={scope}')
    assert response.status_code == 200
    links = Links()
    links.feed(response.text)
    modes = [link for link in links.links if link.get("href", "").startswith("/phases?")]
    assert modes
    assert all(("project_scope=all" in link["href"]) == (scope == "all") for link in modes)
    sidebar = Links()
    sidebar.feed(response.text.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0])
    assert all(("project_scope=all" in link.get("href", "")) == (scope == "all")
               for link in sidebar.links)
