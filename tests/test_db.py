"""Tests for WorkflowDB — SQLite persistence."""

import json
import os
import sqlite3
from pathlib import Path

import pytest

from wartz_workflow.db import WorkflowDB, DB_PATH


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Чистая БД для каждого теста."""
    test_db = tmp_path / "test_workflow.db"
    monkeypatch.setattr("wartz_workflow.db.DB_PATH", test_db)
    db = WorkflowDB(str(test_db))
    db.init()
    return db


class TestInit:
    def test_creates_all_tables(self, db):
        """После init должны быть все таблицы."""
        tables = db._list_tables()
        assert {
            "phases", "instructions", "checks", "evidence",
            "tasks", "task_history", "phase_groups", "agents", "cli_history"
        }.issubset(tables)

    def test_init_idempotent(self, db):
        """Повторный init не падает."""
        db.init()  # второй раз
        tables = db._list_tables()
        assert {"phases", "instructions"}.issubset(tables)


class TestImportPhases:
    def test_imports_phases(self, db):
        """Импорт 2 фаз из dict."""
        phases = [
            {
                "id": "test-1",
                "name": "Test Phase One",
                "description": "First test phase",
                "phase_order": 1,
                "skills": json.dumps(["skill-a", "skill-b"]),
                "instructions": [
                    {"step_num": 1, "description": "Do this", "execution_type": "sync", "skills": json.dumps(["skill-a", "skill-b"])},
                    {"step_num": 2, "description": "Do that", "execution_type": "parallel"},
                ],
                "checks": [
                    {"description": "File exists"},
                ],
                "evidence": [
                    {"description": "Screenshot of UI"},
                ],
            },
            {
                "id": "test-2",
                "name": "Test Phase Two",
                "description": "Second test phase",
                "phase_order": 2,
                "instructions": [
                    {"step_num": 1, "description": "Finish it", "execution_type": "sync"}
                ],
            },
        ]
        db.import_phases(phases)
        rows = db.get_phases()
        assert len(rows) == 2
        assert rows[0]["code"] == "test-1"
        assert rows[0]["phase_order"] == 1

    def test_get_phase_detail(self, db):
        """Деталь фазы включает инструкции, checks, evidence."""
        phases = [
            {
                "id": "test-d",
                "name": "Detail Phase",
                "description": "Desc",
                "phase_order": 10,
                "instructions": [
                    {"step_num": 1, "description": "Step 1", "execution_type": "sync"},
                ],
                "checks": [
                    {"description": "Check 1"},
                ],
                "evidence": [
                    {"description": "Evidence 1"},
                ],
            }
        ]
        db.import_phases(phases)

        phase = db.get_phase("test-d")
        assert phase["code"] == "test-d"
        assert phase["name"] == "Detail Phase"
        instructions = db.get_phase_instructions("test-d")
        assert len(instructions) == 1
        assert instructions[0]["description"] == "Step 1"
        assert instructions[0]["execution_type"] == "sync"

        checks = db.get_phase_checks("test-d")
        assert len(checks) == 1
        assert checks[0]["description"] == "Check 1"

        evidence = db.get_phase_evidence("test-d")
        assert len(evidence) == 1
        assert evidence[0]["description"] == "Evidence 1"


class TestPhaseCRUD:
    def test_create_phase(self, db):
        db.create_phase({"id": "p-1", "name": "P1", "description": "D1", "phase_order": 1})
        row = db.get_phase("p-1")
        assert row["name"] == "P1"

    def test_update_phase(self, db):
        db.create_phase({"id": "p-2", "name": "Old", "description": "", "phase_order": 2})
        db.update_phase("p-2", {"name": "New", "description": "Updated"})
        row = db.get_phase("p-2")
        assert row["name"] == "New"
        assert row["description"] == "Updated"

    def test_delete_phase_cascades(self, db):
        db.create_phase({"id": "p-3", "name": "P3", "description": "", "phase_order": 3})
        iid = db.create_instruction({"phase_id": "p-3", "step_num": 1, "description": "I1", "execution_type": "sync"})
        db.delete_phase("p-3")
        assert db.get_phase("p-3") is None
        assert db.get_phase_instructions("p-3") == []


class TestInstructionCRUD:
    def test_reorder_instructions(self, db):
        db.create_phase({"id": "p-i", "name": "I", "description": "", "phase_order": 1})
        db.create_instruction({"phase_id": "p-i", "step_num": 1, "description": "First", "execution_type": "sync"})
        db.create_instruction({"phase_id": "p-i", "step_num": 2, "description": "Second", "execution_type": "parallel"})
        rows = db.get_phase_instructions("p-i")
        ids = [r["id"] for r in rows]
        db.reorder_instructions("p-i", ids[::-1])
        rows = db.get_phase_instructions("p-i")
        assert rows[0]["description"] == "Second"
        assert rows[0]["step_num"] == 1
        assert rows[1]["description"] == "First"
        assert rows[1]["step_num"] == 2

    def test_delete_instruction(self, db):
        db.create_phase({"id": "p-d", "name": "D", "description": "", "phase_order": 1})
        iid = db.create_instruction({"phase_id": "p-d", "step_num": 1, "description": "To delete", "execution_type": "sync"})
        db.delete_instruction(iid)
        assert len(db.get_phase_instructions("p-d")) == 0


class TestTaskCRUD:
    def test_create_and_get_task(self, db):
        db.create_task({"task_key": "AAT-1", "title": "T1", "current_phase": "-1"})
        t = db.get_task_by_key("AAT-1")
        assert t is not None
        assert t["task_key"] == "AAT-1"

    def test_update_task(self, db):
        db.create_task({"task_key": "AAT-2", "title": "Old", "current_phase": "-1"})
        t = db.get_task_by_key("AAT-2")
        db.update_task(t["id"], {"title": "New"})
        t2 = db.get_task_by_key("AAT-2")
        assert t2["title"] == "New"

    def test_task_history(self, db):
        # Seed phases so that task_history FK resolves
        db.create_phase({"id": "0", "name": "P0", "description": "", "phase_order": 1})
        db.create_phase({"id": "1", "name": "P1", "description": "", "phase_order": 2})
        db.create_task({"task_key": "AAT-3", "title": "T3", "current_phase": "-1"})
        t = db.get_task_by_key("AAT-3")
        db.add_task_history(t["id"], "0", "done")
        db.add_task_history(t["id"], "1", "pending")
        history = db.get_task_history(t["id"])
        assert len(history) == 2
        pmap = {p["phase_id"]: p["status"] for p in history}
        # phase_id is now int, so lookup int IDs from created phases
        p0 = db.get_phase_by_code("0")
        p1 = db.get_phase_by_code("1")
        assert pmap[p0["id"]] == "done"
        assert pmap[p1["id"]] == "pending"


class TestPhaseGroupCRUD:
    def test_create_and_get(self, db):
        gid = db.create_phase_group({"code": "prep", "name": "Подготовка", "sort_order": 1})
        g = db.get_phase_group(gid)
        assert g["name"] == "Подготовка"
        assert g["sort_order"] == 1

    def test_list_ordered(self, db):
        db.create_phase_group({"code": "z", "name": "ZZ", "sort_order": 2})
        db.create_phase_group({"code": "a", "name": "AA", "sort_order": 1})
        groups = db.get_phase_groups()
        assert [g["code"] for g in groups] == ["a", "z"]

    def test_update_and_delete(self, db):
        gid = db.create_phase_group({"code": "upd", "name": "Old", "sort_order": 1})
        db.update_phase_group(gid, {"name": "New"})
        assert db.get_phase_group(gid)["name"] == "New"
        db.delete_phase_group(gid)
        assert db.get_phase_group(gid) is None


class TestAgentCRUD:
    def test_create_and_get(self, db):
        aid = db.create_agent({"name": "coder"})
        a = db.get_agent(aid)
        assert a["name"] == "coder"

    def test_list(self, db):
        db.create_agent({"name": "critic"})
        db.create_agent({"name": "coder"})
        agents = db.get_agents()
        assert len(agents) == 2

    def test_update_and_delete(self, db):
        aid = db.create_agent({"name": "Old"})
        db.update_agent(aid, {"name": "New"})
        assert db.get_agent(aid)["name"] == "New"
        db.delete_agent(aid)
        assert db.get_agent(aid) is None


class TestCliHistory:
    def test_log_and_get(self, db):
        db.log_cli_call("step", "AAT-5", '{"report": "done"}', '{"next_phase": "1"}')
        db.log_cli_call("history", "AAT-5", None, None)
        rows = db.get_cli_history()
        assert len(rows) == 2
        cmds = {r["command"] for r in rows}
        assert cmds == {"step", "history"}
