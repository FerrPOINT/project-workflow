"""Tests for Web UI wizard page."""
import pytest
from fastapi.testclient import TestClient

from wartz_workflow import ui as server


@pytest.fixture
def client(monkeypatch):
    # Ensure templates exist
    from wartz_workflow.ui import ensure_templates
    ensure_templates()
    return TestClient(server.app)


class TestWizardPage:
    def test_wizard_page_returns_html(self, client):
        resp = client.get("/wizard/TEST-123")
        assert resp.status_code == 200
        html = resp.text
        assert "<html" in html
        assert "Wizard: TEST-123" in html

    def test_wizard_shows_phase_name(self, client):
        resp = client.get("/wizard/TEST-123")
        assert resp.status_code == 200
        html = resp.text
        # Phase -1 should be shown initially
        assert "Task Intake" in html

    def test_wizard_checklist_present(self, client):
        resp = client.get("/wizard/TEST-123")
        assert resp.status_code == 200
        html = resp.text
        # Should contain checklist checkboxes
        assert '<input type="checkbox"' in html
        assert 'name="done_items"' in html

    def test_wizard_form_present(self, client):
        resp = client.get("/wizard/TEST-123")
        assert resp.status_code == 200
        html = resp.text
        assert '<form id="wizardForm"' in html
        assert '<textarea name="notes"' in html
        assert 'skipPhase()' in html

    def test_wizard_api_answer_basic(self, client):
        resp = client.post(
            "/api/wizard/TEST-123/answer",
            data={"done_items": ["c0"], "notes": "done"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["status"] in ("partial", "advanced")
        assert "done" in data
        assert "total" in data

    def test_wizard_api_answer_empty(self, client):
        resp = client.post(
            "/api/wizard/TEST-123/answer",
            data={"notes": ""}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_wizard_api_answer_invalid_phase(self, client):
        resp = client.post(
            "/api/wizard/UNKNOWN-KEY/answer",
            data={"done_items": ["c0"], "notes": "x"}
        )
        # Should still return (wizard creates phase or defaults to Phase -1)
        assert resp.status_code == 200

    def test_wizard_nav_link_from_tasks(self, client):
        # Make sure there's at least one task
        from wartz_workflow.conversation import add_wizard_answer
        resp = client.get("/tasks")
        assert resp.status_code == 200
        # Tasks table renders even empty; UI nav works
        assert "</th>" in resp.text
