"""WorkflowDB — SQLite persistence for phases, instructions, checks, evidence, checkups."""

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
        conn.execute("PRAGMA foreign_keys = ON")  # CASCADE работает только с этим
        conn.row_factory = sqlite3.Row
        return conn

    # ── Init ───────────────────────────────────────────────────────────

    def init(self) -> None:
        """Создать таблицы из schema.sql с миграциями."""
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
        """БД создана, но фаз ещё не импортировано."""
        with self._conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM phases").fetchone()[0]
            return count == 0

    def import_phases(self, phases: list[dict]) -> None:
        """Залить фазы из YAML → SQLite (разово, при инициализации)."""
        with self._conn() as conn:
            for p in phases:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO phases (id, name, description, phase_order, skills)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        p["id"],
                        p["name"],
                        p.get("description") or "",
                        p["phase_order"],
                        p.get("skills"),
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
                        INSERT INTO evidence (phase_id, description)
                        VALUES (?, ?)
                        """,
                        (p["id"], e["description"]),
                    )
                for cu in p.get("checkups", []):
                    conn.execute(
                        """
                        INSERT INTO checkups (phase_id, name, check_type, target, interval_min, last_status, fail_action)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            p["id"],
                            cu["name"],
                            cu["check_type"],
                            cu.get("target"),
                            cu.get("interval_min", 0),
                            cu.get("last_status", "unknown"),
                            cu.get("fail_action", "warn"),
                        ),
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
        ]:
            try:
                conn.execute(f"ALTER TABLE phases ADD COLUMN {column} {ctype}")
            except sqlite3.OperationalError:
                pass  # already exists

    def get_phases(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM phases ORDER BY phase_order"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_phase(self, phase_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM phases WHERE id = ?", (phase_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_phase_instructions(self, phase_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM instructions
                WHERE phase_id = ?
                ORDER BY step_num
                """,
                (phase_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_phase_checks(self, phase_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM checks WHERE phase_id = ?", (phase_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_phase_evidence(self, phase_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM evidence WHERE phase_id = ?", (phase_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_phase_checkups(self, phase_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM checkups WHERE phase_id = ?", (phase_id,)
            ).fetchall()
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
        """Добавить инструкцию к фазе. Возвращает id."""
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

    # ── Check CRUD ───────────────────────────────────────────────────

    def create_check(self, data: dict) -> int:
        """Добавить check к фазе. Возвращает id."""
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
        """Добавить evidence к фазе. Возвращает id."""
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

    def reorder_instructions(self, phase_id: str, ids: list[int]) -> None:
        """Переставить step_num по порядку ids."""
        # Сброс уникальных значений
        with self._conn() as conn:
            for inst_id in ids:
                conn.execute(
                    "UPDATE instructions SET step_num = -? WHERE id = ? AND phase_id = ?",
                    (inst_id, inst_id, phase_id),
                )
            # Установить правильный порядок
            for new_num, inst_id in enumerate(ids, 1):
                conn.execute(
                    "UPDATE instructions SET step_num = ? WHERE id = ? AND phase_id = ?",
                    (new_num, inst_id, phase_id),
                )
            conn.commit()

    # ── Checkup CRUD ─────────────────────────────────────────────────

    def add_checkup(self, phase_id: str, data: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO checkups (phase_id, name, check_type, target, interval_min, last_status, fail_action)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    phase_id,
                    data["name"],
                    data["check_type"],
                    data.get("target"),
                    data.get("interval_min", 0),
                    data.get("last_status", "unknown"),
                    data.get("fail_action", "warn"),
                ),
            )
            conn.commit()

    def update_checkup(self, cu_id: int, data: dict) -> None:
        fields = []
        vals = []
        for k, v in data.items():
            fields.append(f"{k} = ?")
            vals.append(v)
        vals.append(cu_id)
        sql = f"UPDATE checkups SET {', '.join(fields)} WHERE id = ?"
        with self._conn() as conn:
            conn.execute(sql, vals)
            conn.commit()

    def run_checkup(self, cu_id: int, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE checkups SET last_status = ?, last_run = ? WHERE id = ?",
                (status, now, cu_id),
            )
            conn.commit()

    def get_checkup(self, cu_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM checkups WHERE id = ?", (cu_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_pending_checkups(self) -> list[dict]:
        """Чекапы которые пора проверить: unknown или interval прошёл."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM checkups
                WHERE last_status = 'unknown'
                    OR last_run IS NULL
                    OR (interval_min > 0
                        AND datetime(last_run, '+' || interval_min || ' minutes') <= datetime('now'))
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_checkup(self, cu_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM checkups WHERE id = ?", (cu_id,))
            conn.commit()
