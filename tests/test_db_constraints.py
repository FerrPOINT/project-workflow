"""Test DB CHECK constraints + edge cases for task_key, skills, status."""

from pathlib import Path
import sqlite3
import pytest

from wartz_workflow.db import WorkflowDB


@pytest.fixture
def conn(tmp_path):
    """Fresh DB with schema applied, returns sqlite3.Connection."""
    db_path = tmp_path / "test_constraints.db"
    c = sqlite3.connect(str(db_path))
    # apply schema
    schema_sql = Path(__file__).parent.parent / "wartz_workflow" / "db_schema.sql"
    c.executescript(schema_sql.read_text())
    c.execute("PRAGMA foreign_keys = ON")
    c.execute(
        "INSERT INTO workflows (code, name, description) VALUES (?, ?, ?)",
        ("default", "Default Workflow", "Constraint test workflow"),
    )
    # base phase
    c.execute(
        "INSERT INTO phases (workflow_id, code, name, phase_order) VALUES (?, ?, ?, ?)",
        (1, "0", "Base", 0),
    )
    c.execute(
        "INSERT INTO projects (workflow_id, code, name, key_patterns) VALUES (?, ?, ?, ?)",
        (1, "TEST", "Test Project", '["^(?P<prefix>TEST)-(?P<number>[0-9]+)$"]')
    )
    c.commit()
    return c


class TestCheckConstraints:
    def test_phase_bad_execution_type_blocked(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO phases (workflow_id,code,name,phase_order,execution_type) VALUES (?,?,?,?,?)",
                (1, "bad", "Bad", 1, "invalid")
            )

    def test_task_bad_status_blocked(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks (project_id, task_key, status) VALUES (?,?,?)",
                (1, "T-1", "garbage")
            )

    def test_history_bad_status_blocked(self, conn):
        conn.execute("INSERT INTO tasks (project_id, task_key, status) VALUES (?,?,?)", (1, "T-ok", "active"))
        tid = conn.execute("SELECT id FROM tasks WHERE task_key=?", ("T-ok",)).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO task_history (task_id,phase_id,status) VALUES (?,?,?)",
                (tid, 1, "garbage")
            )

    def test_instr_bad_execution_type_blocked(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO instructions (phase_id,step_num,description,execution_type) VALUES (?,?,?,?)",
                (1, 1, "S", "garbage")
            )

    def test_null_task_key_blocked(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks (project_id, task_key) VALUES (?, ?)",
                (1, None)
            )

    def test_null_project_id_blocked(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks (project_id, task_key) VALUES (?, ?)",
                (None, "TEST-1")
            )

    def test_unknown_project_id_blocked(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks (project_id, task_key) VALUES (?, ?)",
                (999, "TEST-2")
            )

    def test_valid_execution_types_accepted(self, conn):
        conn.execute("INSERT INTO phases (workflow_id,code,name,phase_order,execution_type) VALUES (?,?,?,?,?)",
                     (1, "ok1", "Ok", 1, "sync"))
        conn.execute("INSERT INTO phases (workflow_id,code,name,phase_order,execution_type) VALUES (?,?,?,?,?)",
                     (1, "ok2", "Ok2", 2, "parallel"))

    def test_valid_status_accepted(self, conn):
        for st in ("active", "done", "blocked"):
            conn.execute("INSERT INTO tasks (project_id, task_key, status) VALUES (?,?,?)", (1, f"TK-{st}", st))
        # task_history uses pending|done — use separate phases for each status (UNIQUE on task_id+phase_id)
        conn.execute("INSERT INTO tasks (project_id, task_key, status) VALUES (?,?,?)", (1, "T-history", "active"))
        tid = conn.execute("SELECT id FROM tasks WHERE task_key=?", ("T-history",)).fetchone()[0]
        for i, st in enumerate(("pending", "done")):
            conn.execute("INSERT INTO phases (workflow_id,code,name,phase_order) VALUES (?,?,?,?)", (1, f"ph-{i}", "H", i+10))
            pid = conn.execute("SELECT id FROM phases WHERE code=?", (f"ph-{i}",)).fetchone()[0]
            conn.execute(
                "INSERT INTO task_history (task_id,phase_id,status) VALUES (?,?,?)",
                (tid, pid, st)
            )

    def test_null_skills_accepted(self, conn):
        conn.execute(
            "INSERT INTO instructions (phase_id,step_num,description,execution_type,skills) VALUES (?,?,?,?,?)",
            (1, 99, "S", "sync", None)
        )
        row = conn.execute("SELECT skills FROM instructions WHERE step_num=?", (99,)).fetchone()
        assert row[0] is None

    def test_json_skills_accepted(self, conn):
        conn.execute(
            "INSERT INTO instructions (phase_id,step_num,description,execution_type,skills) VALUES (?,?,?,?,?)",
            (1, 100, "S", "sync", '["python", "git"]')
        )
        row = conn.execute("SELECT skills FROM instructions WHERE step_num=?", (100,)).fetchone()
        assert row[0] == '["python", "git"]'

    def test_unique_task_key_blocked(self, conn):
        conn.execute("INSERT INTO tasks (project_id, task_key) VALUES (?, ?) ", (1, "ABC-1"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks (project_id, task_key) VALUES (?, ?)", (1, "ABC-1"))

    def test_cascade_delete_phase_clears_instructions(self, conn):
        conn.execute("INSERT INTO instructions (phase_id,step_num,description) VALUES (?,?,?)",
                     (1, 1, "I1"))
        conn.execute("DELETE FROM phases WHERE id=?", (1,))
        rows = conn.execute("SELECT * FROM instructions WHERE phase_id=?", (1,)).fetchall()
        assert len(rows) == 0

    def test_cascade_delete_task_clears_history(self, conn):
        conn.execute("INSERT INTO tasks (project_id, task_key) VALUES (?, ?)", (1, "DDD-1"))
        tid = conn.execute("SELECT id FROM tasks WHERE task_key=?", ("DDD-1",)).fetchone()[0]
        conn.execute("INSERT INTO task_history (task_id,phase_id) VALUES (?,?)", (tid, 1))
        conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
        rows = conn.execute("SELECT * FROM task_history WHERE task_id=?", (tid,)).fetchall()
        assert len(rows) == 0
