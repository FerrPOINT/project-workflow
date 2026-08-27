"""UI edge-case tests — error paths, helpers, and uncovered branches."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.ui]

from project_workflow.interfaces.ui import (
    _build_parallel_phase_blocks,
    _group_instructions,
    _load_cli_reference,
    _load_tasks,
    _load_workflows,
    app,
)
from project_workflow.interfaces.ui.helpers import _resolve_task_phase_id

client = TestClient(app)


# ═══════════════════════════════════════════════════════════
# Pure helpers
# ═══════════════════════════════════════════════════════════


class TestGroupInstructions:
    def test_groups_parallel_with_previous(self):
        instructions = [
            {"id": 1, "execution_type": "sync"},
            {"id": 2, "execution_type": "parallel"},
            {"id": 3, "execution_type": "sync"},
        ]
        result = _group_instructions(instructions)
        assert result == [[instructions[0], instructions[1]], [instructions[2]]]

    def test_empty_instructions(self):
        assert _group_instructions([]) == []

    def test_sync_breaks_group(self):
        inst = [
            {"step": "a", "execution_type": "sync"},
            {"step": "b", "execution_type": "parallel"},
            {"step": "c", "execution_type": "sync"},
        ]
        result = _group_instructions(inst)
        assert len(result) == 2


class TestBuildParallelPhaseBlocks:
    def test_empty(self):
        assert _build_parallel_phase_blocks([]) == []

    def test_single(self):
        blocks = _build_parallel_phase_blocks([{"id": 1, "code": "1", "execution_type": "sync"}])
        assert len(blocks) == 1
        assert blocks[0]["kind"] == "single"

    def test_parallel(self):
        blocks = _build_parallel_phase_blocks(
            [
                {"id": 1, "code": "1", "execution_type": "sync"},
                {"id": 2, "code": "2", "execution_type": "parallel", "parallel_with_phase_id": 3},
                {"id": 3, "code": "3", "execution_type": "parallel"},
            ]
        )
        assert [block["kind"] for block in blocks] == ["single", "parallel"]
        assert blocks[1]["phases"][0]["parallel_group"] == "2"
        assert blocks[1]["phases"][1]["parallel_group"] == "2"


class TestResolveTaskPhase:
    def test_by_id_match(self):
        phases = [{"id": 1, "code": "1", "name": "One", "phase_order": 1}]
        assert _resolve_task_phase_id(1, phases)["code"] == "1"

    @pytest.mark.parametrize("value", [None, "1", True, 0])
    def test_invalid_current_phase_id_fails_closed(self, value):
        with pytest.raises(ValueError):
            _resolve_task_phase_id(value, [])

    def test_unresolvable(self):
        with pytest.raises(ValueError, match="отсутствует"):
            _resolve_task_phase_id(99, [])


class TestLoadWorkflows:
    def test_empty(self, monkeypatch):
        db = MagicMock()
        db.get_workflows.return_value = []
        db.get_phases.return_value = []
        monkeypatch.setattr("project_workflow.interfaces.ui._app_state", MagicMock(get_db=lambda: db))
        assert _load_workflows() == []


class TestLoadTasks:
    def test_empty(self, monkeypatch):
        db = MagicMock()
        db.get_tasks.return_value = []
        db.get_workflows.return_value = []
        db.get_phases.return_value = []
        monkeypatch.setattr("project_workflow.interfaces.ui._app_state", MagicMock(get_db=lambda: db))
        assert _load_tasks() == []

    def test_task_done_with_history(self, monkeypatch):
        db = MagicMock()
        db.get_tasks.return_value = [
            {
                "id": 1,
                "task_key": "AAT-1",
                "status": "done",
                "current_phase_id": 1,
                "current_phase_code": "-1",
                "current_phase_name": "Start",
                "project_id": 10,
                "workflow_id": 1,
                "updated_at": "2025-02-01",
            }
        ]
        db.get_workflows.return_value = [{"id": 1}]
        db.get_phases.return_value = [{"id": 1, "code": "-1", "name": "Start"}]
        db.list_phase_events_batch.return_value = {
            1: [
                {"phase_id": 1, "event_type": "completed", "occurred_at": "2025-01-15"},
                {"phase_id": 1, "event_type": "completed", "occurred_at": "2025-01-20"},
            ]
        }
        db.step_history.latest_for_tasks.return_value = []
        db.get_projects.return_value = [{"id": 10, "code": "AAT", "name": "AAT"}]
        monkeypatch.setattr("project_workflow.interfaces.ui._app_state", MagicMock(get_db=lambda: db))
        tasks = _load_tasks()
        assert tasks[0]["completed_at"] == "2025-01-20"

    def test_task_done_without_completed_event_fails_closed(self, monkeypatch):
        db = MagicMock()
        db.get_tasks.return_value = [
            {
                "id": 1,
                "task_key": "AAT-1",
                "status": "done",
                "current_phase_id": 1,
                "current_phase_code": "-1",
                "current_phase_name": "Start",
                "project_id": 10,
                "workflow_id": 1,
                "updated_at": "2025-02-01",
            }
        ]
        db.get_workflows.return_value = [{"id": 1}]
        db.get_phases.return_value = [{"id": 1, "code": "-1", "name": "Start"}]
        db.list_phase_events_batch.return_value = {
            1: [{"phase_id": 1, "event_type": "entered", "occurred_at": "2025-01-15"}]
        }
        db.step_history.latest_for_tasks.return_value = []
        db.get_projects.return_value = [{"id": 10, "code": "AAT", "name": "AAT"}]
        monkeypatch.setattr("project_workflow.interfaces.ui._app_state", MagicMock(get_db=lambda: db))
        with pytest.raises(ValueError, match="нет события completed"):
            _load_tasks()


# ═══════════════════════════════════════════════════════════
# Task detail edge cases
# ═══════════════════════════════════════════════════════════


class TestTaskDetailEdgeCases:
    def test_task_detail_step_history_next_contract(self, monkeypatch):
        from project_workflow.interfaces.ui import _get_task_detail

        db = MagicMock()
        db.get_task_by_key.return_value = {
            "id": 1,
            "task_key": "AAT-1",
            "status": "active",
            "current_phase_id": 1,
            "title": "T",
            "workflow_id": 1,
            "project_id": 10,
        }
        db.projects.get_by_id.return_value.to_dict.return_value = {
            "id": 10,
            "code": "AAT",
            "name": "AAT",
        }
        db.list_phase_events.return_value = [{"phase_id": 1, "event_type": "entered", "occurred_at": "2025-01-01"}]
        db.get_phases.return_value = [
            {"id": 1, "code": "1", "name": "Current", "phase_order": 1, "execution_type": "sync"}
        ]
        db.list_step_history.return_value = [
            {
                "verdict": "pass",
                "worker_report": "done",
                "evaluation_snapshot": {"phase_code": "historical.1", "phase_name": "Historical phase"},
                "supervisor_response": {
                    "next_phase_code": "2",
                    "message": "ok",
                    "next_phase_contract": {
                        "phase_code": "2",
                        "phase_name": "Next",
                        "instructions": ["Do next"],
                        "required_checks": ["Check next"],
                        "required_evidence": ["Evidence next"],
                    },
                },
                "created_at": "2025-01-01",
            }
        ]
        monkeypatch.setattr("project_workflow.interfaces.ui._app_state", MagicMock(get_db=lambda: db))
        task = _get_task_detail("AAT-1")
        assert task["step_history"][0]["next_contract"] is not None
        assert task["step_history"][0]["next_contract"]["phase_name"] == "Next"
        assert task["step_history"][0]["phase_code"] == "historical.1"
        assert task["step_history"][0]["phase_name"] == "Historical phase"

    def test_task_detail_step_history_no_next_phase(self, monkeypatch):
        from project_workflow.interfaces.ui import _get_task_detail

        db = MagicMock()
        db.get_task_by_key.return_value = {
            "id": 1,
            "task_key": "AAT-1",
            "status": "active",
            "current_phase_id": 1,
            "title": "T",
            "workflow_id": 1,
            "project_id": 10,
        }
        db.projects.get_by_id.return_value.to_dict.return_value = {
            "id": 10,
            "code": "AAT",
            "name": "AAT",
        }
        db.list_phase_events.return_value = [{"phase_id": 1, "event_type": "entered", "occurred_at": "2025-01-01"}]
        db.get_phases.return_value = [
            {"id": 1, "code": "1", "name": "Current", "phase_order": 1, "execution_type": "sync"}
        ]
        db.list_step_history.return_value = [
            {
                "verdict": "pass",
                "worker_report": "done",
                "evaluation_snapshot": {"phase_code": "1", "phase_name": "Current"},
                "supervisor_response": {"message": "ok"},
                "created_at": "2025-01-01",
            }
        ]
        monkeypatch.setattr("project_workflow.interfaces.ui._app_state", MagicMock(get_db=lambda: db))
        task = _get_task_detail("AAT-1")
        assert task["step_history"][0]["next_contract"] is None

    def test_main_entry(self, monkeypatch):
        from project_workflow.interfaces.ui import main

        called = []
        monkeypatch.setattr("uvicorn.run", lambda *a, **kw: called.append((a, kw)))
        monkeypatch.setattr("sys.argv", ["ui", "--port", "8811"])
        try:
            main()
        except SystemExit:
            pass
        assert called


# ═══════════════════════════════════════════════════════════
# API error paths
# ═══════════════════════════════════════════════════════════


class TestApiErrorPaths:
    def test_api_phase_detail_not_found(self):
        response = client.get("/api/phases/999999")
        assert response.status_code == 404
        assert response.json()["ok"] is False

    def test_health_endpoint_ok(self):
        with patch("project_workflow.infrastructure.db.session.schema_is_ready", return_value=True):
            response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["database"] == "ok"
        assert "version" in data

    def test_health_endpoint_bad_db(self, monkeypatch):
        def _bad_engine(*a, **kw):
            raise RuntimeError("db down")

        monkeypatch.setattr("project_workflow.infrastructure.db.session.get_engine", _bad_engine)
        with patch(
            "project_workflow.application.state._AppState.create_uow",
            side_effect=AssertionError("health must not create a request UoW"),
        ):
            response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["ok"] is False
        assert data["database"] == "error"
        assert data["error_code"] == "database-unavailable"
        assert "db down" not in response.text

    def test_health_endpoint_rejects_schema_drift_without_details(self):
        with patch(
            "project_workflow.infrastructure.db.session.schema_is_ready",
            return_value=False,
        ):
            response = client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["ok"] is False
        assert data["database"] == "ok"
        assert data["schema"] == "error"
        assert data["error_code"] == "schema-not-ready"
        assert "SELECT" not in response.text
        assert "postgresql" not in response.text

    def test_api_workflow_create_missing_name(self):
        response = client.post("/api/workflows", json={})
        assert response.status_code == 422
        assert "name" in response.text

    def test_api_workflow_create_with_code_rejected(self):
        response = client.post("/api/workflows", json={"code": "X", "name": "Test"})
        assert response.status_code == 422
        assert "code" in response.text

    def test_api_tasks(self):
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_api_workflows(self):
        response = client.get("/api/workflows")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_api_phase_update_invalid(self):
        response = client.put("/api/phases/999999", json={"name": "x"})
        assert response.status_code == 404

    def test_api_agents(self):
        response = client.get("/api/agents")
        assert response.status_code == 200

    def test_api_project_tasks(self):
        response = client.get("/api/projects")
        assert response.status_code == 200


# ═══════════════════════════════════════════════════════════
# Page-level edge cases
# ═══════════════════════════════════════════════════════════


class TestPageEdgeCases:
    def test_index_page(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "Дашборд" in response.text

    def test_phases_page(self):
        response = client.get("/phases")
        assert response.status_code == 200

    def test_tasks_page(self):
        response = client.get("/tasks")
        assert response.status_code == 200

    def test_projects_page(self):
        response = client.get("/projects")
        assert response.status_code == 200

    def test_settings_page(self):
        response = client.get("/settings")
        assert response.status_code == 200

    def test_agents_page(self):
        response = client.get("/agents")
        assert response.status_code == 200

    def test_workflows_page(self):
        response = client.get("/workflows")
        assert response.status_code == 200

    def test_task_detail_missing(self):
        response = client.get("/task/999999")
        assert response.status_code == 404
        assert "Задача не найдена" in response.text
        assert "К списку задач" in response.text

    def test_phase_detail_missing(self):
        response = client.get("/phase/999999")
        assert response.status_code == 404
        assert "Фаза не найдена" in response.text
        assert "К фазам" in response.text


# ═══════════════════════════════════════════════════════════
# CLI reference
# ═══════════════════════════════════════════════════════════


class TestLoadCliReference:
    def test_loads_commands(self):
        commands = _load_cli_reference()
        assert isinstance(commands, list)
