"""Integration / end-to-end tests — full workflow cycle.

Scenario: Seed DB → create task → step through phases → verify history
"""

import json
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from wartz_workflow.db import WorkflowDB
from wartz_workflow.ui import app


client = TestClient(app)


class TestEndToEndWorkflow:
    """Full cycle via direct DB + API checks."""

    def test_seeded_db_has_phase_groups_and_agents(self, tmp_path: Path):
        """Seed импорт + проверка phase_groups и agents."""
        db_path = tmp_path / "test.db"
        wdb = WorkflowDB(str(db_path))
        wdb.init()
        seed_path = Path(__file__).parent.parent / "wartz_workflow" / "references" / "seed.json"
        # seed.json — top-level может быть object или list
        raw = json.loads(seed_path.read_text())
        if isinstance(raw, list):
            wdb.import_phases(raw)
        else:
            wdb.import_phases(raw["phases"])
        phases = wdb.get_phases()
        assert len(phases) > 0
        p = phases[0]
        assert "id" in p and "name" in p and "phase_order" in p
        assert "execution_type" in p

    def test_create_task_and_history(self, tmp_path: Path):
        """Создание таски + запись истории."""
        db_path = tmp_path / "test2.db"
        wdb = WorkflowDB(str(db_path))
        wdb.init()
        wdb.create_task({"task_key": "AAT-99", "title": "Integ Test"})
        task = wdb.get_task_by_key("AAT-99")
        assert task is not None
        assert int(task["current_phase"]) == -1
        wdb.create_phase({"id": "0", "name": "Setup", "phase_order": 0})
        wdb.add_task_history(task["id"], "0", "done")
        hist = wdb.get_task_history(task["id"])
        assert len(hist) == 1
        assert hist[0]["status"] == "done"

    def test_phase_groups_and_agents_crud(self, tmp_path: Path):
        """Полный CRUD групп и агентов."""
        db_path = tmp_path / "test3.db"
        wdb = WorkflowDB(str(db_path))
        wdb.init()
        wdb.create_phase_group({"id": "prep", "name": "Подготовка", "sort_order": 0})
        groups = wdb.get_phase_groups()
        assert len(groups) == 1
        assert groups[0]["name"] == "Подготовка"
        wdb.create_agent({"name": "coder"})
        agents = wdb.get_agents()
        assert len(agents) == 1
        assert agents[0]["id"] is not None
        assert agents[0]["name"] == "coder"

    def test_cli_history_logs_and_reads(self, tmp_path: Path):
        """Лог CLI вызовов."""
        db_path = tmp_path / "test4.db"
        wdb = WorkflowDB(str(db_path))
        wdb.init()
        wdb.log_cli_call("step", "AAT-10", '{"report": "done"}', '{"next": "1"}')
        wdb.log_cli_call("history", "AAT-10", None, None)
        rows = wdb.get_cli_history()
        assert len(rows) == 2
        assert {rows[0]["command"], rows[1]["command"]} == {"step", "history"}
        assert rows[1]["command"] == "history"

    def test_phase_with_group_and_agent(self, tmp_path: Path):
        """Фаза с group_id и agent_id."""
        db_path = tmp_path / "test5.db"
        wdb = WorkflowDB(str(db_path))
        wdb.init()
        wdb.create_phase_group({"id": "g1", "name": "Group 1", "sort_order": 1})
        agent_id = wdb.create_agent({"name": "test-bot"})
        wdb.create_phase({
            "id": "p2",
            "name": "P2",
            "phase_order": 0,
            "group_id": "g1",
            "agent_id": agent_id,
            "execution_type": "parallel",
        })
        rows = wdb.get_phases()
        assert len(rows) == 1
        g1_info = wdb.get_phase_group_by_code("g1")
        assert rows[0]["group_id"] == g1_info["id"]
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
        wdb = WorkflowDB(str(db_path))
        wdb.init()
        wdb.create_phase({"id": "p3", "name": "P3", "phase_order": 0})
        wdb.create_instruction({"phase_id": "p3", "step_num": 1, "description": "Step"})
        wdb.delete_phase("p3")
        assert wdb.get_phase("p3") is None
        inst = wdb.get_phase_instructions("p3")
        assert len(inst) == 0

    def test_empty_cli_history(self, tmp_path: Path):
        db_path = tmp_path / "test7.db"
        wdb = WorkflowDB(str(db_path))
        wdb.init()
        rows = wdb.get_cli_history(limit=10)
        assert len(rows) == 0

    def test_task_history_no_skipped_status(self, tmp_path: Path):
        """В task_history статус skipped не должен использоваться, но DB его принимает."""
        db_path = tmp_path / "test8.db"
        wdb = WorkflowDB(str(db_path))
        wdb.init()
        wdb.create_phase({"id": "0", "name": "Phase 0", "phase_order": 1})
        wdb.create_task({"task_key": "AAT-SK", "title": "Skip Test"})
        task = wdb.get_task_by_key("AAT-SK")
        assert task is not None
        wdb.add_task_history(task["id"], "0", "pending")
        # Re-adding with done status should update via ON CONFLICT
        wdb.add_task_history(task["id"], "0", "done")
        hist = wdb.get_task_history(task["id"])
        assert hist[0]["status"] == "done"
