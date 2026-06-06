"""FastAPI endpoint tests to boost ui.py coverage.

Uses TestClient to hit GET/POST/PUT endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from wartz_workflow.ui import app

client = TestClient(app)


def _phase_id(code: str) -> int:
    from wartz_workflow.ui import _get_db

    phase = _get_db().get_phase(code)
    assert phase is not None
    return int(phase["id"])


class TestIndex:
    def test_index(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "")
        assert "Дашборд" in resp.text
        assert "Активные задачи" in resp.text

    def test_phases_list_page(self):
        resp = client.get("/phases")
        assert resp.status_code == 200

    def test_phase_detail_page(self):
        resp = client.get(f"/phase/{_phase_id('0.0a')}")
        assert resp.status_code == 200

    def test_settings_page(self):
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_projects_page(self):
        resp = client.get("/projects")
        assert resp.status_code == 200
        assert "Проекты" in resp.text

    def test_tasks_page_has_project_column(self):
        resp = client.get("/tasks")
        assert resp.status_code == 200
        assert "Проект" in resp.text

    def test_settings_page_describes_cli_commands(self):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "wartz-workflow step" in resp.text
        assert "wartz-workflow history" in resp.text
        assert "wartz-workflow ui" not in resp.text
        assert "--report" in resp.text
        assert "--n" in resp.text
        assert ">--repo<" not in resp.text
        assert ">--skip<" not in resp.text


class TestApiPhases:
    def test_list_phases(self):
        resp = client.get("/api/phases")
        assert resp.status_code == 200
        data = resp.json()
        assert "phases" in data

    def test_get_phase(self):
        resp = client.get(f"/api/phases/{_phase_id('0.0a')}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_legacy_phase_code_route_removed_from_api(self):
        resp = client.get("/api/phases/0.7")
        assert resp.status_code == 404

    def test_update_phase_missing(self):
        resp = client.put("/api/phases/-9999", json={"body": {}})
        assert resp.status_code in (404, 422)

    def test_api_groups(self):
        resp = client.get("/api/groups")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_api_settings(self):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "commands" in data
        names = {cmd["name"] for cmd in data["commands"]}
        assert {"step", "history"}.issubset(names)
        assert "ui" not in names


class TestApiWizard:
    def test_wizard_evaluate(self):
        resp = client.post("/api/wizard/evaluate", json={"task_key": "AAT-999", "report": "test"})
        assert resp.status_code == 200
        data = resp.json()
        assert "verdict" in data

    def test_wizard_context(self):
        resp = client.get("/api/wizard/AAT-999/context")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_wizard_phase_post(self):
        resp = client.post("/api/wizard/0", json={"report": "done"})
        assert resp.status_code in (200, 404)


class TestDeleteResources:
    def test_delete_instruction_not_found(self):
        resp = client.delete("/api/instructions/99999")
        assert resp.status_code == 200  # current implementation returns ok even if missing

    def test_delete_check_not_found(self):
        resp = client.delete("/api/checks/99999")
        assert resp.status_code == 200

    def test_delete_evidence_not_found(self):
        resp = client.delete("/api/evidence/99999")
        assert resp.status_code == 200
