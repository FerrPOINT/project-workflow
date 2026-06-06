"""WorkflowDB — SQLite persistence for workflow entities.

Схема: groups, agents, phases, instructions, checks, evidence, projects, tasks, task_history, cli_history.
Плоская структура, связи через FOREIGN KEY.
PK: INTEGER AUTOINCREMENT, семантические code TEXT UNIQUE.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import config

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

    def _resolve_project_id(self, val: int | str) -> int:
        if isinstance(val, int):
            return val
        row = self.get_project_by_code(val)
        if not row:
            raise ValueError(f"Unknown project code: {val}")
        return row["id"]

    def _resolve_workflow_id(self, val: int | str | None) -> int:
        if isinstance(val, int):
            return val
        if val is None:
            workflow = self.get_default_workflow()
            if not workflow:
                raise ValueError("Default workflow is not initialized")
            return workflow["id"]
        row = self.get_workflow_by_code(str(val))
        if not row:
            raise ValueError(f"Unknown workflow code: {val}")
        return row["id"]

    @staticmethod
    def _serialize_key_patterns(patterns: list[str] | str | None) -> str:
        if patterns is None:
            return "[]"
        if isinstance(patterns, str):
            return patterns
        return json.dumps([str(p) for p in patterns], ensure_ascii=False)

    @staticmethod
    def _deserialize_key_patterns(raw: list[str] | str | None) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            return [str(p) for p in raw]
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(p) for p in parsed]
            except Exception:
                pass
        return []

    def _hydrate_workflow_row(self, row: sqlite3.Row | dict | None) -> dict | None:
        if not row:
            return None
        return dict(row)

    def _hydrate_project_row(self, row: sqlite3.Row | dict | None) -> dict | None:
        if not row:
            return None
        data = dict(row)
        data["key_patterns"] = self._deserialize_key_patterns(data.get("key_patterns"))
        return data

    def _bootstrap_workflows(self) -> list[dict]:
        return [{
            "code": "default",
            "name": "Default Workflow",
            "description": "Базовый workflow каталога фаз",
        }]

    def _bootstrap_projects(self) -> list[dict]:
        legacy_patterns = config.load_legacy_key_patterns()
        if legacy_patterns:
            return [{
                "code": "default",
                "name": "Migrated Default Project",
                "key_patterns": legacy_patterns,
            }]
        return [{
            "code": "TASKNEIROKLYUCH",
            "name": "TASKNEIROKLYUCH",
            "key_patterns": config.DEFAULT_TASK_KEY_PATTERNS,
        }]

    def _table_columns(self, conn: sqlite3.Connection, table_name: str) -> list[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row[1] for row in rows]

    def _ensure_default_workflows(self, conn: sqlite3.Connection) -> None:
        count = conn.execute("SELECT COUNT(*) FROM workflows").fetchone()[0]
        if count:
            return
        for workflow in self._bootstrap_workflows():
            conn.execute(
                "INSERT INTO workflows (code, name, description) VALUES (?, ?, ?)",
                (
                    workflow["code"],
                    workflow["name"],
                    workflow.get("description", ""),
                ),
            )

    def _default_workflow_id(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT id FROM workflows WHERE code = ?", ("default",)).fetchone()
        if not row:
            raise ValueError("Default workflow is not initialized")
        return int(row["id"])

    def _ensure_default_projects(self, conn: sqlite3.Connection) -> None:
        count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        if count:
            return
        default_workflow_id = self._default_workflow_id(conn)
        for project in self._bootstrap_projects():
            conn.execute(
                "INSERT INTO projects (workflow_id, code, name, key_patterns) VALUES (?, ?, ?, ?)",
                (
                    default_workflow_id,
                    project["code"],
                    project["name"],
                    self._serialize_key_patterns(project.get("key_patterns")),
                ),
            )

    def _project_rows(self, conn: sqlite3.Connection) -> list[dict]:
        rows = conn.execute("SELECT * FROM projects ORDER BY id").fetchall()
        return [self._hydrate_project_row(row) for row in rows if row]

    def _match_project_for_task_key(
        self,
        task_key: str,
        conn: sqlite3.Connection,
        *,
        strict: bool = True,
    ) -> dict | None:
        from .task_validator import TaskKeyValidator

        projects = self._project_rows(conn)
        if not projects:
            return None
        validator = TaskKeyValidator.from_projects(projects)
        validated = validator.validate(task_key)
        if validated.is_valid and validated.project:
            for project in projects:
                if project["code"] == validated.project:
                    return project
        if strict:
            return None
        return projects[0]

    def _migrate_tasks_add_project(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            CREATE TABLE tasks_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id    INTEGER NOT NULL REFERENCES projects(id),
                task_key      TEXT NOT NULL UNIQUE,
                title         TEXT,
                description   TEXT,
                current_phase INTEGER NOT NULL DEFAULT -1,
                status        TEXT DEFAULT 'active'
                    CHECK(status IN ('active', 'done', 'blocked')),
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for row in rows:
            project = self._match_project_for_task_key(row["task_key"], conn, strict=False)
            if not project:
                raise ValueError(f"Cannot migrate task without project match: {row['task_key']}")
            conn.execute(
                """
                INSERT INTO tasks_new (id, project_id, task_key, title, description, current_phase, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    project["id"],
                    row["task_key"],
                    row["title"],
                    row["description"],
                    row["current_phase"],
                    row["status"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        conn.execute("DROP TABLE tasks")
        conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
        conn.execute("PRAGMA foreign_keys = ON")

    def _backfill_task_projects(self, conn: sqlite3.Connection) -> None:
        if "project_id" not in self._table_columns(conn, "tasks"):
            return
        rows = conn.execute("SELECT id, task_key FROM tasks WHERE project_id IS NULL OR project_id = ''").fetchall()
        for row in rows:
            project = self._match_project_for_task_key(row["task_key"], conn, strict=False)
            if project:
                conn.execute("UPDATE tasks SET project_id = ? WHERE id = ?", (project["id"], row["id"]))

    def _migrate_agents_add_description(self, conn: sqlite3.Connection) -> None:
        agent_columns = self._table_columns(conn, "agents")
        if "description" in agent_columns:
            return
        conn.execute("ALTER TABLE agents ADD COLUMN description TEXT NOT NULL DEFAULT ''")

    def _migrate_projects_add_workflow(self, conn: sqlite3.Connection) -> None:
        project_columns = self._table_columns(conn, "projects")
        if "workflow_id" not in project_columns:
            conn.execute("ALTER TABLE projects ADD COLUMN workflow_id INTEGER REFERENCES workflows(id)")
        default_workflow_id = self._default_workflow_id(conn)
        conn.execute(
            "UPDATE projects SET workflow_id = ? WHERE workflow_id IS NULL OR workflow_id = ''",
            (default_workflow_id,),
        )

    def _migrate_phases_add_workflow(self, conn: sqlite3.Connection) -> None:
        phase_columns = self._table_columns(conn, "phases")
        default_workflow_id = self._default_workflow_id(conn)
        if "workflow_id" not in phase_columns:
            conn.execute("ALTER TABLE phases ADD COLUMN workflow_id INTEGER REFERENCES workflows(id)")
        conn.execute(
            "UPDATE phases SET workflow_id = ? WHERE workflow_id IS NULL OR workflow_id = ''",
            (default_workflow_id,),
        )
        if "is_seed_managed" not in phase_columns:
            conn.execute("ALTER TABLE phases ADD COLUMN is_seed_managed INTEGER NOT NULL DEFAULT 1")
        conn.execute("UPDATE phases SET is_seed_managed = 1 WHERE is_seed_managed IS NULL")

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        task_columns = self._table_columns(conn, "tasks")
        self._migrate_agents_add_description(conn)
        self._migrate_projects_add_workflow(conn)
        self._migrate_phases_add_workflow(conn)
        if "project_id" not in task_columns:
            self._migrate_tasks_add_project(conn)
        self._backfill_task_projects(conn)

    # ── Init ───────────────────────────────────────────────────────────

    def init(self) -> None:
        ddl = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._conn() as conn:
            conn.executescript(ddl)
            self._ensure_default_workflows(conn)
            self._migrate_schema(conn)
            self._ensure_default_projects(conn)
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

    def sync_phase_catalog(
        self,
        phases: list[dict],
        phase_order: list[str],
        phase_redirects: dict[str, str] | None = None,
    ) -> None:
        """Синхронизировать SQLite-каталог фаз с seed и мигрировать legacy-коды."""
        phase_redirects = phase_redirects or {}

        seed_by_code: dict[str, dict] = {}
        for fallback_order, phase in enumerate(phases, start=1):
            code = str(phase.get("code", phase.get("id", ""))).strip()
            if not code:
                continue
            normalized = dict(phase)
            normalized["code"] = code
            normalized["phase_order"] = phase_order.index(code) + 1 if code in phase_order else fallback_order
            seed_by_code[code] = normalized

        desired_codes = set(seed_by_code)
        removed_codes = [code for code in phase_redirects if code not in desired_codes]

        with self._conn() as conn:
            default_workflow_id = self._default_workflow_id(conn)
            for code in phase_order:
                phase = seed_by_code.get(code)
                if not phase:
                    continue

                existing = conn.execute("SELECT id FROM phases WHERE code = ?", (code,)).fetchone()
                payload = (
                    default_workflow_id,
                    phase["name"],
                    phase.get("description") or "",
                    phase.get("min_time_min", 0),
                    phase["phase_order"],
                    phase.get("next_recommendation"),
                    phase.get("parallel_with"),
                    phase.get("rollback_target"),
                    phase.get("execution_type", "sync"),
                    1,
                )
                if existing:
                    conn.execute(
                        """
                        UPDATE phases
                        SET workflow_id = ?,
                            name = ?,
                            description = ?,
                            min_time_min = ?,
                            phase_order = ?,
                            next_recommendation = ?,
                            parallel_with = ?,
                            rollback_target = ?,
                            execution_type = ?,
                            is_seed_managed = ?
                        WHERE id = ?
                        """,
                        (*payload, existing["id"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO phases (
                            code, workflow_id, name, description, min_time_min, phase_order,
                            next_recommendation, parallel_with, rollback_target, execution_type, is_seed_managed
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            code,
                            *payload,
                        ),
                    )

            phase_rows = {
                row["code"]: dict(row)
                for row in conn.execute("SELECT * FROM phases").fetchall()
            }

            for legacy_code, target_code in phase_redirects.items():
                legacy_phase = phase_rows.get(legacy_code)
                target_phase = phase_rows.get(target_code)
                if not target_phase:
                    continue

                if not legacy_phase:
                    continue

                history_rows = conn.execute(
                    "SELECT id, task_id, status, completed_at FROM task_history WHERE phase_id = ?",
                    (legacy_phase["id"],),
                ).fetchall()
                for history_row in history_rows:
                    target_history = conn.execute(
                        "SELECT id, status, completed_at FROM task_history WHERE task_id = ? AND phase_id = ?",
                        (history_row["task_id"], target_phase["id"]),
                    ).fetchone()

                    if target_history:
                        merged_status = "done" if (
                            history_row["status"] == "done" or target_history["status"] == "done"
                        ) else target_history["status"]
                        merged_completed_at = target_history["completed_at"] or history_row["completed_at"]
                        conn.execute(
                            "UPDATE task_history SET status = ?, completed_at = ? WHERE id = ?",
                            (merged_status, merged_completed_at, target_history["id"]),
                        )
                        conn.execute("DELETE FROM task_history WHERE id = ?", (history_row["id"],))
                    else:
                        conn.execute(
                            "UPDATE task_history SET phase_id = ? WHERE id = ?",
                            (target_phase["id"], history_row["id"]),
                        )

            if removed_codes:
                placeholders = ", ".join("?" for _ in removed_codes)
                conn.execute(
                    f"UPDATE phases SET parallel_with = NULL WHERE parallel_with IN ({placeholders})",
                    removed_codes,
                )

            desired_ids = [phase_rows[code]["id"] for code in phase_order if code in phase_rows]
            if desired_ids:
                placeholders = ", ".join("?" for _ in desired_ids)
                for table_name in ("instructions", "checks", "evidence"):
                    conn.execute(
                        f"DELETE FROM {table_name} WHERE phase_id IN ({placeholders})",
                        desired_ids,
                    )

            for code in phase_order:
                phase = seed_by_code.get(code)
                if not phase or code not in phase_rows:
                    continue
                phase_id = phase_rows[code]["id"]

                for fallback_step_num, inst in enumerate(phase.get("instructions", []), start=1):
                    raw_skills = inst.get("skills")
                    skills_payload = json.dumps(raw_skills, ensure_ascii=False) if isinstance(raw_skills, list) else raw_skills
                    conn.execute(
                        """
                        INSERT INTO instructions (phase_id, step_num, description, execution_type, skills)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            phase_id,
                            inst.get("step_num", fallback_step_num),
                            inst["description"],
                            inst.get("execution_type", "sync"),
                            skills_payload,
                        ),
                    )

                for check in phase.get("checks", []):
                    conn.execute(
                        "INSERT INTO checks (phase_id, description) VALUES (?, ?)",
                        (phase_id, check["description"]),
                    )

                for evidence in phase.get("evidence", []):
                    conn.execute(
                        "INSERT INTO evidence (phase_id, description) VALUES (?, ?)",
                        (phase_id, evidence.get("description", evidence.get("item", ""))),
                    )

            stale_rows = conn.execute("SELECT id, code, is_seed_managed FROM phases").fetchall()
            for stale_row in stale_rows:
                if stale_row["code"] in desired_codes:
                    continue
                if not stale_row["is_seed_managed"]:
                    continue
                conn.execute("DELETE FROM phases WHERE id = ?", (stale_row["id"],))

            conn.commit()

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
                "INSERT INTO agents (name, description) VALUES (?, ?)",
                (
                    data["name"],
                    str(data.get("description", "")).strip(),
                ),
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

    # ── Workflows ───────────────────────────────────────────────────────

    def create_workflow(self, data: dict) -> int:
        code = str(data.get("code", data.get("id", ""))).strip()
        if not code:
            raise ValueError("Workflow code is required")
        with self._conn() as conn:
            c = conn.execute(
                "INSERT INTO workflows (code, name, description) VALUES (?, ?, ?)",
                (
                    code,
                    str(data.get("name", code)).strip() or code,
                    str(data.get("description", "")).strip(),
                ),
            )
            conn.commit()
            return c.lastrowid or 0

    def get_workflows(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM workflows ORDER BY id").fetchall()
            return [self._hydrate_workflow_row(r) for r in rows if r]

    def get_workflow(self, workflow_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
            return self._hydrate_workflow_row(row)

    def get_workflow_by_code(self, code: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE code = ?", (code,)).fetchone()
            return self._hydrate_workflow_row(row)

    def get_default_workflow(self) -> dict | None:
        return self.get_workflow_by_code("default")

    def update_workflow(self, workflow_id: int | str, data: dict) -> None:
        resolved = self._resolve_workflow_id(workflow_id)
        fields = []
        vals = []
        for k, v in data.items():
            if k == "id":
                continue
            fields.append(f"{k} = ?")
            vals.append(v)
        if not fields:
            return
        vals.append(resolved)
        sql = f"UPDATE workflows SET {', '.join(fields)} WHERE id = ?"
        with self._conn() as conn:
            conn.execute(sql, vals)
            conn.commit()

    def delete_workflow(self, workflow_id: int | str) -> None:
        resolved = self._resolve_workflow_id(workflow_id)
        with self._conn() as conn:
            conn.execute("DELETE FROM workflows WHERE id = ?", (resolved,))
            conn.commit()

    # ── Projects ────────────────────────────────────────────────────────

    def create_project(self, data: dict) -> int:
        code = str(data.get("code", data.get("id", ""))).strip()
        if not code:
            raise ValueError("Project code is required")
        workflow_id = self._resolve_workflow_id(data.get("workflow_id", data.get("workflow", data.get("workflow_code"))))
        with self._conn() as conn:
            c = conn.execute(
                "INSERT INTO projects (workflow_id, code, name, key_patterns) VALUES (?, ?, ?, ?)",
                (
                    workflow_id,
                    code,
                    data.get("name", code),
                    self._serialize_key_patterns(data.get("key_patterns")),
                ),
            )
            conn.commit()
            return c.lastrowid or 0

    def get_projects(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT projects.*, workflows.code AS workflow_code, workflows.name AS workflow_name, workflows.description AS workflow_description
                FROM projects
                JOIN workflows ON workflows.id = projects.workflow_id
                ORDER BY projects.id
                """
            ).fetchall()
            return [self._hydrate_project_row(r) for r in rows if r]

    def get_project(self, project_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT projects.*, workflows.code AS workflow_code, workflows.name AS workflow_name, workflows.description AS workflow_description
                FROM projects
                JOIN workflows ON workflows.id = projects.workflow_id
                WHERE projects.id = ?
                """,
                (project_id,),
            ).fetchone()
            return self._hydrate_project_row(row)

    def get_project_by_code(self, code: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT projects.*, workflows.code AS workflow_code, workflows.name AS workflow_name, workflows.description AS workflow_description
                FROM projects
                JOIN workflows ON workflows.id = projects.workflow_id
                WHERE projects.code = ?
                """,
                (code,),
            ).fetchone()
            return self._hydrate_project_row(row)

    def update_project(self, project_id: int | str, data: dict) -> None:
        resolved = self._resolve_project_id(project_id)
        fields = []
        vals = []
        for k, v in data.items():
            if k == "id":
                continue
            if k == "key_patterns":
                fields.append("key_patterns = ?")
                vals.append(self._serialize_key_patterns(v))
            elif k in {"workflow_id", "workflow", "workflow_code"}:
                fields.append("workflow_id = ?")
                vals.append(self._resolve_workflow_id(v))
            else:
                fields.append(f"{k} = ?")
                vals.append(v)
        if not fields:
            return
        vals.append(resolved)
        sql = f"UPDATE projects SET {', '.join(fields)} WHERE id = ?"
        with self._conn() as conn:
            conn.execute(sql, vals)
            conn.commit()

    def delete_project(self, project_id: int | str) -> None:
        resolved = self._resolve_project_id(project_id)
        with self._conn() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (resolved,))
            conn.commit()

    # ── Import Phases (from YAML/JSON) ─────────────────────────────────

    def import_phases(self, phases: list[dict]) -> None:
        with self._conn() as conn:
            default_workflow_id = self._default_workflow_id(conn)
            for p in phases:
                code = p.get("code", p.get("id", ""))
                workflow_id = self._resolve_workflow_id(p.get("workflow_id", default_workflow_id))
                conn.execute(
                    """
                    INSERT OR REPLACE INTO phases (workflow_id, code, name, description, min_time_min, phase_order, group_id, agent_id, next_recommendation, parallel_with, rollback_target, execution_type, is_seed_managed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workflow_id,
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
                        1,
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

    def get_phases(self, workflow_id: int | str | None = None) -> list[dict]:
        with self._conn() as conn:
            params: tuple[Any, ...] = ()
            where_clause = ""
            if workflow_id is not None:
                where_clause = "WHERE phases.workflow_id = ?"
                params = (self._resolve_workflow_id(workflow_id),)
            rows = conn.execute(
                f"""
                SELECT phases.*, workflows.code AS workflow_code, workflows.name AS workflow_name, workflows.description AS workflow_description
                FROM phases
                JOIN workflows ON workflows.id = phases.workflow_id
                {where_clause}
                ORDER BY phases.phase_order
                """,
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def get_phase(self, phase_id: int | str) -> dict | None:
        with self._conn() as conn:
            if isinstance(phase_id, int):
                row = conn.execute(
                    """
                    SELECT phases.*, workflows.code AS workflow_code, workflows.name AS workflow_name, workflows.description AS workflow_description
                    FROM phases
                    JOIN workflows ON workflows.id = phases.workflow_id
                    WHERE phases.id = ?
                    """,
                    (phase_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT phases.*, workflows.code AS workflow_code, workflows.name AS workflow_name, workflows.description AS workflow_description
                    FROM phases
                    JOIN workflows ON workflows.id = phases.workflow_id
                    WHERE phases.code = ?
                    """,
                    (phase_id,),
                ).fetchone()
            return dict(row) if row else None

    def get_phase_by_code(self, code: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT phases.*, workflows.code AS workflow_code, workflows.name AS workflow_name, workflows.description AS workflow_description
                FROM phases
                JOIN workflows ON workflows.id = phases.workflow_id
                WHERE phases.code = ?
                """,
                (code,),
            ).fetchone()
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
            workflow_id = self._resolve_workflow_id(data.get("workflow_id", data.get("workflow", data.get("workflow_code"))))
            c = conn.execute(
                """
                INSERT INTO phases (workflow_id, code, name, description, min_time_min, phase_order, group_id, agent_id,
                                    next_recommendation, parallel_with, rollback_target, execution_type, is_seed_managed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
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
                    int(bool(data.get("is_seed_managed", 0))),
                ),
            )
            conn.commit()
            return c.lastrowid or 0

    def update_phase(self, phase_id: int | str, data: dict) -> None:
        resolved = self._resolve_phase_id(phase_id)
        fields = []
        vals = []
        for k, v in data.items():
            if k == "id":
                continue
            if k == "group_id":
                fields.append("group_id = ?")
                vals.append(self._resolve_group_id(v) if v else None)
            elif k in {"workflow_id", "workflow", "workflow_code"}:
                fields.append("workflow_id = ?")
                vals.append(self._resolve_workflow_id(v))
            else:
                fields.append(f"{k} = ?")
                vals.append(v)
        if not fields:
            return
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
            project_id = data.get("project_id")
            if project_id is None and data.get("project") is not None:
                project_id = self._resolve_project_id(data["project"])
            if project_id is None and data.get("project_code") is not None:
                project_id = self._resolve_project_id(data["project_code"])
            if project_id is None:
                project = self._match_project_for_task_key(data["task_key"], conn)
                if not project:
                    raise ValueError(f"No project regex matched task key: {data['task_key']}")
                project_id = project["id"]
            c = conn.execute(
                """
                INSERT INTO tasks (project_id, task_key, title, description, current_phase, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
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
            rows = conn.execute(
                """
                SELECT tasks.*, projects.code AS project_code, projects.name AS project_name
                FROM tasks
                JOIN projects ON projects.id = tasks.project_id
                ORDER BY tasks.updated_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT tasks.*, projects.code AS project_code, projects.name AS project_name
                FROM tasks
                JOIN projects ON projects.id = tasks.project_id
                WHERE tasks.id = ?
                """,
                (task_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_task_by_key(self, task_key: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT tasks.*, projects.code AS project_code, projects.name AS project_name
                FROM tasks
                JOIN projects ON projects.id = tasks.project_id
                WHERE tasks.task_key = ?
                """,
                (task_key,),
            ).fetchone()
            return dict(row) if row else None

    def update_task(self, task_id: int, data: dict) -> None:
        fields = []
        vals = []
        for k, v in data.items():
            if k == "project":
                fields.append("project_id = ?")
                vals.append(self._resolve_project_id(v))
            elif k == "project_code":
                fields.append("project_id = ?")
                vals.append(self._resolve_project_id(v))
            else:
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

    def update_phase_parallel(self, phase_id: int | str, parallel_with: str | None) -> None:
        resolved_phase = self._resolve_phase_id(phase_id)
        with self._conn() as conn:
            conn.execute("UPDATE phases SET parallel_with = ? WHERE id = ?", (parallel_with, resolved_phase))
            conn.commit()

    def batch_update_groups(self, group_map: dict[str, str]) -> None:
        resolved_batch = [
            (parallel_with, self._resolve_phase_id(phase_id))
            for phase_id, parallel_with in group_map.items()
        ]
        with self._conn() as conn:
            conn.executemany(
                "UPDATE phases SET parallel_with = ? WHERE id = ?",
                resolved_batch,
            )
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
