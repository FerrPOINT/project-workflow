"""Tests for Web UI wizard page v5.0 — conversational mode."""

import pytest
from fastapi.testclient import TestClient

from wartz_workflow import ui as server


@pytest.fixture
def client(monkeypatch):
    from wartz_workflow.ui import ensure_templates
    ensure_templates()
    return TestClient(server.app)


class TestWizardPage:
    def test_wizard_page_returns_html(self, client):
        resp = client.get("/wizard/TEST-123")
        assert resp.status_code == 200
        html = resp.text
        assert "<html" in html
        assert "🧙 Wizard: TEST-123" in html

    def test_wizard_shows_phase_prompt(self, client):
        resp = client.get("/wizard/TEST-123")
        assert resp.status_code == 200
        html = resp.text
        # Should show phase instructions prompt
        assert "Фаза" in html
        assert "Обязательно выполнить" in html or "Инструкции" in html

    def test_wizard_has_textarea(self, client):
        resp = client.get("/wizard/TEST-123")
        assert resp.status_code == 200
        html = resp.text
        assert "<textarea name=\"notes\"" in html

    def test_wizard_form_present(self, client):
        resp = client.get("/wizard/TEST-123")
        assert resp.status_code == 200
        html = resp.text
        assert '<form id="wizardForm"' in html
        assert 'Отправить отчёт' in html

    def test_wizard_api_answer_returns_verdict(self, client):
        resp = client.post(
            "/api/wizard/TEST-123/answer",
            data={"notes": "Открыл Jira тикет, скопировал Summary, извлёк Acceptance Criteria"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "verdict" in data
        assert data["verdict"] in ("PASS", "FAIL")
        assert "phase" in data
        assert "covered" in data
        assert "missing" in data
        assert "message" in data

    def test_wizard_api_answer_empty_report(self, client):
        resp = client.post(
            "/api/wizard/TEST-123/answer",
            data={"notes": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["verdict"] == "FAIL"
        assert len(data["missing"]) > 0

    def test_wizard_api_answer_invalid_phase(self, client):
        resp = client.post(
            "/api/wizard/UNKNOWN-KEY/answer",
            data={"notes": "Открыл Jira, скопировал Summary"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "verdict" in data

    def test_wizard_nav_link_from_tasks(self, client):
        from wartz_workflow.conversation import add_wizard_answer
        resp = client.get("/tasks")
        assert resp.status_code == 200
        assert "</th>" in resp.text

    def test_wizard_instructions_api(self, client):
        resp = client.get("/api/wizard/TEST-123/instructions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "prompt" in data
        assert "Фаза" in data["prompt"]
