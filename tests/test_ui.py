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
        assert "wartz-workflow UI" in response.text

    def test_index_contains_dashboard(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "Dashboard" in response.text

    def test_nav_links_present(self):
        response = client.get("/")
        assert "Dashboard" in response.text
        assert "Phases" in response.text
        assert "Tasks" in response.text
        assert "Config" in response.text


class TestPhasesPage:
    def test_phases_returns_html(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Все фазы" in response.text

    def test_phases_api_returns_json(self):
        response = client.get("/api/phases")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "phases" in data


class TestTasksPage:
    def test_tasks_returns_html(self):
        response = client.get("/tasks")
        assert response.status_code == 200
        assert "Задачи" in response.text

    def test_tasks_api_returns_json(self):
        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "tasks" in data


class TestTaskDetailPage:
    def test_task_detail_returns_html(self):
        response = client.get("/task/TEST-1")
        assert response.status_code == 200
        # Should show message history (empty is ok)
        assert "История:" in response.text

    def test_task_detail_api(self):
        response = client.get("/api/task/TEST-1/messages")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["task_id"] == "TEST-1"


class TestConfigPage:
    def test_config_returns_html(self):
        response = client.get("/config")
        assert response.status_code == 200
        assert "Конфигурация" in response.text

    def test_config_api_returns_json(self):
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "wartz_dir" in data
        assert "blockers" in data
        assert "phase_order" in data


class TestNotFound:
    def test_404_on_unknown(self):
        response = client.get("/nonexistent")
        # FastAPI default 404
        assert response.status_code == 404
