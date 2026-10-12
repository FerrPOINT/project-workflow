"""Public UI navigation regression tests for the compatible pdlc1 patch."""
import hashlib
import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path

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
