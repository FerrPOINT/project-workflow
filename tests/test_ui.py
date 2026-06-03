"""Tests for UI (FastAPI endpoints)."""

import pytest
from fastapi.testclient import TestClient

from wartz_workflow.ui import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    """Populate DB with YAML phases before UI tests."""
    from wartz_workflow.ui import _get_db, _yaml_to_sqlite
    wdb = _get_db()
    if wdb.is_empty():
        _yaml_to_sqlite()


class TestIndexPage:
    def test_index_returns_html(self):
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "wartz" in response.text
        assert "workflow" in response.text

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
        assert 'class="kanban-card"' in response.text

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
        assert 'flow-card' in response.text

    def test_phase_detail_404_on_unknown(self):
        response = client.get("/phase/nonexistent")
        assert response.status_code == 404


class TestPhaseUpdate:
    def test_api_phase_update_bulk(self):
        resp = client.put("/api/phases/-1", json={
            "instructions": [
                {"description": "Test 1", "execution_type": "sync"},
                {"description": "Test 2", "execution_type": "parallel"}
            ],
            "checks": [{"description": "Check 1"}],
            "evidence": [{"description": "Evidence 1"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["ids"]["instructions"]) == 2
        assert len(data["ids"]["checks"]) == 1
        assert len(data["ids"]["evidence"]) == 1

    def test_api_phase_update_returns_ids(self):
        resp = client.put("/api/phases/-1", json={
            "instructions": [{"description": "X", "execution_type": "sync"}]
        })
        data = resp.json()
        # IDs must be positive integers
        assert all(isinstance(i, int) and i > 0 for i in data["ids"]["instructions"])


class TestDragDropAPI:
    """Tests for drag-and-drop backend APIs."""

    def test_api_batch_order_update(self):
        resp = client.put("/api/phases/order", json={
            "orders": [
                {"phase_id": "-1", "phase_order": 1},
                {"phase_id": "0", "phase_order": 2},
                {"phase_id": "1", "phase_order": 3},
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["updated"] == 3

    def test_api_batch_order_empty_error(self):
        resp = client.put("/api/phases/order", json={"orders": []})
        assert resp.status_code == 400
        data = resp.json()
        assert data["ok"] is False

    def test_api_single_phase_order(self):
        resp = client.put("/api/phases/1/order", json={"phase_order": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["phase_id"] == "1"
        assert data["phase_order"] == 5

    def test_api_single_phase_order_missing(self):
        resp = client.put("/api/phases/1/order", json={})
        assert resp.status_code == 400
        data = resp.json()
        assert data["ok"] is False

    def test_api_parallel_groups_update(self):
        resp = client.put("/api/phases/parallel", json={
            "groups": [["4.5", "5"], ["7.5", "7.6"]],
            "clear": ["3.5"]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["groups_set"] > 0
        assert data["cleared"] == 1


class TestKanbanHTML:
    """Tests for drag-and-drop HTML attributes in Kanban."""

    def test_kanban_cards_are_draggable(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'draggable="true"' in response.text
        assert 'ondragstart="cardDragStart(event)"' in response.text

    def test_kanban_has_drop_zones(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'ondrop="colDrop(event)"' in response.text

    def test_kanban_has_data_attrs(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'data-phase-id=' in response.text
        assert 'data-phase-order=' in response.text


class TestExecutionHTML:
    """Tests for drag-and-drop HTML attributes in execution graph."""

    def test_execution_nodes_are_draggable(self):
        response = client.get("/execution")
        assert response.status_code == 200
        assert 'draggable="true"' in response.text
        assert 'ondragstart="nodeDragStart(event)"' in response.text

    def test_execution_has_drop_zones(self):
        response = client.get("/execution")
        assert response.status_code == 200
        assert 'class="drop-zone"' in response.text
        assert 'ondrop="zoneDrop(event)"' in response.text

    def test_execution_has_controls(self):
        response = client.get("/execution")
        assert response.status_code == 200
        assert 'saveLayout()' in response.text
        assert 'resetLayout()' in response.text
        assert 'Разъединить' in response.text
