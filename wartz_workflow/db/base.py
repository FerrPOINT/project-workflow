"""WorkflowDB — SQLite persistence for workflow entities.

Схема: workflows, agents, phases, instructions, checks, evidence, projects, tasks, task_history, cli_history.
Плоская структура, связи через FOREIGN KEY.
PK: INTEGER AUTOINCREMENT, семантические code TEXT UNIQUE для фаз и проектов.
"""

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .. import config

# Deterministic default: package-local data directory (not expanduser which
# resolves differently under systemd vs Hermes terminal).
# WORKFLOW_DB_PATH env var overrides for production / systemd.
_pkg_dir = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("WORKFLOW_DB_PATH", str(_pkg_dir / "data" / "workflow.db")))
SCHEMA_PATH = Path(__file__).parent / "db_schema.sql"


class WorkflowDB:
    """SQLite workflow persistence."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(DB_PATH)
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute("PRAGMA cache_size = -32000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def close(self) -> None:
        pass

    def _resolve_phase_id(self, val: int | str) -> int:
        if isinstance(val, int):
            return val
        row = self.get_phase_by_code(val)
        if not row:
            raise ValueError(f"Unknown phase code: {val}")
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
        token = str(val).strip()
        if token.isdigit():
            return int(token)
        workflow = self.get_workflow_by_name(token)
        if workflow:
            return int(workflow["id"])
        raise ValueError(f"Unknown workflow id: {val}")

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

    @staticmethod
    def _json_dumps(value: Any, fallback: str = "{}") -> str:
        if value is None:
            return fallback
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _json_loads(raw: Any, default: Any) -> Any:
        if raw in (None, ""):
            return default
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            return default

    def _hydrate_workflow_row(self, row: sqlite3.Row | dict | None) -> dict | None:
        if not row:
            return None
        data = dict(row)
        if "is_default" in data:
            data["is_default"] = bool(data.get("is_default"))
        return data

    def _hydrate_project_row(self, row: sqlite3.Row | dict | None) -> dict | None:
        if not row:
            return None
        data = dict(row)
        data["key_patterns"] = self._deserialize_key_patterns(data.get("key_patterns"))
        if "workflow_is_default" in data:
            data["workflow_is_default"] = bool(data.get("workflow_is_default"))
        return data

    def _hydrate_supervisor_run_row(self, row: sqlite3.Row | dict | None) -> dict | None:
        if not row:
            return None
        data = dict(row)
        data["covered"] = self._json_loads(data.get("covered"), [])
        data["missing"] = self._json_loads(data.get("missing"), [])
        data["blockers"] = self._json_loads(data.get("blockers"), [])
        data["context_snapshot"] = self._json_loads(data.get("context_snapshot"), {})
        data["response"] = self._json_loads(data.get("response"), {})
        return data

    def _bootstrap_workflows(self) -> list[dict]:
        return [
            {
                "name": config.DEFAULT_WORKFLOW_NAME,
                "description": "Базовый workflow каталога фаз",
                "is_default": 1,
            },
            {
                "name": config.SMOKE_WORKFLOW_NAME,
                "description": "Короткий боевой workflow для CLI smoke/regression тестирования parallel веток, delegated phase metadata, rollback и history.",
                "is_default": 0,
            },
        ]

    def _bootstrap_projects(self) -> list[dict]:
        legacy_patterns = config.load_legacy_key_patterns()
        default_project = {
            "workflow_name": config.DEFAULT_WORKFLOW_NAME,
            "code": "TASKNEIROKLYUCH",
            "name": "TASKNEIROKLYUCH",
            "key_patterns": config.DEFAULT_TASK_KEY_PATTERNS,
        }
        if legacy_patterns:
            default_project = {
                "workflow_name": config.DEFAULT_WORKFLOW_NAME,
                "code": "default",
                "name": "Migrated Default Project",
                "key_patterns": legacy_patterns,
            }
        return [
            default_project,
            {
                "workflow_name": config.SMOKE_WORKFLOW_NAME,
                "code": config.SMOKE_PROJECT_CODE,
                "name": config.SMOKE_PROJECT_NAME,
                "key_patterns": config.SMOKE_TASK_KEY_PATTERNS,
            },
        ]

    def _bootstrap_agents(self) -> list[dict]:
        return [
            {
                "name": "researcher",
                "description": "Исследует кодовую базу, зависимости и dataflow; собирает контекст перед изменениями.",
            },
            {
                "name": "critic",
                "description": "Проводит gate-review планов и результатов, ищет риски и незакрытые обязательные проверки.",
            },
            {
                "name": "reviewer",
                "description": "Проверяет качество решения, тесты и безопасность; фиксирует замечания по результату review.",
            },
            {
                "name": "ops",
                "description": "Ведёт операционные шаги workflow: статусы, артефакты, hand-off и финальное закрытие.",
            },
            {
                "name": "coder",
                "description": "Готовит реализацию, итоговые выводы и улучшения процесса после завершения задачи.",
            },
        ]

    @staticmethod
    def _normalize_agent_name(value: str | None) -> str:
        return str(value or "").strip().casefold()

    def _ensure_default_agents(self, conn: sqlite3.Connection) -> None:
        existing = conn.execute("SELECT id, name, description FROM agents ORDER BY id").fetchall()
        existing_by_name = {
            self._normalize_agent_name(row["name"]): dict(row)
            for row in existing
            if self._normalize_agent_name(row["name"])
        }
        for agent in self._bootstrap_agents():
            normalized_name = self._normalize_agent_name(agent["name"])
            row = existing_by_name.get(normalized_name)
            if row is None:
                conn.execute(
                    "INSERT INTO agents (name, description) VALUES (?, ?)",
                    (agent["name"], agent["description"]),
                )
                continue
            if str(row.get("description") or "").strip():
                continue
            conn.execute(
                "UPDATE agents SET description = ? WHERE id = ?",
                (agent["description"], row["id"]),
            )

    def _resolve_seed_agent_id(self, conn: sqlite3.Connection, phase: dict) -> int | None:
        if "selected_agent" not in phase:
            raw_agent_id = phase.get("agent_id")
            return int(raw_agent_id) if isinstance(raw_agent_id, int) else None

        requested_name = str(phase.get("selected_agent") or "").strip()
        normalized_name = self._normalize_agent_name(requested_name)
        if not normalized_name:
            return None

        rows = conn.execute("SELECT id, name, description FROM agents ORDER BY id").fetchall()
        for row in rows:
            if self._normalize_agent_name(row["name"]) == normalized_name:
                if str(row["description"] or "").strip():
                    return int(row["id"])
                default_description = next(
                    (
                        item["description"]
                        for item in self._bootstrap_agents()
                        if self._normalize_agent_name(item["name"]) == normalized_name
                    ),
                    "",
                )
                if default_description:
                    conn.execute(
                        "UPDATE agents SET description = ? WHERE id = ?",
                        (default_description, row["id"]),
                    )
                return int(row["id"])

        default_name, default_description = next(
            (
                (item["name"], item["description"])
                for item in self._bootstrap_agents()
                if self._normalize_agent_name(item["name"]) == normalized_name
            ),
            (requested_name, ""),
        )
        created = conn.execute(
            "INSERT INTO agents (name, description) VALUES (?, ?)",
            (default_name, default_description),
        )
        return int(created.lastrowid or 0)

    def _sanitize_default_project_patterns(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT id, key_patterns FROM projects WHERE code = ?",
            ("TASKNEIROKLYUCH",),
        ).fetchone()
        if not row:
            return

        patterns = self._deserialize_key_patterns(row["key_patterns"])
        cleaned = [pattern for pattern in patterns if "HRRECRUITER" not in str(pattern)]
        if not cleaned:
            cleaned = list(config.DEFAULT_TASK_KEY_PATTERNS)
        if cleaned == patterns:
            return

        conn.execute(
            "UPDATE projects SET key_patterns = ? WHERE id = ?",
            (self._serialize_key_patterns(cleaned), row["id"]),
        )

    def _prune_known_fixture_data(self, conn: sqlite3.Connection) -> None:
        fixture_project = conn.execute(
            "SELECT id FROM projects WHERE code = ? AND name = ?",
            ("UITEST", "UI Test Project"),
        ).fetchone()
        if fixture_project:
            conn.execute("DELETE FROM tasks WHERE project_id = ?", (fixture_project["id"],))
            conn.execute("DELETE FROM projects WHERE id = ?", (fixture_project["id"],))

        conn.execute(
            "DELETE FROM tasks WHERE task_key = ? AND title = ?",
            ("TASKNEIROKLYUCH-247", "Добавить E2E тесты для workflow"),
        )

    def _dedupe_agents(self, conn: sqlite3.Connection) -> None:
        seen: dict[tuple[str, str], int] = {}
        rows = conn.execute("SELECT id, name, description FROM agents ORDER BY id").fetchall()
        for row in rows:
            key = (
                str(row["name"] or "").strip().casefold(),
                str(row["description"] or "").strip(),
            )
            if not key[0]:
                continue

            keeper_id = seen.get(key)
            if keeper_id is None:
                seen[key] = row["id"]
                continue

            conn.execute("UPDATE phases SET agent_id = ? WHERE agent_id = ?", (keeper_id, row["id"]))
            conn.execute("DELETE FROM agents WHERE id = ?", (row["id"],))

    def _sanitize_runtime_state(self, conn: sqlite3.Connection) -> None:
        self._sanitize_default_project_patterns(conn)
        self._prune_known_fixture_data(conn)
        self._dedupe_agents(conn)

    def sanitize_runtime_state(self) -> None:
        with self._conn() as conn:
            self._sanitize_runtime_state(conn)
            conn.commit()

    def _table_columns(self, conn: sqlite3.Connection, table_name: str) -> list[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row[1] for row in rows]

    def _table_sql(self, conn: sqlite3.Connection, table_name: str) -> str:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return str(row[0] or "") if row else ""

    def _migrate_workflows_drop_code(self, conn: sqlite3.Connection) -> None:
        workflow_columns = self._table_columns(conn, "workflows")
        if "code" not in workflow_columns and "is_default" in workflow_columns:
            return

        rows = conn.execute("SELECT * FROM workflows ORDER BY id").fetchall()
        default_workflow_id: int | None = None
        if rows:
            if "is_default" in workflow_columns:
                for row in rows:
                    if int(row["is_default"] or 0) == 1:
                        default_workflow_id = int(row["id"])
                        break
            if default_workflow_id is None and "code" in workflow_columns:
                for row in rows:
                    if str(row["code"] or "").strip() == "default":
                        default_workflow_id = int(row["id"])
                        break
            if default_workflow_id is None:
                bootstrap_name = str(self._bootstrap_workflows()[0].get("name", "")).strip()
                for row in rows:
                    if str(row["name"] or "").strip() == bootstrap_name:
                        default_workflow_id = int(row["id"])
                        break
            if default_workflow_id is None:
                default_workflow_id = int(rows[0]["id"])

        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            CREATE TABLE workflows_new (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                is_default  INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0, 1))
            )
            """
        )
        for row in rows:
            conn.execute(
                "INSERT INTO workflows_new (id, name, description, is_default) VALUES (?, ?, ?, ?)",
                (
                    row["id"],
                    str(row["name"] or "").strip(),
                    str(row["description"] or "").strip(),
                    1 if default_workflow_id is not None and int(row["id"]) == default_workflow_id else 0,
                ),
            )
        conn.execute("DROP TABLE workflows")
        conn.execute("ALTER TABLE workflows_new RENAME TO workflows")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_workflows_single_default ON workflows(is_default) WHERE is_default = 1"
        )
        conn.execute("PRAGMA foreign_keys = ON")

    def _ensure_default_workflows(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_workflows_single_default ON workflows(is_default) WHERE is_default = 1"
        )
        existing_rows = conn.execute("SELECT id, name, description, is_default FROM workflows ORDER BY id").fetchall()
        existing_by_name = {
            str(row["name"] or "").strip(): row
            for row in existing_rows
            if str(row["name"] or "").strip()
        }
        bootstrap_workflows = self._bootstrap_workflows()
        bootstrap_default_name = str(bootstrap_workflows[0].get("name", "")).strip() if bootstrap_workflows else ""

        for workflow in bootstrap_workflows:
            workflow_name = str(workflow.get("name", "")).strip()
            if not workflow_name:
                continue
            if (
                bool(existing_rows)
                and bool(workflow.get("is_default"))
                and workflow_name == bootstrap_default_name
                and workflow_name not in existing_by_name
            ):
                continue
            row = existing_by_name.get(workflow_name)
            if row is None:
                conn.execute(
                    "INSERT INTO workflows (name, description, is_default) VALUES (?, ?, ?)",
                    (
                        workflow_name,
                        str(workflow.get("description", "") or "").strip(),
                        0,
                    ),
                )
                continue
            if not str(row["description"] or "").strip() and str(workflow.get("description", "") or "").strip():
                conn.execute(
                    "UPDATE workflows SET description = ? WHERE id = ?",
                    (str(workflow.get("description", "") or "").strip(), row["id"]),
                )

        rows = conn.execute("SELECT id, name, description, is_default FROM workflows ORDER BY id").fetchall()
        default_rows = [row for row in rows if int(row["is_default"] or 0) == 1]
        if not default_rows:
            bootstrap_name = str(self._bootstrap_workflows()[0].get("name", "")).strip()
            selected = next(
                (row for row in rows if str(row["name"] or "").strip() == bootstrap_name),
                rows[0],
            )
            conn.execute("UPDATE workflows SET is_default = 0")
            conn.execute("UPDATE workflows SET is_default = 1 WHERE id = ?", (selected["id"],))
            return

        keeper_id = int(default_rows[0]["id"])
        conn.execute("UPDATE workflows SET is_default = 0 WHERE id != ? AND is_default = 1", (keeper_id,))

    def _align_bootstrap_catalog_to_default_workflow(self, conn: sqlite3.Connection) -> None:
        default_workflow_id = self._default_workflow_id(conn)

        bootstrap_project_codes = [
            str(project.get("code", "")).strip()
            for project in self._bootstrap_projects()
            if str(project.get("workflow_name", config.DEFAULT_WORKFLOW_NAME)).strip() == config.DEFAULT_WORKFLOW_NAME
            if str(project.get("code", "")).strip()
        ]
        if bootstrap_project_codes:
            placeholders = ", ".join("?" for _ in bootstrap_project_codes)
            conn.execute(
                f"UPDATE projects SET workflow_id = ? WHERE code IN ({placeholders}) AND workflow_id != ?",
                (default_workflow_id, *bootstrap_project_codes, default_workflow_id),
            )

        phase_codes = [code for code in config.PHASE_ORDER if str(code).strip()]
        if phase_codes:
            placeholders = ", ".join("?" for _ in phase_codes)
            seed_filter = ""
            if "is_seed_managed" in self._table_columns(conn, "phases"):
                seed_filter = " AND (is_seed_managed = 1 OR is_seed_managed IS NULL)"
            conn.execute(
                f"UPDATE phases SET workflow_id = ? WHERE code IN ({placeholders}) AND workflow_id != ?{seed_filter}",
                (default_workflow_id, *phase_codes, default_workflow_id),
            )

    def _default_workflow_id(self, conn: sqlite3.Connection) -> int:
        row = conn.execute("SELECT id FROM workflows WHERE is_default = 1 ORDER BY id LIMIT 1").fetchone()
        if not row:
            raise ValueError("Default workflow is not initialized")
        return int(row["id"])

    def _ensure_default_projects(self, conn: sqlite3.Connection) -> None:
        workflows = conn.execute("SELECT id, name FROM workflows ORDER BY id").fetchall()
        workflow_ids_by_name = {
            str(row["name"] or "").strip(): int(row["id"])
            for row in workflows
            if str(row["name"] or "").strip()
        }
        default_workflow_id = self._default_workflow_id(conn)
        existing_rows = conn.execute("SELECT id, code FROM projects ORDER BY id").fetchall()
        existing_codes = {
            str(row["code"] or "").strip()
            for row in existing_rows
            if str(row["code"] or "").strip()
        }
        for project in self._bootstrap_projects():
            if project["code"] in existing_codes:
                continue
            workflow_name = str(project.get("workflow_name", config.DEFAULT_WORKFLOW_NAME)).strip()
            workflow_id = workflow_ids_by_name.get(workflow_name, default_workflow_id)
            conn.execute(
                "INSERT INTO projects (workflow_id, code, name, key_patterns) VALUES (?, ?, ?, ?)",
                (
                    workflow_id,
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
        from ..task_validator import TaskKeyValidator

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

    def match_project_for_task_key(self, task_key: str, *, strict: bool = True) -> dict | None:
        with self._conn() as conn:
            return self._match_project_for_task_key(task_key, conn, strict=strict)

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
                current_phase TEXT NOT NULL DEFAULT '-1',
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
                    str(row["current_phase"] if row["current_phase"] not in (None, "") else "-1"),
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

    def _migrate_tasks_current_phase_to_text(self, conn: sqlite3.Connection) -> None:
        task_columns = self._table_columns(conn, "tasks")
        if "current_phase" not in task_columns:
            return
        info = conn.execute("PRAGMA table_info(tasks)").fetchall()
        current_phase_col = next((row for row in info if row[1] == "current_phase"), None)
        if current_phase_col and str(current_phase_col[2] or "").upper() == "TEXT":
            return

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
                current_phase TEXT NOT NULL DEFAULT '-1',
                status        TEXT DEFAULT 'active'
                    CHECK(status IN ('active', 'done', 'blocked')),
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for row in rows:
            current_phase = row["current_phase"]
            current_phase_value = "-1" if current_phase in (None, "") else str(current_phase)
            conn.execute(
                """
                INSERT INTO tasks_new (id, project_id, task_key, title, description, current_phase, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["project_id"],
                    row["task_key"],
                    row["title"],
                    row["description"],
                    current_phase_value,
                    row["status"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        conn.execute("DROP TABLE tasks")
        conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
        conn.execute("PRAGMA foreign_keys = ON")

    def _migrate_task_history_statuses(self, conn: sqlite3.Connection) -> None:
        create_sql = self._table_sql(conn, "task_history").lower()
        if all(token in create_sql for token in ("partial", "blocked", "rollback", "delegated")):
            return

        rows = conn.execute("SELECT * FROM task_history ORDER BY id").fetchall()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            CREATE TABLE task_history_new (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id      INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                phase_id     INTEGER NOT NULL REFERENCES phases(id),
                status       TEXT DEFAULT 'pending'
                    CHECK(status IN ('pending', 'done', 'partial', 'blocked', 'rollback', 'delegated')),
                completed_at TEXT,
                UNIQUE(task_id, phase_id)
            )
            """
        )
        allowed_statuses = {"pending", "done", "partial", "blocked", "rollback", "delegated"}
        for row in rows:
            status = str(row["status"] or "pending").strip().lower()
            if status not in allowed_statuses:
                status = "pending"
            conn.execute(
                "INSERT INTO task_history_new (id, task_id, phase_id, status, completed_at) VALUES (?, ?, ?, ?, ?)",
                (row["id"], row["task_id"], row["phase_id"], status, row["completed_at"]),
            )
        conn.execute("DROP TABLE task_history")
        conn.execute("ALTER TABLE task_history_new RENAME TO task_history")
        conn.execute("PRAGMA foreign_keys = ON")

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        task_columns = self._table_columns(conn, "tasks")
        self._migrate_workflows_drop_code(conn)
        self._ensure_default_workflows(conn)
        self._migrate_agents_add_description(conn)
        self._migrate_projects_add_workflow(conn)
        self._migrate_phases_add_workflow(conn)
        if "project_id" not in task_columns:
            self._migrate_tasks_add_project(conn)
        self._backfill_task_projects(conn)
        self._migrate_tasks_current_phase_to_text(conn)
        self._migrate_task_history_statuses(conn)

    # ── Init ───────────────────────────────────────────────────────────

    def init(self) -> None:
        ddl = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._conn() as conn:
            conn.executescript(ddl)
            self._migrate_schema(conn)
            self._ensure_default_workflows(conn)
            self._align_bootstrap_catalog_to_default_workflow(conn)
            self._ensure_default_projects(conn)
            self._ensure_default_agents(conn)
            self._sanitize_runtime_state(conn)
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
        workflow_id: int | str | None = None,
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
            self._ensure_default_workflows(conn)
            catalog_workflow_id = self._resolve_workflow_id(workflow_id) if workflow_id is not None else self._default_workflow_id(conn)
            for code in phase_order:
                phase = seed_by_code.get(code)
                if not phase:
                    continue

                existing = conn.execute("SELECT id, agent_id FROM phases WHERE code = ?", (code,)).fetchone()
                seed_agent_id = (
                    self._resolve_seed_agent_id(conn, phase)
                    if ("selected_agent" in phase or "agent_id" in phase)
                    else (existing["agent_id"] if existing else None)
                )
                payload = (
                    catalog_workflow_id,
                    phase["name"],
                    phase.get("description") or "",
                    phase.get("min_time_min", 0),
                    phase["phase_order"],
                    seed_agent_id,
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
                            agent_id = ?,
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
                            agent_id, next_recommendation, parallel_with, rollback_target, execution_type, is_seed_managed
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

            stale_rows = conn.execute(
                "SELECT id, code, is_seed_managed, workflow_id FROM phases WHERE workflow_id = ?",
                (catalog_workflow_id,),
            ).fetchall()
            for stale_row in stale_rows:
                if stale_row["code"] in desired_codes:
                    continue
                if not stale_row["is_seed_managed"]:
                    continue
                conn.execute("DELETE FROM phases WHERE id = ?", (stale_row["id"],))

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
        name = str(data.get("name", "")).strip()
        if not name:
            raise ValueError("Workflow name is required")
        with self._conn() as conn:
            c = conn.execute(
                "INSERT INTO workflows (name, description, is_default) VALUES (?, ?, ?)",
                (
                    name,
                    str(data.get("description", "")).strip(),
                    1 if bool(data.get("is_default")) else 0,
                ),
            )
            conn.commit()
            return c.lastrowid or 0

    def get_workflows(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM workflows ORDER BY id").fetchall()
            return [self._hydrate_workflow_row(r) for r in rows if r]

    def get_workflow_by_name(self, name: str) -> dict | None:
        normalized = str(name or "").strip()
        if not normalized:
            return None
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE name = ? ORDER BY id LIMIT 1", (normalized,)).fetchone()
            return self._hydrate_workflow_row(row)

    def get_workflow(self, workflow_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
            return self._hydrate_workflow_row(row)

    def get_default_workflow(self) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE is_default = 1 ORDER BY id LIMIT 1").fetchone()
            return self._hydrate_workflow_row(row)

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
                SELECT projects.*, workflows.name AS workflow_name, workflows.description AS workflow_description, workflows.is_default AS workflow_is_default
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
                SELECT projects.*, workflows.name AS workflow_name, workflows.description AS workflow_description, workflows.is_default AS workflow_is_default
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
                SELECT projects.*, workflows.name AS workflow_name, workflows.description AS workflow_description, workflows.is_default AS workflow_is_default
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
                seed_agent_id = self._resolve_seed_agent_id(conn, p) if ("selected_agent" in p or "agent_id" in p) else None
                conn.execute(
                    """
                    INSERT OR REPLACE INTO phases (workflow_id, code, name, description, min_time_min, phase_order, agent_id, next_recommendation, parallel_with, rollback_target, execution_type, is_seed_managed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workflow_id,
                        code,
                        p["name"],
                        p.get("description") or "",
                        p.get("min_time_min", 0),
                        p["phase_order"],
                        seed_agent_id,
                        p.get("next_recommendation"),
                        p.get("parallel_with"),
                        p.get("rollback_target"),
                        p.get("execution_type", "sync"),
                        1,
                    ),
                )
                phase_int_id = conn.execute("SELECT id FROM phases WHERE code = ?", (code,)).fetchone()[0]
                for inst in p.get("instructions", []):
                    raw_skills = inst.get("skills")
                    skills_payload = json.dumps(raw_skills, ensure_ascii=False) if isinstance(raw_skills, list) else raw_skills
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
                            skills_payload,
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
                SELECT phases.*, workflows.name AS workflow_name, workflows.description AS workflow_description, workflows.is_default AS workflow_is_default
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
                    SELECT phases.*, workflows.name AS workflow_name, workflows.description AS workflow_description, workflows.is_default AS workflow_is_default
                    FROM phases
                    JOIN workflows ON workflows.id = phases.workflow_id
                    WHERE phases.id = ?
                    """,
                    (phase_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT phases.*, workflows.name AS workflow_name, workflows.description AS workflow_description, workflows.is_default AS workflow_is_default
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
                SELECT phases.*, workflows.name AS workflow_name, workflows.description AS workflow_description, workflows.is_default AS workflow_is_default
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
            workflow_id = self._resolve_workflow_id(data.get("workflow_id", data.get("workflow", data.get("workflow_code"))))
            c = conn.execute(
                """
                INSERT INTO phases (workflow_id, code, name, description, min_time_min, phase_order, agent_id,
                                    next_recommendation, parallel_with, rollback_target, execution_type, is_seed_managed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    data.get("code", data.get("id", "")),
                    data["name"],
                    data.get("description") or "",
                    data.get("min_time_min", 0),
                    data["phase_order"],
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
            if k in {"workflow_id", "workflow", "workflow_code"}:
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
                    str(data.get("current_phase", "-1")),
                    data.get("status", "active"),
                ),
            )
            conn.commit()
            return c.lastrowid or 0

    def get_tasks(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT tasks.*, projects.code AS project_code, projects.name AS project_name,
                       projects.workflow_id AS workflow_id, workflows.name AS workflow_name
                FROM tasks
                JOIN projects ON projects.id = tasks.project_id
                LEFT JOIN workflows ON workflows.id = projects.workflow_id
                ORDER BY tasks.updated_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]

    def get_task(self, task_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT tasks.*, projects.code AS project_code, projects.name AS project_name,
                       projects.workflow_id AS workflow_id, workflows.name AS workflow_name
                FROM tasks
                JOIN projects ON projects.id = tasks.project_id
                LEFT JOIN workflows ON workflows.id = projects.workflow_id
                WHERE tasks.id = ?
                """,
                (task_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_task_by_key(self, task_key: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT tasks.*, projects.code AS project_code, projects.name AS project_name,
                       projects.workflow_id AS workflow_id, workflows.name AS workflow_name
                FROM tasks
                JOIN projects ON projects.id = tasks.project_id
                LEFT JOIN workflows ON workflows.id = projects.workflow_id
                WHERE tasks.task_key = ?
                """,
                (task_key,),
            ).fetchone()
            return dict(row) if row else None

    def _resolve_task_id(self, value: int | str) -> int:
        if isinstance(value, int):
            return value
        task = self.get_task_by_key(value)
        if not task:
            raise ValueError(f"Unknown task key: {value}")
        return int(task["id"])

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

    # ── Supervisor Runs ───────────────────────────────────────────────

    def create_supervisor_run(self, data: dict) -> int:
        task_id = data.get("task_id")
        if task_id is None:
            task_key = data.get("task_key")
            if task_key is None:
                raise ValueError("task_id or task_key is required")
            task_id = self._resolve_task_id(task_key)
        phase_id = self._resolve_phase_id(data["phase_id"])
        next_phase_id = data.get("next_phase_id")
        rollback_phase_id = data.get("rollback_phase_id")
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO supervisor_runs (
                    task_id, phase_id, verdict, report, covered, missing, blockers,
                    next_phase_id, rollback_phase_id, context_snapshot, response
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(task_id),
                    phase_id,
                    str(data["verdict"]),
                    str(data.get("report", "") or ""),
                    self._json_dumps(data.get("covered", []), fallback="[]"),
                    self._json_dumps(data.get("missing", []), fallback="[]"),
                    self._json_dumps(data.get("blockers", []), fallback="[]"),
                    self._resolve_phase_id(next_phase_id) if next_phase_id is not None else None,
                    self._resolve_phase_id(rollback_phase_id) if rollback_phase_id is not None else None,
                    self._json_dumps(data.get("context_snapshot", {}), fallback="{}"),
                    self._json_dumps(data.get("response", {}), fallback="{}"),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid or 0)

    def get_supervisor_runs(
        self,
        *,
        task_id: int | None = None,
        task_key: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        if task_id is None:
            if task_key is None:
                raise ValueError("task_id or task_key is required")
            task_id = self._resolve_task_id(task_key)
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT supervisor_runs.*, phases.code AS phase_code,
                       next_phase.code AS next_phase_code,
                       rollback_phase.code AS rollback_phase_code,
                       tasks.task_key AS task_key
                FROM supervisor_runs
                JOIN phases ON phases.id = supervisor_runs.phase_id
                JOIN tasks ON tasks.id = supervisor_runs.task_id
                LEFT JOIN phases AS next_phase ON next_phase.id = supervisor_runs.next_phase_id
                LEFT JOIN phases AS rollback_phase ON rollback_phase.id = supervisor_runs.rollback_phase_id
                WHERE supervisor_runs.task_id = ?
                ORDER BY supervisor_runs.created_at DESC, supervisor_runs.id DESC
                LIMIT ?
                """,
                (int(task_id), int(limit)),
            ).fetchall()
            hydrated: list[dict] = []
            for row in rows:
                item = self._hydrate_supervisor_run_row(row)
                if item is not None:
                    hydrated.append(item)
            return hydrated

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
