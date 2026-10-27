"""The incremental editor uses the same scoped owner view as a full page."""

import pytest
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.interfaces.ui import _app_state, app
from tests.test_ui_shell_template import Elements
from tests.test_workflow_mode_tabs_ui import _developer_catalog

pytestmark = pytest.mark.ui
client = TestClient(app)


def editor_url(mode="initial"):
    catalog = _developer_catalog()
    with _app_state.get_db() as uow:
        profession = uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE)
        uow.workflows.assign_profession(catalog["workflow_id"], profession.id)
        uow.commit()
        profession_id = profession.id
    return (f"/workflows?profession_id={profession_id}&workflow_id={catalog['workflow_id']}"
            f"&mode_id={catalog[mode + '_mode_id']}&project_scope=all")


@pytest.mark.parametrize("mode", ["initial", "rework"])
@pytest.mark.parametrize("admin", [False, True])
def test_fragment_reuses_scoped_rendering_and_permissions(monkeypatch, mode, admin):
    from project_workflow.interfaces.ui.routes import pages
    monkeypatch.setattr(pages, "can_administer", lambda request: admin)
    url = editor_url(mode)
    full = client.get(url)
    fragment = client.get(url, headers={"X-Workflow-View": "editor-v1"})
    assert full.status_code == fragment.status_code == 200
    assert fragment.headers["X-Workflow-View"] == "editor-v1"
    assert fragment.headers["Cache-Control"] == "private, no-store"
    assert "X-Workflow-View" in fragment.headers["Vary"]
    assert "X-Workflow-View" not in full.headers
    assert "<!DOCTYPE html>" in full.text
    assert "<!DOCTYPE html>" not in fragment.text
    assert 'id="sidebar"' not in fragment.text
    assert "installServerProduct" not in fragment.text
    for body in [full.text, fragment.text]:
        assert body.count('id="workflowCrud"') == 1
        assert f'{mode.title()} phase' in body
        assert f'{("rework" if mode == "initial" else "initial").title()} phase' not in body
        assert ('id="workflowForm"' in body) is admin
        assert ('onclick="addPhaseAfter(this)"' in body) is admin
    scripts = [attrs for tag, attrs in Elements(fragment.text).elements if tag == "script"]
    assert scripts == [{"type": "application/json", "id": "workflowEditorState"}]


@pytest.mark.parametrize("query,status", [("mode_id=invalid", 422), ("mode_id=999999", 404),
                                         ("workflow_id=999999", 404), ("profession_id=999999", 404)])
def test_fragment_errors_cannot_be_installed_as_an_editor(query, status):
    response = client.get("/workflows?" + query, headers={"X-Workflow-View": "editor-v1"})
    assert response.status_code == status
    assert "X-Workflow-View" not in response.headers


def test_unknown_fragment_version_remains_a_full_document():
    response = client.get(editor_url(), headers={"X-Workflow-View": "editor-v2"})
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text
    assert "X-Workflow-View" not in response.headers
