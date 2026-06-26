"""API route coverage gap tests using mocked _app_state."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.ui]

from project_workflow.interfaces.ui import app


client = TestClient(app)


def _fake_app_state(**kwargs):
    """Build a fake _AppState-like object whose attributes return MagicMocks by default."""
    state = MagicMock()
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


class TestApiTaskDetail:
    def test_task_detail_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.get_db.return_value.get_task_by_key.return_value = None
            response = client.get("/api/tasks/MISSING-99")
        assert response.status_code == 404


class TestApiPhaseCreate:
    def test_missing_workflow_id(self):
        response = client.post("/api/phases", json={"name": "X", "phase_order": 1})
        assert response.status_code == 400

    def test_missing_phase_order(self):
        response = client.post("/api/phases", json={"name": "X", "workflow_id": 1})
        assert response.status_code == 400

    def test_invalid_string_workflow_id_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.workflow_service.return_value.get_workflow.return_value = None
            response = client.post("/api/phases", json={"name": "X", "phase_order": 1, "workflow_id": "999"})
        assert response.status_code == 400

    def test_numeric_workflow_id_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.workflow_service.return_value.get_workflow.return_value = None
            response = client.post("/api/phases", json={"name": "X", "phase_order": 1, "workflow_id": 999})
        assert response.status_code == 400

    def test_code_field_is_set(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.workflow_service.return_value.get_workflow.return_value = {"id": 1}
            state.phase_service.return_value.list_phases.return_value = []
            state.phase_service.return_value.create_phase.return_value = {"id": 10}
            response = client.post("/api/phases", json={"name": "X", "phase_order": 1, "workflow_id": 1, "code": "custom"})
        assert response.status_code == 200
        assert response.json()["phase_id"] == 10


class TestApiPhaseUpdate:
    def test_phase_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._load_phase_detail", return_value=None):
            response = client.put("/api/phases/1", json={"name": "X"})
        assert response.status_code == 404

    def test_coerce_id_returns_none(self):
        with patch("project_workflow.interfaces.ui.routes.api._load_phase_detail", return_value={"id": 1}):
            with patch("project_workflow.interfaces.ui.routes.api._coerce_phase_db_id", return_value=None):
                response = client.put("/api/phases/1", json={"name": "X"})
        assert response.status_code == 404

    def test_forbidden_phase_num(self):
        with patch("project_workflow.interfaces.ui.routes.api._load_phase_detail", return_value={"id": 1}):
            response = client.put("/api/phases/1", json={"phase_num": 2, "name": "X"})
        assert response.status_code == 400

    def test_forbidden_code(self):
        with patch("project_workflow.interfaces.ui.routes.api._load_phase_detail", return_value={"id": 1}):
            response = client.put("/api/phases/1", json={"code": "NEW", "name": "X"})
        assert response.status_code == 400

    def test_empty_payload_ok(self):
        with patch("project_workflow.interfaces.ui.routes.api._load_phase_detail", return_value={"id": 1}):
            with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
                state.get_service.return_value.update_phase.return_value = None
                response = client.put("/api/phases/1", json={})
        assert response.status_code == 200


class TestApiPhaseDelete:
    def test_phase_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.phase_service.return_value.get_phase.return_value = None
            response = client.delete("/api/phases/1")
        assert response.status_code == 404


class TestApiPhaseBatchOrder:
    def test_empty_orders(self):
        response = client.put("/api/phases/order", json={"orders": []})
        assert response.status_code == 400

    def test_invalid_phase_id(self):
        with patch("project_workflow.interfaces.ui.routes.api._coerce_phase_db_id", return_value=None):
            response = client.put("/api/phases/order", json={"orders": [{"phase_id": "bad", "phase_order": 1}]})
        assert response.status_code == 400


class TestApiWorkflowDelete:
    def test_workflow_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.workflow_service.return_value.get_workflow.return_value = None
            response = client.delete("/api/workflows/1")
        assert response.status_code == 404

    def test_default_workflow(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.workflow_service.return_value.get_workflow.return_value = {"id": 1, "is_default": True}
            state.phase_service.return_value.list_phases.return_value = []
            response = client.delete("/api/workflows/1")
        assert response.status_code == 400


class TestApiProjectUpdate:
    def test_project_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.project_service.return_value.get_project.return_value = None
            response = client.put("/api/projects/1", json={"name": "X"})
        assert response.status_code == 404

    def test_update_description(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.project_service.return_value.get_project.return_value = {"id": 1}
            state.project_service.return_value.get_project.side_effect = [{"id": 1}, {"id": 1}]
            response = client.put("/api/projects/1", json={"description": "new"})
        assert response.status_code == 200


class TestApiProjectDelete:
    def test_project_delete_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.task_service.return_value.list_tasks.return_value = []
            state.project_service.return_value.get_project.return_value = None
            response = client.delete("/api/projects/1")
        assert response.status_code == 404


class TestApiAgentUpdate:
    def test_agent_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.agent_service.return_value.get_agent.return_value = None
            response = client.put("/api/agents/1", json={"name": "X"})
        assert response.status_code == 404


class TestApiAgentDelete:
    def test_agent_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.agent_service.return_value.get_agent.return_value = None
            response = client.delete("/api/agents/1")
        assert response.status_code == 404

    def test_agent_assigned_to_phase(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.agent_service.return_value.get_agent.return_value = {"id": 1}
            state.phase_service.return_value.list_phases.return_value = [{"agent_id": 1}]
            response = client.delete("/api/agents/1")
        assert response.status_code == 400


class TestApiInstructionCreate:
    def test_phase_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.phase_service.return_value.get_phase.return_value = None
            response = client.post("/api/instructions", json={"phase_id": 1, "description": "d"})
        assert response.status_code == 404


class TestApiInstructionUpdate:
    def test_instruction_not_found(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.instruction_service.return_value.get_instruction.return_value = None
            response = client.put("/api/instructions/1", json={"description": "d"})
        assert response.status_code == 404

    def test_update_step_num(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.instruction_service.return_value.get_instruction.return_value = {"id": 1}
            state.instruction_service.return_value.get_instruction.side_effect = [{"id": 1}, {"id": 1}]
            response = client.put("/api/instructions/1", json={"step_num": 5})
        assert response.status_code == 200


class TestApiInstructionUpdateSkills:
    def test_skills_string_split(self):
        with patch("project_workflow.interfaces.ui.routes.api._app_state") as state:
            state.instruction_service.return_value.get_instruction.return_value = {"id": 1}
            state.instruction_service.return_value.get_instruction.side_effect = [{"id": 1}, {"id": 1}]
            response = client.put("/api/instructions/1/skills", json={"skills": "a\nb"})
        assert response.status_code == 200
