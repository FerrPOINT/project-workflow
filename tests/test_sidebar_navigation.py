"""Public UI navigation regression tests for the compatible pdlc1 patch."""
import hashlib
import json
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from project_workflow.interfaces.ui import app


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


def test_sidebar_removes_global_phases_and_preserves_cli():
    response = TestClient(app).get("/settings")
    assert response.status_code == 200
    sidebar = response.text.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0]
    links = Links()
    links.feed(sidebar)
    assert not any(link.get("href") == "/phases" for link in links.links)
    assert any(link.get("href") == "/settings" and link.get("aria-label") == "Команды CLI" for link in links.links)
    assert "Сервис работает" not in sidebar
    assert "Служебное" in sidebar


def test_process_phase_link_uses_selected_workflow():
    client = TestClient(app)
    response = client.get("/api/workflows")
    assert response.status_code == 200
    workflows = response.json()["workflows"]
    workflow = workflows[0]
    response = client.get(f"/workflows?workflow_id={workflow['id']}")
    links = Links()
    links.feed(response.text)
    phase_links = [link for link in links.links if "data-workflow-phases" in link]
    assert phase_links
    assert all(f"workflow_id={workflow['id']}" in link.get("href", "") for link in phase_links)


def test_cli_template_is_identical_to_the_installed_baseline():
    template = Path(__file__).resolve().parents[1] / "project_workflow/interfaces/ui/templates/settings.html"
    # The accepted scope explicitly freezes this page independently of sidebar edits.
    expected = "8e744b40c6241855c3e505d366fa4a6437838a7bb5c60e31ce663bc1e7e17865"
    content = template.read_text(encoding="utf-8").encode()
    assert hashlib.sha256(content).hexdigest() == expected


def test_switching_process_drops_foreign_namespace_and_mode():
    template = Path(__file__).resolve().parents[1] / "project_workflow/interfaces/ui/templates/workflows.html"
    source = template.read_text(encoding="utf-8")
    selection = source[source.index("function workflowSelectionUrl("):source.index("function syncWorkflowUrl(")]
    phases = source[source.index("function phaseUrlForWorkflow("):source.index("function currentWorkflowPayload(")]
    script = "\n".join([
        "const initialWorkflowId=7, workflowNamespaceId=4, namespaceWorkflowId=7;",
        "const window={location:{origin:'http://workflow.test',href:'http://workflow.test/workflows?namespace_id=4&mode_id=11&project_scope=all'}};",
        selection, phases,
        "const same=phaseUrlForWorkflow(7);",
        "window.location.href='http://workflow.test'+workflowSelectionUrl(8);",
        "console.log(JSON.stringify({same,switched:phaseUrlForWorkflow(8),selection:window.location.href}));",
    ])
    result = subprocess.run(["node", "-"], input=script, text=True, capture_output=True, check=True, timeout=10)
    links = json.loads(result.stdout)
    assert links["same"] == "/phases?workflow_id=7&namespace_id=4&mode_id=11&project_scope=all"
    assert links["switched"] == "/phases?workflow_id=8&project_scope=all"
    assert links["selection"] == "http://workflow.test/workflows?project_scope=all&workflow_id=8"


def rendered_navigation(html, request_url, extra_links=()):
    """Run the served document-load module over its public anchor attributes."""
    links = Links()
    links.feed(html)
    anchors = links.links + list(extra_links)
    module = re.search(r"<script data-project-navigation-context>(.*?)</script>", html, re.S)
    assert module is not None
    harness = "\n".join([
        "const window={location:new URL(" + json.dumps(request_url) + ")};",
        "const anchors=" + json.dumps(anchors) + ";",
        "const elements=anchors.map(attrs=>({href:attrs.href,",
        "hasAttribute:key=>Object.hasOwn(attrs,key),",
        "classList:{contains:name=>(attrs.class||'').split(/\\s+/).includes(name)}}));",
        "const document={querySelectorAll:()=>elements,addEventListener:(event,callback)=>{",
        "if(event!=='DOMContentLoaded')throw new Error('Unexpected lifecycle');callback();}};",
        module.group(1),
        "console.log(JSON.stringify(elements.map((el,index)=>({...anchors[index],href:el.href}))));",
    ])
    result = subprocess.run(["node", "-"], input=harness, text=True, capture_output=True,
                            check=True, timeout=10)
    return anchors, json.loads(result.stdout)


