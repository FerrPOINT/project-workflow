"""Tests for UI (FastAPI endpoints)."""

import pytest
from fastapi.testclient import TestClient

from wartz_workflow.ui import app


client = TestClient(app)


class TestIndexPage:
    def test_index_returns_html(self):
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "wartz-workflow" in response.text

    def test_index_has_nav(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "Фазы" in response.text


class TestPhasesPage:
    def test_phases_returns_html(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Все фазы" in response.text

    def test_phases_has_phase_rows(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'class="phase-row"' in response.text

    def test_phases_api_returns_json(self):
        response = client.get("/api/phases")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "phases" in data
        assert len(data["phases"]) > 0


class TestPhaseDetail:
    def test_phase_detail_returns_html(self):
        response = client.get("/phase/-1")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Инструкции" in response.text

    def test_phase_detail_has_instructions(self):
        response = client.get("/phase/-1")
        assert response.status_code == 200
        assert 'class="instruction"' in response.text

    def test_phase_detail_404_on_unknown(self):
        response = client.get("/phase/nonexistent")
        assert response.status_code == 404


class TestTasksPage:
    def test_tasks_returns_html(self):
        response = client.get("/tasks")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Задачи" in response.text


class TestNotFound:
    def test_404_on_unknown(self):
        response = client.get("/nonexistent")
        assert response.status_code == 404
