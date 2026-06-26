"""Integration / end-to-end tests — full workflow cycle.

Scenario: Seed DB → create task → step through phases → verify history
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.ui]

from project_workflow.infrastructure import conversation as convo
from project_workflow.infrastructure.db.uow import SAUnitOfWork

from project_workflow.interfaces.ui import app


client = TestClient(app)


class TestEndToEndWorkflow:
    """Full cycle via direct DB + API checks."""

    def test_seeded_db_has_workflows_and_agents(self, tmp_path: Path):
        """Seed импорт + проверка workflow-aware фаз и agents."""
        db_path = tmp_path / "test.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        seed_path = Path(__file__).parent.parent / "project_workflow" / "references" / "seed.json"
        # seed.json — top-level может быть object или list
        raw = json.loads(seed_path.read_text())
        if isinstance(raw, list):
            uow.import_phases(raw)
        else:
            uow.import_phases(raw["phases"])
        phases = uow.get_phases()
        assert len(phases) > 0
        p = phases[0]
        assert "id" in p and "name" in p and "phase_order" in p
        assert "execution_type" in p

    def test_create_task_and_history(self, tmp_path: Path):
        """Создание таски + запись истории."""
        db_path = tmp_path / "test2.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        uow.create_project({
            "code": "AAT",
            "name": "AAT",
            "key_prefixes": ["AAT"],
        })
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

    def test_cli_history_logs_and_reads(self, tmp_path: Path):
        """Лог CLI вызовов."""
        db_path = tmp_path / "test4.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        uow.log_cli_call("step", "AAT-10", '{"report": "done"}', '{"next": "1"}')
        uow.log_cli_call("history", "AAT-10", None, None)
        rows = uow.get_cli_history()
        assert len(rows) == 2
        assert {rows[0]["command"], rows[1]["command"]} == {"step", "history"}
        assert rows[1]["command"] == "history"

    def test_phase_with_agent(self, tmp_path: Path):
        """Фаза с agent_id без legacy group_id."""
        db_path = tmp_path / "test5.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        agent_id = uow.create_agent({"name": "test-bot", "description": "Executes delegated work"})
        uow.create_phase({
            "id": "p2",
            "name": "P2",
            "phase_order": 0,
            "agent_id": agent_id,
            "execution_type": "parallel",
        })
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


class TestConversationHistory:
    def test_get_messages_without_limit_returns_all_records(self, tmp_path: Path, monkeypatch):
        db_dir = tmp_path / ".project-workflow"
        db_path = db_dir / "conversation.db"
        monkeypatch.setattr("project_workflow.infrastructure.conversation.DB_DIR", db_dir)
        monkeypatch.setattr("project_workflow.infrastructure.conversation.DB_PATH", db_path)

        convo.add_message("99", "TASK-99", "user", "first")
        convo.add_message("99", "TASK-99", "agent", "second")
        convo.add_message("99", "TASK-99", "system", "third")

        rows = convo.get_messages("99", limit=None)

        assert [row.content for row in rows] == ["first", "second", "third"]


class TestEdgeCases:
    """Граничные случаи."""

    def test_phase_delete_cascades_instructions(self, tmp_path: Path):
        db_path = tmp_path / "test6.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        wid = uow.get_default_workflow()["id"]
        uow.create_phase({"workflow_id": wid, "id": "p3", "name": "P3", "phase_order": 0})
        uow.create_phase({"workflow_id": wid, "id": "p4", "name": "P4", "phase_order": 1})
        uow.create_instruction({"phase_id": "p3", "step_num": 1, "description": "Step"})
        uow.delete_phase("p3")
        assert uow.get_phase("p3") is None
        inst = uow.get_phase_instructions("p3")
        assert len(inst) == 0

    def test_empty_cli_history(self, tmp_path: Path):
        db_path = tmp_path / "test7.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        rows = uow.get_cli_history(limit=10)
        assert len(rows) == 0

    def test_task_history_no_skipped_status(self, tmp_path: Path):
        """В task_history статус skipped не должен использоваться, но DB его принимает."""
        db_path = tmp_path / "test8.db"
        uow = SAUnitOfWork(str(db_path))
        uow.init()
        uow.create_phase({"id": "0", "name": "Phase 0", "phase_order": 1})
        uow.create_project({
            "code": "AATSK",
            "name": "AATSK",
            "key_prefixes": ["AAT"],
        })
        uow.create_task({"task_key": "AAT-99", "title": "Skip Test"})
        task = uow.get_task_by_key("AAT-99")
        assert task is not None
        uow.add_task_history(task["id"], "0", "pending")
        # Re-adding with done status should update via ON CONFLICT
        uow.add_task_history(task["id"], "0", "done")
        hist = uow.get_task_history(task["id"])
        assert hist[0]["status"] == "done"
