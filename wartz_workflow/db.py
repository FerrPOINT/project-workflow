"""WorkflowDB — SQLite persistence for phases, instructions, checks, evidence.

Схема: 4 таблицы + tasks/task_phases. Всё остальное удалено.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path.home() / ".wartz-workflow" / "workflow.db"

SCHEMA_PATH = Path(__file__).parent / "db_schema.sql"


class WorkflowDB:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DB_PATH)
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    # ── Init ───────────────────────────────────────────────────────────

    def init(self) -> None:
        ddl = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._conn() as conn:
            conn.executescript(ddl)
            self._migrate(conn)
            conn.commit()

    def _list_tables(self) -> set[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            return {r["name"] for r in rows}

    def is_empty(self) -> bool:
        with self._conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM phases").fetchone()[0]
            return count == 0

    def import_phases(self, phases: list[dict]) -> None:
        with self._conn() as conn:
            for p in phases:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO phases (
                        id, name, description, phase_order, skills,
                        delegate_agent, delegate_timeout, delegate_max_cycles, delegate_toolsets,
                        parallel_with, rollback_target, next_recommendation
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        p["id"],
                        p["name"],
                        p.get("description") or "",
                        p["phase_order"],
                        p.get("skills"),
                        p.get("delegate_agent"),
                        p.get("delegate_timeout"),
                        p.get("delegate_max_cycles"),
                        p.get("delegate_toolsets"),
                        p.get("parallel_with"),
                        p.get("rollback_target"),
                        p.get("next_recommendation"),
                    ),
                )
                for inst in p.get("instructions", []):
                    conn.execute(
                        """
                        INSERT INTO instructions (phase_id, step_num, description, execution_type, tool)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            p["id"],
                            inst["step_num"],
                            inst["description"],
                            inst.get("execution_type", "sync"),
                            inst.get("tool"),
                        ),
                    )
                for c in p.get("checks", []):
                    conn.execute(
                        """
                        INSERT INTO checks (phase_id, description, command)
                        VALUES (?, ?, ?)
                        """,
                        (p["id"], c["description"], c.get("command")),
                    )
                for e in p.get("evidence", []):
                    conn.execute(
                        """
                        INSERT INTO evidence (phase_id, description, validator)
                        VALUES (?, ?, ?)
                        """,
                        (p["id"], e.get("description", e.get("item", "")), e.get("validator")),
                    )
            conn.commit()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Добавить колонки которых не хватает (idempotent)."""
        for column, ctype in [
            ("delegate_agent", "TEXT"),
            ("delegate_timeout", "INTEGER DEFAULT 30"),
            ("delegate_max_cycles", "INTEGER DEFAULT 3"),
            ("delegate_toolsets", "TEXT"),
            ("parallel_with", "TEXT"),
            ("rollback_target", "TEXT"),
            ("next_recommendation", "TEXT"),
            ("group_id", "TEXT DEFAULT 'setup'"),
        ]:
            try:
                conn.execute(f"ALTER TABLE phases ADD COLUMN {column} {ctype}")
            except sqlite3.OperationalError:
                pass

    # ── Read ───────────────────────────────────────────────────────────

    def get_phases(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM phases ORDER BY phase_order").fetchall()
            return [dict(r) for r in rows]

    def get_phase(self, phase_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM phases WHERE id = ?", (phase_id,)).fetchone()
            return dict(row) if row else None

    def get_phase_instructions(self, phase_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM instructions WHERE phase_id = ? ORDER BY step_num",
                (phase_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_phase_checks(self, phase_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM checks WHERE phase_id = ?", (phase_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_phase_evidence(self, phase_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM evidence WHERE phase_id = ?", (phase_id,)).fetchall()
            return [dict(r) for r in rows]

    # ── Phase CRUD ───────────────────────────────────────────────────

    def create_phase(self, data: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO phases (id, name, description, phase_order, skills)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    data["id"],
                    data["name"],
                    data.get("description") or "",
                    data["phase_order"],
                    data.get("skills"),
                ),
            )
            conn.commit()

    def update_phase(self, phase_id: str, data: dict) -> None:
        fields = []
        vals = []
        for k, v in data.items():
            fields.append(f"{k} = ?")
            vals.append(v)
        vals.append(phase_id)
        sql = f"UPDATE phases SET {', '.join(fields)} WHERE id = ?"
        with self._conn() as conn:
            conn.execute(sql, vals)
            conn.commit()

    def delete_phase(self, phase_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM phases WHERE id = ?", (phase_id,))
            conn.commit()

    # ── Instruction CRUD ─────────────────────────────────────────────

    def create_instruction(self, data: dict) -> int:
        with self._conn() as conn:
            c = conn.execute(
                """
                INSERT INTO instructions (phase_id, step_num, description, execution_type, tool)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    data["phase_id"],
                    data["step_num"],
                    data["description"],
                    data.get("execution_type", "sync"),
                    data.get("tool"),
                ),
            )
            conn.commit()
            return c.lastrowid

    def update_instruction(self, inst_id: int, data: dict) -> None:
        with self._conn() as conn:
            fields = []
            vals = []
            for k, v in data.items():
                fields.append(f"{k} = ?")
                vals.append(v)
            vals.append(inst_id)
            sql = f"UPDATE instructions SET {', '.join(fields)} WHERE id = ?"
            conn.execute(sql, vals)
            conn.commit()

    def delete_instruction(self, inst_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM instructions WHERE id = ?", (inst_id,))
            conn.commit()

    def reorder_instructions(self, phase_id: str, ids: list[int]) -> None:
        with self._conn() as conn:
            for temp_num, inst_id in enumerate(ids, 1):
                conn.execute(
                    "UPDATE instructions SET step_num = -? WHERE id = ? AND phase_id = ?",
                    (temp_num, inst_id, phase_id),
                )
            for new_num, inst_id in enumerate(ids, 1):
                conn.execute(
                    "UPDATE instructions SET step_num = ? WHERE id = ? AND phase_id = ?",
                    (new_num, inst_id, phase_id),
                )
            conn.commit()

    # ── Check CRUD ───────────────────────────────────────────────────

    def create_check(self, data: dict) -> int:
        with self._conn() as conn:
            c = conn.execute(
                """
                INSERT INTO checks (phase_id, description, command)
                VALUES (?, ?, ?)
                """,
                (data["phase_id"], data["description"], data.get("command")),
            )
            conn.commit()
            return c.lastrowid

    def update_check(self, check_id: int, data: dict) -> None:
        with self._conn() as conn:
            fields = []
            vals = []
            for k, v in data.items():
                fields.append(f"{k} = ?")
                vals.append(v)
            vals.append(check_id)
            sql = f"UPDATE checks SET {', '.join(fields)} WHERE id = ?"
            conn.execute(sql, vals)
            conn.commit()

    def delete_check(self, check_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM checks WHERE id = ?", (check_id,))
            conn.commit()

    # ── Evidence CRUD ────────────────────────────────────────────────

    def create_evidence(self, data: dict) -> int:
        with self._conn() as conn:
            c = conn.execute(
                """
                INSERT INTO evidence (phase_id, description)
                VALUES (?, ?)
                """,
                (data["phase_id"], data["description"]),
            )
            conn.commit()
            return c.lastrowid

    def update_evidence(self, ev_id: int, data: dict) -> None:
        with self._conn() as conn:
            fields = []
            vals = []
            for k, v in data.items():
                fields.append(f"{k} = ?")
                vals.append(v)
            vals.append(ev_id)
            sql = f"UPDATE evidence SET {', '.join(fields)} WHERE id = ?"
            conn.execute(sql, vals)
            conn.commit()

    def delete_evidence(self, ev_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM evidence WHERE id = ?", (ev_id,))
            conn.commit()

    # ── Aliases (backward compat) ─────────────────────────────────────
    def add_instruction(self, phase_id: str, data: dict) -> None:
        return self.create_instruction({"phase_id": phase_id, **data})

    def add_check(self, phase_id: str, data: dict) -> None:
        return self.create_check({"phase_id": phase_id, **data})

    def add_evidence(self, phase_id: str, data: dict) -> None:
        return self.create_evidence({"phase_id": phase_id, **data})

    get_instructions = get_phase_instructions
    get_checks       = get_phase_checks
    get_evidence     = get_phase_evidence

    # ── Task CRUD ──────────────────────────────────────────────────────

    def create_task(self, data: dict) -> int:
        with self._conn() as conn:
            c = conn.execute(
                """
                INSERT INTO tasks (jira_key, title, description, current_phase, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    data["jira_key"],
                    data.get("title", ""),
                    data.get("description", ""),
                    data.get("current_phase", "-1"),
                    data.get("status", "active"),
                ),
            )
            conn.commit()
            return c.lastrowid or 0

    def get_tasks(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC").fetchall()
            return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    def get_task_by_jira(self, jira_key: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE jira_key = ?", (jira_key,)).fetchone()
            return dict(row) if row else None

    def update_task(self, task_id: int, data: dict) -> None:
        fields = []
        vals = []
        for k, v in data.items():
            fields.append(f"{k} = ?")
            vals.append(v)
        vals.append(task_id)
        sql = f"UPDATE tasks SET {', '.join(fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
        with self._conn() as conn:
            conn.execute(sql, vals)
            conn.commit()

    def delete_task(self, task_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()

    def add_task_phase(self, task_id: int, phase_id: str, status: str = "pending") -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_phases (task_id, phase_id, status, completed_at)
                VALUES (?, ?, ?, CASE WHEN ? = 'done' THEN CURRENT_TIMESTAMP ELSE NULL END)
                """,
                (task_id, phase_id, status, status),
            )
            conn.commit()

    def get_task_phases(self, task_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM task_phases WHERE task_id = ? ORDER BY completed_at",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def batch_update_orders(self, batch: list[tuple[str, int]]) -> None:
        """Массовое обновление phase_order (drag-and-drop Kanban)."""
        with self._conn() as conn:
            conn.executemany(
                "UPDATE phases SET phase_order = ? WHERE id = ?",
                [(order, pid) for pid, order in batch],
            )
            conn.commit()

    def update_phase_order(self, phase_id: str, new_order: int) -> None:
        """Обновить порядок одной фазы."""
        with self._conn() as conn:
            conn.execute("UPDATE phases SET phase_order = ? WHERE id = ?", (new_order, phase_id))
            conn.commit()

    def get_questions(self, phase_id: str) -> list[dict]:
        """Legacy stub — questions удалены из БД."""
        return []

    def get_checkups(self, phase_id: str) -> list[dict]:
        """Legacy stub — checkups удалены из БД."""
        return []

    def run_checkup(self, checkup_id: int, status: str = "") -> None:
        pass

    def get_checkup(self, checkup_id: int) -> dict | None:
        return None

    def get_pending_checkups(self) -> list[dict]:
        return []

    def seed_default_groups(self) -> None:
        """Seed default phase groups if table existed. Legacy stub."""
        pass

    def get_phase_groups(self) -> list[dict]:
        """Legacy stub — phase_groups удалены из БД."""
        return []

    def get_phase_group(self, group_id: str) -> dict | None:
        return None

    def create_group(self, data: dict) -> int:
        return 0

    def create_phase_group(self, data: dict) -> None:
        pass

    def delete_group(self, group_id: str) -> None:
        pass

    def delete_group_by_id(self, group_id: str) -> None:
        pass

    def delete_phase_group(self, group_id: str) -> None:
        pass

    def update_group(self, group_id: str, data: dict) -> None:
        pass

    def update_phase_group(self, group_id: str, data: dict) -> None:
        pass

    def batch_update_group_orders(self, batch: list[tuple[str, int]]) -> None:
        pass

    def assign_phase_group(self, phase_id: str, group_id: str) -> None:
        pass

    def update_phase_group_assignment(self, phase_id: str, group_id: str) -> None:
        pass

    def update_groups_order(self, ordered_ids: list[str]) -> None:
        pass

    def batch_update_groups(self, group_map: dict[str, str]) -> None:
        pass

    def update_phase_parallel(self, phase_id: str, target: str | None) -> None:
        pass

