"""Integration / end-to-end tests — full workflow cycle.

Scenario: Seed DB → create task → step through phases → verify history
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.ui]

from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui import app

client = TestClient(app)


class TestEndToEndWorkflow:
    """Full cycle via direct DB + API checks."""

    def test_explicit_catalog_setup_has_workflows_and_agents(self, tmp_path: Path):
        """Explicit catalog setup creates workflow phases and agents."""
        db_path = tmp_path / "test.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        assert uow.get_all_phases() == []
        schema.ensure_phase_catalog(uow)
        phases = uow.get_all_phases()
        assert len(phases) > 0
        p = phases[0]
        assert "id" in p and "name" in p and "phase_order" in p
        assert "execution_type" in p
        assert uow.get_workflows()
        agents = uow.get_agents()
        assert len(agents) > 0

    def test_create_task_and_history(self, tmp_path: Path):
        """Создание таски + запись истории."""
        db_path = tmp_path / "test2.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        uow.create_project(
            {
                "code": "AAT",
                "name": "AAT",
                "key_prefixes": ["AAT"],
            }
        )
        uow.create_task({"task_key": "AAT-99", "title": "Integ Test"})
        task = uow.get_task_by_key("AAT-99")
        assert task is not None
        assert int(task["current_phase"]) == -1
        uow.create_phase({"id": "0", "name": "Setup", "phase_order": 0})
        uow.add_task_history(task["id"], "0", "done")
        hist = uow.get_task_history(task["id"])
        assert len(hist) == 1
        assert hist[0]["status"] == "done"

    def test_agents_crud(self, tmp_path: Path):
        """Полный CRUD агентов."""
        db_path = tmp_path / "test3.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        uow.create_agent({"name": "coder", "description": "Пишет код"})
        agents = uow.get_agents()
        created = [agent for agent in agents if agent["name"] == "coder" and agent["description"] == "Пишет код"]
        assert len(created) == 1
        assert created[0]["id"] is not None

    def test_phase_with_agent(self, tmp_path: Path):
        """Фаза с agent_id без legacy group_id."""
        db_path = tmp_path / "test5.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        agent_id = uow.create_agent({"name": "test-bot", "description": "Executes delegated work"})
        uow.create_phase(
            {
                "id": "p2",
                "name": "P2",
                "phase_order": 0,
                "agent_id": agent_id,
                "execution_type": "parallel",
            }
        )
        rows = uow.get_phases()
        assert len(rows) == 1
        assert "group_id" not in rows[0]
        assert rows[0]["agent_id"] == agent_id
        assert rows[0]["execution_type"] == "parallel"

    def test_api_serves_phases(self):
        """GET /api/phases отдаёт JSON объект с phases."""
        resp = client.get("/api/phases")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
        assert "phases" in data


class TestEdgeCases:
    """Граничные случаи."""

    def test_phase_delete_cascades_instructions(self, tmp_path: Path):
        db_path = tmp_path / "test6.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        wid = uow.workflows.ensure_default_exists().id
        uow.create_phase({"workflow_id": wid, "id": "p3", "name": "P3", "phase_order": 0})
        uow.create_phase({"workflow_id": wid, "id": "p4", "name": "P4", "phase_order": 1})
        uow.create_instruction({"phase_id": "p3", "step_num": 1, "description": "Step"})
        uow.delete_phase("p3")
        assert uow.get_phase("p3") is None
        p4 = uow.get_phase("p4")
        assert p4 is not None
        inst = list(uow.instructions.list(int(p4["id"])))
        assert len(inst) == 0
    def test_task_history_no_skipped_status(self, tmp_path: Path):
        """В task_history статус skipped не должен использоваться, но DB его принимает."""
        db_path = tmp_path / "test8.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        uow.create_phase({"id": "0", "name": "Phase 0", "phase_order": 1})
        uow.create_project(
            {
                "code": "AATSK",
                "name": "AATSK",
                "key_prefixes": ["AAT"],
            }
        )
        uow.create_task({"task_key": "AAT-99", "title": "Skip Test"})
        task = uow.get_task_by_key("AAT-99")
        assert task is not None
        uow.add_task_history(task["id"], "0", "pending")
        # Re-adding with done status should update via ON CONFLICT
        uow.add_task_history(task["id"], "0", "done")
        hist = uow.get_task_history(task["id"])
        assert hist[0]["status"] == "done"
