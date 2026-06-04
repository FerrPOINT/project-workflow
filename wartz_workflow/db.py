"""WorkflowDB — SQLite persistence for workflow entities.

Схема: 9 таблиц (phase_groups, agents, phases, instructions, checks, evidence, tasks, task_history, cli_history)
Плоская структура, связи через FOREIGN KEY.
PK: INTEGER AUTOINCREMENT, семантические code TEXT UNIQUE.
"""

import sqlite3
from pathlib import Path

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

    # ── Resolve helpers (code -> int) ──────────────────────────────────

    def _resolve_phase_id(self, val: int | str) -> int:
        if isinstance(val, int):
            return val
        row = self.get_phase_by_code(val)
        if not row:
            raise ValueError(f"Unknown phase code: {val}")
        return row["id"]

    def _resolve_group_id(self, val: int | str) -> int:
        if isinstance(val, int):
            return val
        row = self.get_phase_group_by_code(val)
        if not row:
            raise ValueError(f"Unknown group code: {val}")
        return row["id"]

    # ── Init ───────────────────────────────────────────────────────────

    def init(self) -> None:
        ddl = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._conn() as conn:
            conn.executescript(ddl)
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

    # ── Phase Groups ───────────────────────────────────────────────────

    def create_phase_group(self, data: dict) -> int:
        with self._conn() as conn:
            c = conn.execute(
                "INSERT INTO phase_groups (code, name, sort_order) VALUES (?, ?, ?)",
                (data.get("code", data.get("id", "")), data["name"], data.get("sort_order", 0)),
            )
            conn.commit()
            return c.lastrowid or 0

    def get_phase_groups(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM phase_groups ORDER BY sort_order").fetchall()
            return [dict(r) for r in rows]

    def get_phase_group(self, group_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM phase_groups WHERE id = ?", (group_id,)).fetchone()
            return dict(row) if row else None

    def get_phase_group_by_code(self, code: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM phase_groups WHERE code = ?", (code,)).fetchone()
            return dict(row) if row else None

    def update_phase_group(self, group_id: int | str, data: dict) -> None:
        resolved = self._resolve_group_id(group_id)
        fields = []
        vals = []
        for k, v in data.items():
            if k != "id":
                fields.append(f"{k} = ?")
                vals.append(v)
        vals.append(resolved)
        sql = f"UPDATE phase_groups SET {', '.join(fields)} WHERE id = ?"
        with self._conn() as conn:
            conn.execute(sql, vals)
            conn.commit()

    def delete_phase_group(self, group_id: int | str) -> None:
        resolved = self._resolve_group_id(group_id)
        with self._conn() as conn:
            conn.execute("DELETE FROM phase_groups WHERE id = ?", (resolved,))
            conn.commit()

    # ── Agents ─────────────────────────────────────────────────────────

    def create_agent(self, data: dict) -> int:
        with self._conn() as conn:
            c = conn.execute(
                "INSERT INTO agents (name) VALUES (?)",
                (data["name"],),
            )
            conn.commit()
            return c.lastrowid or 0

    def get_agents(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def get_agent(self, agent_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            return dict(row) if row else None

    def update_agent(self, agent_id: int, data: dict) -> None:
        fields = []
        vals = []
        for k, v in data.items():
            if k != "id":
                fields.append(f"{k} = ?")
                vals.append(v)
        vals.append(agent_id)
        sql = f"UPDATE agents SET {', '.join(fields)} WHERE id = ?"
        with self._conn() as conn:
            conn.execute(sql, vals)
            conn.commit()

    def delete_agent(self, agent_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
            conn.commit()

    # ── Import Phases (from YAML/JSON) ─────────────────────────────────

    def import_phases(self, phases: list[dict]) -> None:
        with self._conn() as conn:
            for p in phases:
                code = p.get("code", p.get("id", ""))
                conn.execute(
                    """
                    INSERT OR REPLACE INTO phases (code, name, description, min_time_min, phase_order, group_id, agent_id, next_recommendation, parallel_with, rollback_target, execution_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code,
                        p["name"],
                        p.get("description") or "",
                        p.get("min_time_min", 0),
                        p["phase_order"],
                        p.get("group_id"),
                        p.get("agent_id"),
                        p.get("next_recommendation"),
                        p.get("parallel_with"),
                        p.get("rollback_target"),
                        p.get("execution_type", "sync"),
                    ),
                )
                phase_int_id = conn.execute("SELECT id FROM phases WHERE code = ?", (code,)).fetchone()[0]
                for inst in p.get("instructions", []):
                    conn.execute(
                        """
                        INSERT INTO instructions (phase_id, step_num, description, execution_type, skills)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            phase_int_id,
                            inst["step_num"],
                            inst["description"],
                            inst.get("execution_type", "sync"),
                            inst.get("skills"),
                        ),
                    )
                for c in p.get("checks", []):
                    conn.execute(
                        "INSERT INTO checks (phase_id, description) VALUES (?, ?)",
                        (phase_int_id, c["description"]),
                    )
                for e in p.get("evidence", []):
                    conn.execute(
                        "INSERT INTO evidence (phase_id, description) VALUES (?, ?)",
                        (phase_int_id, e.get("description", e.get("item", ""))),
                    )
            conn.commit()

    # ── Read ───────────────────────────────────────────────────────────

    def get_phases(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM phases ORDER BY phase_order").fetchall()
            return [dict(r) for r in rows]

    def get_phase(self, phase_id: int | str) -> dict | None:
        with self._conn() as conn:
            if isinstance(phase_id, int):
                row = conn.execute("SELECT * FROM phases WHERE id = ?", (phase_id,)).fetchone()
            else:
                row = conn.execute("SELECT * FROM phases WHERE code = ?", (phase_id,)).fetchone()
            return dict(row) if row else None

    def get_phase_by_code(self, code: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM phases WHERE code = ?", (code,)).fetchone()
            return dict(row) if row else None

    def get_phase_instructions(self, phase_id: int | str) -> list[dict]:
        try:
            resolved = self._resolve_phase_id(phase_id)
        except ValueError:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM instructions WHERE phase_id = ? ORDER BY step_num",
                (resolved,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_phase_checks(self, phase_id: int | str) -> list[dict]:
        try:
            resolved = self._resolve_phase_id(phase_id)
        except ValueError:
            return []
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM checks WHERE phase_id = ?", (resolved,)).fetchall()
            return [dict(r) for r in rows]

    def get_phase_evidence(self, phase_id: int | str) -> list[dict]:
        try:
            resolved = self._resolve_phase_id(phase_id)
        except ValueError:
            return []
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM evidence WHERE phase_id = ?", (resolved,)).fetchall()
            return [dict(r) for r in rows]

    # ── Phase CRUD ───────────────────────────────────────────────────

    def create_phase(self, data: dict) -> int:
        """Insert a new phase row (code-based lookup)."""
        with self._conn() as conn:
            group_id = self._resolve_group_id(data["group_id"]) if data.get("group_id") else None
            c = conn.execute(
                """
                INSERT INTO phases (code, name, description, min_time_min, phase_order, group_id, agent_id,
                                    next_recommendation, parallel_with, rollback_target, execution_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data.get("code", data.get("id", "")),
                    data["name"],
                    data.get("description") or "",
                    data.get("min_time_min", 0),
                    data["phase_order"],
                    group_id,
                    data.get("agent_id"),
                    data.get("next_recommendation"),
                    data.get("parallel_with"),
                    data.get("rollback_target"),
                    data.get("execution_type", "sync"),
                ),
            )
            conn.commit()
            return c.lastrowid or 0

    def update_phase(self, phase_id: int | str, data: dict) -> None:
        resolved = self._resolve_phase_id(phase_id)
        fields = []
        vals = []
        for k, v in data.items():
            if k != "id":
                fields.append(f"{k} = ?")
                vals.append(v)
        vals.append(resolved)
        sql = f"UPDATE phases SET {', '.join(fields)} WHERE id = ?"
        with self._conn() as conn:
            conn.execute(sql, vals)
            conn.commit()

    def delete_phase(self, phase_id: int | str) -> None:
        resolved = self._resolve_phase_id(phase_id)
        with self._conn() as conn:
            conn.execute("DELETE FROM phases WHERE id = ?", (resolved,))
            conn.commit()

    # ── Instruction CRUD ─────────────────────────────────────────────

    def create_instruction(self, data: dict) -> int:
        resolved = self._resolve_phase_id(data["phase_id"])
        with self._conn() as conn:
            c = conn.execute(
                """
                INSERT INTO instructions (phase_id, step_num, description, execution_type, skills)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    resolved,
                    data["step_num"],
                    data["description"],
                    data.get("execution_type", "sync"),
                    data.get("skills"),
                ),
            )
            conn.commit()
            return c.lastrowid

    def update_instruction(self, inst_id: int, data: dict) -> None:
        with self._conn() as conn:
            fields = []
            vals = []
            for k, v in data.items():
                if k != "id":
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

    def reorder_instructions(self, phase_id: int | str, ids: list[int]) -> None:
        resolved = self._resolve_phase_id(phase_id)
        with self._conn() as conn:
            for temp_num, inst_id in enumerate(ids, 1):
                conn.execute(
                    "UPDATE instructions SET step_num = -? WHERE id = ? AND phase_id = ?",
                    (temp_num, inst_id, resolved),
                )
            for new_num, inst_id in enumerate(ids, 1):
                conn.execute(
                    "UPDATE instructions SET step_num = ? WHERE id = ? AND phase_id = ?",
                    (new_num, inst_id, resolved),
                )
            conn.commit()

    # ── Check CRUD ───────────────────────────────────────────────────

    def create_check(self, data: dict) -> int:
        resolved = self._resolve_phase_id(data["phase_id"])
        with self._conn() as conn:
            c = conn.execute(
                "INSERT INTO checks (phase_id, description) VALUES (?, ?)",
                (resolved, data["description"]),
            )
            conn.commit()
            return c.lastrowid

    def update_check(self, check_id: int, data: dict) -> None:
        with self._conn() as conn:
            fields = []
            vals = []
            for k, v in data.items():
                if k != "id":
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
        resolved = self._resolve_phase_id(data["phase_id"])
        with self._conn() as conn:
            c = conn.execute(
                "INSERT INTO evidence (phase_id, description) VALUES (?, ?)",
                (resolved, data["description"]),
            )
            conn.commit()
            return c.lastrowid

    def update_evidence(self, ev_id: int, data: dict) -> None:
        with self._conn() as conn:
            fields = []
            vals = []
            for k, v in data.items():
                if k != "id":
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

    # ── Task CRUD ────────────────────────────────────────────────────

    def create_task(self, data: dict) -> int:
        with self._conn() as conn:
            c = conn.execute(
                """
                INSERT INTO tasks (task_key, title, description, current_phase, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    data["task_key"],
                    data.get("title", ""),
                    data.get("description", ""),
                    data.get("current_phase", -1),
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

    def get_task_by_key(self, task_key: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_key = ?", (task_key,)).fetchone()
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

    # ── Task History ─────────────────────────────────────────────────

    def add_task_history(self, task_id: int, phase_id: int | str, status: str = "pending") -> None:
        resolved = self._resolve_phase_id(phase_id)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_history (task_id, phase_id, status, completed_at)
                VALUES (?, ?, ?, CASE WHEN ? = 'done' THEN CURRENT_TIMESTAMP ELSE NULL END)
                """,
                (task_id, resolved, status, status),
            )
            conn.commit()

    def get_task_history(self, task_id: int) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM task_history WHERE task_id = ? ORDER BY completed_at",
                (task_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def add_task_phase(self, task_id: int, phase_id: int | str, status: str = "pending") -> None:
        return self.add_task_history(task_id, phase_id, status)

    def get_task_phases(self, task_id: int) -> list[dict]:
        return self.get_task_history(task_id)

    # ── CLI History ──────────────────────────────────────────────────

    def log_cli_call(self, command: str, task_key: str | None, request: str | None, response: str | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO cli_history (command, task_key, request, response) VALUES (?, ?, ?, ?)",
                (command, task_key, request, response),
            )
            conn.commit()

    def get_cli_history(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM cli_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Batch Operations ─────────────────────────────────────────────

    def batch_update_orders(self, batch: list[tuple[int | str, int]]) -> None:
        resolved_batch = [(order, self._resolve_phase_id(pid)) for pid, order in batch]
        with self._conn() as conn:
            conn.executemany(
                "UPDATE phases SET phase_order = ? WHERE id = ?",
                resolved_batch,
            )
            conn.commit()

    def update_phase_order(self, phase_id: int | str, new_order: int) -> None:
        resolved = self._resolve_phase_id(phase_id)
        with self._conn() as conn:
            conn.execute("UPDATE phases SET phase_order = ? WHERE id = ?", (new_order, resolved))
            conn.commit()

    def update_phase_group_assignment(self, phase_id: int | str, group_id: int | str | None) -> None:
        resolved_phase = self._resolve_phase_id(phase_id)
        resolved_group = self._resolve_group_id(group_id) if group_id is not None else None
        with self._conn() as conn:
            conn.execute("UPDATE phases SET group_id = ? WHERE id = ?", (resolved_group, resolved_phase))
            conn.commit()

    # ── Group Order Batch ─────────────────────────────────────────────

    def batch_update_group_orders(self, batch: list[tuple[int | str, int]]) -> None:
        resolved_batch = [(order, self._resolve_group_id(gid)) for gid, order in batch]
        with self._conn() as conn:
            conn.executemany(
                "UPDATE phase_groups SET sort_order = ? WHERE id = ?",
                resolved_batch,
            )
            conn.commit()

    # ── Seed Defaults ──────────────────────────────────────────────────

    def seed_default_groups(self) -> None:
        defaults = [
            ("setup", "🔧 Setup", 1),
            ("research", "🔬 Research", 2),
            ("plan", "📋 Plan", 3),
            ("dev", "💻 Dev", 4),
            ("qa", "🧪 QA", 5),
            ("closure", "🏁 Closure", 6),
        ]
        with self._conn() as conn:
            for code, name, order in defaults:
                conn.execute(
                    "INSERT OR IGNORE INTO phase_groups (code, name, sort_order) VALUES (?, ?, ?)",
                    (code, name, order),
                )
            conn.commit()

    # ── Alias helpers for UI back-compat ──────────────────────────────

    def get_questions(self, phase_id: int | str) -> list[dict]:
        """Return empty list (questions removed from schema)."""
        return []

    def get_instructions(self, phase_id: int | str) -> list[dict]:
        return self.get_phase_instructions(phase_id)

    def get_checks(self, phase_id: int | str) -> list[dict]:
        return self.get_phase_checks(phase_id)

    def get_evidence(self, phase_id: int | str) -> list[dict]:
        return self.get_phase_evidence(phase_id)
