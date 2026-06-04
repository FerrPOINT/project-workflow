"""Test API routers (FastAPI)."""

import pytest
from fastapi.testclient import TestClient
from wartz_workflow.ui import app

client = TestClient(app)


class TestPhasesRouter:
    def test_list_phases(self):
        resp = client.get("/api/phases")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "phases" in data


class TestWizardRouter:
    def test_wizard_evaluate(self):
        resp = client.post("/api/wizard/evaluate", json={"task_key": "AAT-999", "report": "done"})
        assert resp.status_code == 200
        data = resp.json()
        assert "verdict" in data
