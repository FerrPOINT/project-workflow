"""Conversation History — SQLite persistence for task messages by task ID.

Each task gets a conversation log: user reports what they did,
system notes phase transitions, wizard asks/answers.
This becomes the single source of truth for "что уже сделано".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DB_DIR = Path.home() / ".project-workflow"
DB_PATH = DB_DIR / "conversation.db"


@dataclass
class Message:
    id: int
    task_id: str  # internal task_id (e.g. "TASK-42")
    task_key: str  # e.g. "AAT-123"
    role: str  # user | system | wizard | agent
    content: str
    phase_id: str | None = None
    tags: str | None = None  # comma-separated tags: done,fail,changelog,auto
    created_at: str = ""  # ISO UTC

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "task_key": self.task_key,
            "role": self.role,
            "content": self.content,
            "phase_id": self.phase_id,
            "tags": self.tags,
            "created_at": self.created_at,
        }


# ── DB init ───────────────────────────────────────────────────────────

SQL_INIT = """
CREATE TABLE IF NOT EXISTS conversation (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL,
    task_key    TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    phase_id    TEXT,
    tags        TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_conversation_task ON conversation(task_id);
CREATE INDEX IF NOT EXISTS ix_conversation_phase ON conversation(phase_id);
"""


def _ensure_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SQL_INIT)
    conn.row_factory = sqlite3.Row
    return conn


# ── Write / Read ───────────────────────────────────────────────────────


def add_message(
    task_id: str,
    task_key: str,
    role: str,
    content: str,
    phase_id: str | None = None,
    tags: str | None = None,
) -> int:
    """Добавить сообщение в историю задачи. Возвращает row id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _ensure_db()
    try:
        cur = conn.execute(
            """
            INSERT INTO conversation (task_id, task_key, role, content, phase_id, tags, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, task_key, role, content, phase_id, tags, now),
        )
        conn.commit()
        return cur.lastrowid or 0
    finally:
        conn.close()


def get_messages(
    task_id: str,
    limit: int | None = 200,
    phase_id: str | None = None,
    tags: str | None = None,
) -> list[Message]:
    """Получить историю сообщений по задаче (от новых к старым)."""
    conn = _ensure_db()
    try:
        sql = "SELECT * FROM conversation WHERE task_id = ?"
        params: list = [task_id]
        if phase_id:
            sql += " AND phase_id = ?"
            params.append(phase_id)
        if tags:
            sql += " AND tags LIKE ?"
            params.append(f"%{tags}%")
        sql += " ORDER BY id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [Message(**dict(r)) for r in reversed(rows)]  # chron order
    finally:
        conn.close()
