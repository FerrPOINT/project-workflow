"""Whole-app fragments reuse the canonical shell work area and owner permissions."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from project_workflow.interfaces.ui import app
from tests.test_workflow_incremental import editor_url

pytestmark = pytest.mark.ui
client = TestClient(app)


@pytest.mark.parametrize("path", ["/", "/namespaces", "/namespaces/new", "/workflows", "/tasks", "/settings"])
@pytest.mark.parametrize("admin", [False, True])
def test_work_area_uses_same_view_without_restarting_shell(monkeypatch, path, admin):
    from project_workflow.interfaces.ui.routes import pages
    monkeypatch.setattr(pages, "can_administer", lambda request: admin)
    full = client.get(path)
    fragment = client.get(path, headers={"X-Workflow-View": "page-v1"})
    assert full.status_code == fragment.status_code
    assert fragment.headers["X-Workflow-View"] == "page-v1"
    assert fragment.headers["Cache-Control"] == "private, no-store"
    assert "X-Workflow-View" in fragment.headers["Vary"]
    assert "<!DOCTYPE html>" not in fragment.text
    assert 'id="sidebar"' not in fragment.text
    assert "installServerProduct" not in fragment.text
    def main(body):
        value = re.search(r"<main .*?</main>", body, re.S).group()
        value = re.sub(r"<style data-workflow-page-style>.*?</style>", "", value, flags=re.S)
        return re.sub(r">\s+<", "><", value).strip()
    assert main(full.text) == main(fragment.text)
    meta = json.loads(re.search(r"data-workflow-page>(.*?)</script>", fragment.text, re.S).group(1))
    assert meta["schema_version"] == 1
    assert meta["can_administer"] is admin
    assert fragment.text.count("data-workflow-controller") == 1


def test_phase_and_instruction_views_use_work_area_protocol():
    full = client.get(editor_url())
    phase = re.search(r'href="(/phase/[^"#]+)"', full.text).group(1).replace("&amp;", "&")
    response = client.get(phase, headers={"X-Workflow-View": "page-v1"})
    assert response.status_code == 200
    assert response.headers["X-Workflow-View"] == "page-v1"
    assert "page.cleanup(()=>observer.disconnect())" in response.text
    assert "<!DOCTYPE html>" not in response.text


def test_library_is_exact_local_asset_and_unknown_assets_are_not_exposed():
    from hashlib import sha256
    response = client.get("/ui-assets/htmx-2.0.11.min.js")
    assert response.status_code == 200
    assert sha256(response.content).hexdigest() == "d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717"
    assert "immutable" in response.headers["Cache-Control"]
    assert client.get("/ui-assets/htmx.json").status_code == 404
    from project_workflow.interfaces.ui.sso import _PUBLIC_PATHS
    assert "/ui-assets/htmx-2.0.11.min.js" in _PUBLIC_PATHS
    assert "/api/workflows" not in _PUBLIC_PATHS
