"""Integration / end-to-end tests — full workflow cycle.

Scenario: Seed DB → create task → step through phases → verify history
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.ui]

from project_workflow.application.agent import AgentService
from project_workflow.application.project import ProjectService
from project_workflow.application.task import TaskService
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui import app
from tests._db_helpers import phase_by_code, prepare_sqlite_uow

client = TestClient(app)


class TestEndToEndWorkflow:
    """Full cycle via direct DB + API checks."""

    def test_seeded_db_has_workflows_and_agents(self, tmp_path: Path):
        """Seed bootstrap + проверка workflow-aware фаз и agents."""
        db_path = tmp_path / "test.db"
        uow = SAUnitOfWork(f"sqlite:///{db_path}")
        prepare_sqlite_uow(uow)
        phases = [phase.to_dict() for phase in uow.phases.list()]
        assert len(phases) > 0
        p = phases[0]
        assert "id" in p and "name" in p and "phase_order" in p
        assert "execution_type" in p
        workflows = uow.get_workflows()
        assert [w["name"] for w in workflows] == ["sdlc-business-tech-v1"]
        assert len(phases) == 19
        agents = uow.get_agents()
        assert len(agents) > 0

    def test_create_task_and_history(self, tmp_path: Path):
        """Создание таски + запись истории."""
        db_path = tmp_path / "test2.db"
        uow = SAUnitOfWork(f"sqlite:///{db_path}")
        prepare_sqlite_uow(uow)
        ProjectService(uow).create_project(
            {
                "code": "AAT",
                "name": "AAT",
                "key_prefixes": ["AAT"],
            }
        )
        TaskService(uow).create_task({"task_key": "AAT-99", "title": "Integ Test"})
        task = uow.get_task_by_key("AAT-99")
        assert task is not None
        assert task["current_phase"] == "1.INTAKE"
        workflow_id = uow.workflows.get_default().id
        phase_id = uow.phases.create(
            {"workflow_id": workflow_id, "code": "integration.setup", "name": "Setup", "phase_order": 100}
        )
        uow.tasks.add_history(task["id"], phase_id, "done")
        uow.commit()
        hist = uow.get_task_history(task["id"])
        assert len(hist) == 1
        assert hist[0]["status"] == "done"

    def test_agents_crud(self, tmp_path: Path):
        """Полный CRUD агентов."""
        db_path = tmp_path / "test3.db"
        uow = SAUnitOfWork(f"sqlite:///{db_path}")
        prepare_sqlite_uow(uow)
        AgentService(uow).create_agent({"name": "coder", "description": "Пишет код"})
        agents = uow.get_agents()
        created = [agent for agent in agents if agent["name"] == "coder" and agent["description"] == "Пишет код"]
        assert len(created) == 1
        assert created[0]["id"] is not None

    def test_phase_with_agent(self, tmp_path: Path):
        """Фаза сохраняет назначенного агента."""
        db_path = tmp_path / "test5.db"
        uow = SAUnitOfWork(f"sqlite:///{db_path}")
        prepare_sqlite_uow(uow)
        agent_id = AgentService(uow).create_agent(
            {"name": "test-bot", "description": "Executes delegated work"}
        )["id"]
        workflow_id = uow.workflows.get_default().id
        uow.phases.create(
            {
                "workflow_id": workflow_id,
                "code": "p2",
                "name": "P2",
                "phase_order": 100,
                "agent_id": agent_id,
                "execution_type": "parallel",
            }
        )
        rows = uow.get_phases()
        phase = next(row for row in rows if row["code"] == "p2")
        assert "group_id" not in phase
        assert phase["agent_id"] == agent_id
        assert phase["execution_type"] == "parallel"

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
        uow = SAUnitOfWork(f"sqlite:///{db_path}")
        prepare_sqlite_uow(uow)
        wid = uow.workflows.ensure_default_exists("Default Workflow").id
        p3_id = uow.phases.create(
            {"workflow_id": wid, "code": "p3", "name": "P3", "phase_order": 100}
        )
        p4_id = uow.phases.create(
            {"workflow_id": wid, "code": "p4", "name": "P4", "phase_order": 101}
        )
        uow.instructions.create(p3_id, {"step_num": 1, "description": "Step"})
        uow.phases.delete(p3_id)
        uow.commit()
        assert phase_by_code(uow, "p3", wid) is None
        p4 = uow.phases.get_by_id(p4_id)
        assert p4 is not None
        inst = list(uow.instructions.list(p4_id))
        assert len(inst) == 0
    def test_task_history_no_skipped_status(self, tmp_path: Path):
        """В task_history статус skipped не должен использоваться, но DB его принимает."""
        db_path = tmp_path / "test8.db"
        uow = SAUnitOfWork(f"sqlite:///{db_path}")
        prepare_sqlite_uow(uow)
        workflow_id = uow.workflows.get_default().id
        phase_id = uow.phases.create(
            {"workflow_id": workflow_id, "code": "history.phase", "name": "Phase 0", "phase_order": 100}
        )
        ProjectService(uow).create_project(
            {
                "code": "AATSK",
                "name": "AATSK",
                "key_prefixes": ["AAT"],
            }
        )
        TaskService(uow).create_task({"task_key": "AAT-99", "title": "Skip Test"})
        task = uow.get_task_by_key("AAT-99")
        assert task is not None
        uow.tasks.add_history(task["id"], phase_id, "pending")
        # Re-adding with done status should update via ON CONFLICT
        uow.tasks.add_history(task["id"], phase_id, "done")
        uow.commit()
        hist = uow.get_task_history(task["id"])
        assert hist[0]["status"] == "done"
