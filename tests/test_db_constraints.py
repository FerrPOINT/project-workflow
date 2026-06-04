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
    # base phase
    c.execute("INSERT INTO phases (id, name, phase_order) VALUES (?, ?, ?)", ("0", "Base", 0))
    c.commit()
    return c


class TestCheckConstraints:
    def test_phase_bad_execution_type_blocked(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO phases (id,name,phase_order,execution_type) VALUES (?,?,?,?)",
                ("bad", "Bad", 1, "invalid")
            )

    def test_task_bad_status_blocked(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks (task_key,status) VALUES (?,?)",
                ("T-1", "garbage")
            )

    def test_history_bad_status_blocked(self, conn):
        conn.execute("INSERT INTO tasks (task_key,status) VALUES (?,?)", ("T-ok", "active"))
        tid = conn.execute("SELECT id FROM tasks WHERE task_key=?", ("T-ok",)).fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO task_history (task_id,phase_id,status) VALUES (?,?,?)",
                (tid, "0", "garbage")
            )

    def test_instr_bad_execution_type_blocked(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO instructions (phase_id,step_num,description,execution_type) VALUES (?,?,?,?)",
                ("0", 1, "S", "garbage")
            )

    def test_null_task_key_blocked(self, conn):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO tasks (task_key) VALUES (?)",
                (None,)
            )

    def test_valid_execution_types_accepted(self, conn):
        conn.execute("INSERT INTO phases (id,name,phase_order,execution_type) VALUES (?,?,?,?)",
                     ("ok1", "Ok", 1, "sync"))
        conn.execute("INSERT INTO phases (id,name,phase_order,execution_type) VALUES (?,?,?,?)",
                     ("ok2", "Ok2", 2, "parallel"))

    def test_valid_status_accepted(self, conn):
        for st in ("active", "done", "blocked"):
            conn.execute("INSERT INTO tasks (task_key,status) VALUES (?,?)", (f"TK-{st}", st))
        # task_history uses pending|done
        conn.execute("INSERT INTO tasks (task_key,status) VALUES (?,?)", ("T-history", "active"))
        tid = conn.execute("SELECT id FROM tasks WHERE task_key=?", ("T-history",)).fetchone()[0]
        for st in ("pending", "done"):
            conn.execute(
                "INSERT INTO task_history (task_id,phase_id,status) VALUES (?,?,?)",
                (tid, str(st) or "0", st)
            )

    def test_null_skills_accepted(self, conn):
        conn.execute(
            "INSERT INTO instructions (phase_id,step_num,description,execution_type,skills) VALUES (?,?,?,?,?)",
            ("0", 99, "S", "sync", None)
        )
        row = conn.execute("SELECT skills FROM instructions WHERE step_num=?", (99,)).fetchone()
        assert row[0] is None

    def test_json_skills_accepted(self, conn):
        conn.execute(
            "INSERT INTO instructions (phase_id,step_num,description,execution_type,skills) VALUES (?,?,?,?,?)",
            ("0", 100, "S", "sync", '["python", "git"]')
        )
        row = conn.execute("SELECT skills FROM instructions WHERE step_num=?", (100,)).fetchone()
        assert row[0] == '["python", "git"]'

    def test_unique_task_key_blocked(self, conn):
        conn.execute("INSERT INTO tasks (task_key) VALUES (?)", ("ABC-1",))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks (task_key) VALUES (?)", ("ABC-1",))

    def test_cascade_delete_phase_clears_instructions(self, conn):
        conn.execute("INSERT INTO instructions (phase_id,step_num,description) VALUES (?,?,?)",
                     ("0", 1, "I1"))
        conn.execute("DELETE FROM phases WHERE id=?", ("0",))
        rows = conn.execute("SELECT * FROM instructions WHERE phase_id=?", ("0",)).fetchall()
        assert len(rows) == 0

    def test_cascade_delete_task_clears_history(self, conn):
        conn.execute("INSERT INTO tasks (task_key) VALUES (?)", ("DDD-1",))
        tid = conn.execute("SELECT id FROM tasks WHERE task_key=?", ("DDD-1",)).fetchone()[0]
        conn.execute("INSERT INTO task_history (task_id,phase_id) VALUES (?,?)", (tid, "0"))
        conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
        rows = conn.execute("SELECT * FROM task_history WHERE task_id=?", (tid,)).fetchall()
        assert len(rows) == 0
