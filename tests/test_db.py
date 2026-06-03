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
        """После init должны быть все 5 таблиц."""
        tables = db._list_tables()
        assert {"phases", "instructions", "checks", "evidence", "checkups"}.issubset(tables)

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
                    {"step_num": 1, "description": "Do this", "execution_type": "sync", "tool": "shell"},
                    {"step_num": 2, "description": "Do that", "execution_type": "parallel", "tool": None},
                ],
                "checks": [
                    {"description": "File exists", "command": "ls file.txt"},
                ],
                "evidence": [
                    {"description": "Screenshot of UI"},
                ],
                "checkups": [
                    {
                        "name": "Jira check",
                        "check_type": "jira_status",
                        "target": "TASK-123",
                        "interval_min": 0,
                        "last_status": "unknown",
                        "fail_action": "warn",
                    },
                ],
            },
            {
                "id": "test-2",
                "name": "Test Phase Two",
                "description": "Second test phase",
                "phase_order": 2,
                "skills": None,
                "instructions": [],
                "checks": [],
                "evidence": [],
                "checkups": [],
            },
        ]
        db.import_phases(phases)

        rows = db.get_phases()
        assert len(rows) == 2
        assert rows[0]["id"] == "test-1"
        assert rows[0]["phase_order"] == 1
        assert json.loads(rows[0]["skills"]) == ["skill-a", "skill-b"]

    def test_get_phase_detail(self, db):
        """Деталь фазы включает инструкции, checks, evidence, checkups."""
        phases = [
            {
                "id": "test-d",
                "name": "Detail Phase",
                "description": "Desc",
                "phase_order": 10,
                "skills": None,
                "instructions": [
                    {"step_num": 1, "description": "Step 1", "execution_type": "sync", "tool": None},
                ],
                "checks": [
                    {"description": "Check 1", "command": None},
                ],
                "evidence": [
                    {"description": "Evidence 1"},
                ],
                "checkups": [],
            }
        ]
        db.import_phases(phases)

        phase = db.get_phase("test-d")
        assert phase["id"] == "test-d"
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
        db.create_phase({"id": "p-1", "name": "P1", "description": "D1", "phase_order": 1, "skills": None})
        row = db.get_phase("p-1")
        assert row["name"] == "P1"

    def test_update_phase(self, db):
        db.create_phase({"id": "p-2", "name": "Old", "description": "", "phase_order": 2, "skills": None})
        db.update_phase("p-2", {"name": "New"})
        row = db.get_phase("p-2")
        assert row["name"] == "New"

    def test_delete_phase_cascades(self, db):
        db.create_phase({"id": "p-3", "name": "P3", "description": "", "phase_order": 3, "skills": None})
        db.add_instruction("p-3", {"step_num": 1, "description": "I1", "execution_type": "sync", "tool": None})
        db.delete_phase("p-3")
        assert db.get_phase("p-3") is None
        # инструкции тоже должны быть удалены
        assert db.get_phase_instructions("p-3") == []


class TestInstructionCRUD:
    def test_reorder_instructions(self, db):
        """Поменять порядок инструкций."""
        db.create_phase({"id": "p-i", "name": "I", "description": "", "phase_order": 1, "skills": None})
        db.add_instruction("p-i", {"step_num": 1, "description": "First", "execution_type": "sync", "tool": None})
        db.add_instruction("p-i", {"step_num": 2, "description": "Second", "execution_type": "parallel", "tool": None})

        # reorder: Second → первый, First → второй
        rows = db.get_phase_instructions("p-i")
        ids = [r["id"] for r in rows]
        db.reorder_instructions("p-i", ids[::-1])
        rows = db.get_phase_instructions("p-i")
        assert rows[0]["description"] == "Second"
        assert rows[0]["step_num"] == 1
        assert rows[1]["description"] == "First"
        assert rows[1]["step_num"] == 2

    def test_delete_instruction(self, db):
        db.create_phase({"id": "p-d", "name": "D", "description": "", "phase_order": 1, "skills": None})
        db.add_instruction("p-d", {"step_num": 1, "description": "To delete", "execution_type": "sync", "tool": None})
        rows = db.get_phase_instructions("p-d")
        db.delete_instruction(rows[0]["id"])
        assert len(db.get_phase_instructions("p-d")) == 0


class TestCheckupCRUD:
    def test_run_checkup(self, db):
        db.create_phase({"id": "p-c", "name": "C", "description": "", "phase_order": 1, "skills": None})
        db.add_checkup("p-c", {
            "name": "Jira check",
            "check_type": "jira_status",
            "target": "TASK-42",
            "interval_min": 0,
            "last_status": "unknown",
            "fail_action": "warn",
        })
        checkups = db.get_phase_checkups("p-c")
        assert len(checkups) == 1

        # run → обновляет статус
        db.run_checkup(checkups[0]["id"], status="ok")
        row = db.get_checkup(checkups[0]["id"])
        assert row["last_status"] == "ok"
        assert row["last_run"] is not None

    def test_get_pending(self, db):
        db.create_phase({"id": "p-p", "name": "P", "description": "", "phase_order": 2, "skills": None})
        db.add_checkup("p-p", {
            "name": "Old check",
            "check_type": "test_passed",
            "target": "pytest",
            "interval_min": 60,
            "last_status": "unknown",
            "fail_action": "warn",
        })
        # пометим как давно запущенное
        pending = db.get_pending_checkups()
        # unknown + interval_min 60 → должно вернуться
        names = [p["name"] for p in pending]
        assert "Old check" in names