def test_navigation_scope_covers_sidebar_modes_and_frozen_cli_route():
    client = TestClient(app)
    workflow = client.get("/api/workflows").json()["workflows"][0]
    path = f"/phases?workflow_id={workflow['id']}&project_scope=all"
    response = client.get(path)
    assert response.status_code == 200
    extras = [{"href": "https://git.example.test/repo"},
              {"href": "/download?file=owned", "download": ""},
              {"href": "http://["}]
    original, navigated = rendered_navigation(response.text, "http://testserver" + path, extras)
    sidebar = {link.get("aria-label"): link for link in navigated if link.get("aria-label")}
    for label, pathname in [("Процессы", "/workflows"), ("Выполнения задач", "/tasks"),
                            ("Неймспейсы", "/namespaces"), ("Команды CLI", "/settings")]:
        url = urlsplit(sidebar[label]["href"])
        assert url.path == pathname
        assert parse_qs(url.query)["project_scope"] == ["all"]
    modes = [link for link in navigated if "data-mode-id" in link]
    assert modes
    for link in modes:
        params = parse_qs(urlsplit(link["href"]).query)
        assert params["workflow_id"] == [str(workflow["id"])]
        assert params["mode_id"] == [link["data-mode-id"]]
        assert params["project_scope"] == ["all"]
    assert navigated[-3:] == original[-3:]


@pytest.mark.parametrize("search", ["", "?project_scope=all&project_scope=one"])
def test_navigation_does_not_invent_scope_for_legacy_or_ambiguous_urls(search):
    response = TestClient(app).get("/workflows" + search)
    assert response.status_code == 200
    original, navigated = rendered_navigation(response.text, "http://testserver/workflows" + search)
    assert navigated == original


def test_phase_return_link_keeps_workflow_and_selected_mode():
    client = TestClient(app)
    workflow = client.get("/api/workflows").json()["workflows"][0]
    response = client.get(f"/phases?workflow_id={workflow['id']}")
    links = Links()
    links.feed(response.text)
    mode = next(link for link in links.links if "data-mode-id" in link)
    mode_id = mode["data-mode-id"]
    response = client.get(f"/phases?workflow_id={workflow['id']}&mode_id={mode_id}")
    assert response.status_code == 200
    links = Links()
    links.feed(response.text)
    editor = next(link for link in links.links if "phases-header-action" in link.get("class", ""))
    params = parse_qs(urlsplit(editor["href"]).query)
    assert params["workflow_id"] == [str(workflow["id"])]
    assert params["mode_id"] == [mode_id]


def test_namespace_switch_resets_the_dependent_workflow_and_mode():
    response = TestClient(app).get("/workflows?project_scope=all")
    start = response.text.index("function switchNamespace(")
    end = response.text.index("function pluralizeRu(", start)
    script = "\n".join([
        "const document={cookie:''};",
        "const window={location:{href:'http://workflow.test/phases?namespace_id=4&workflow_id=7&mode_id=11&project_scope=all'}};",
        response.text[start:end],
        "switchNamespace('6');console.log(JSON.stringify(window.location.href));",
    ])
    result = subprocess.run(["node", "-"], input=script, text=True, capture_output=True,
                            check=True, timeout=10)
    params = parse_qs(urlsplit(json.loads(result.stdout)).query)
    assert params == {"namespace_id": ["6"], "project_scope": ["all"]}
