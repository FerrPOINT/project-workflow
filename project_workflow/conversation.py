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
from typing import List, Optional

DB_DIR = Path.home() / ".project-workflow"
DB_PATH = DB_DIR / "conversation.db"


@dataclass
class Message:
    id: int
    task_id: str          # internal task_id (e.g. "TASKNEIROKLYUCH-42")
    task_key: str         # e.g. "AAT-123"
    role: str             # user | system | wizard | agent
    content: str
    phase_id: Optional[str] = None
    tags: Optional[str] = None   # comma-separated tags: done,fail,changelog,auto
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
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SQL_INIT)
    conn.row_factory = sqlite3.Row
    return conn


# ── Write ───────────────────────────────────────────────────────────────

def add_message(
    task_id: str,
    task_key: str,
    role: str,
    content: str,
    phase_id: Optional[str] = None,
    tags: Optional[str] = None,
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


def add_user_note(task_id: str, task_key: str, content: str, phase_id: Optional[str] = None) -> int:
    """Быстрый entrypoint для пользовательского отчёта."""
    return add_message(task_id, task_key, "user", content, phase_id, tags="note")


def add_phase_transition(task_id: str, task_key: str, from_phase: str, to_phase: str) -> None:
    """Записать переход фазы в историю."""
    add_message(
        task_id, task_key, "system",
        f"Phase transition: {from_phase} → {to_phase}",
        phase_id=to_phase,
        tags="transition",
    )


def add_wizard_question(task_id: str, task_key: str, phase_id: str, question: str) -> None:
    add_message(task_id, task_key, "wizard", question, phase_id, tags="question")


def add_wizard_answer(task_id: str, task_key: str, phase_id: str, answer: str, ok: bool) -> None:
    tag = "pass" if ok else "fail"
    add_message(task_id, task_key, "user", answer, phase_id, tags=tag)


# ── Read ──────────────────────────────────────────────────────────────

def get_messages(
    task_id: str,
    limit: Optional[int] = 200,
    phase_id: Optional[str] = None,
    tags: Optional[str] = None,
) -> List[Message]:
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


def get_latest_user_notes(task_id: str, limit: int = 20) -> List[Message]:
    """Последние пользовательские отчёты по задаче."""
    return get_messages(task_id, limit=limit, tags="note")


def get_last_phase(task_id: str) -> Optional[str]:
    """Последняя известная фаза из истории."""
    conn = _ensure_db()
    try:
        row = conn.execute(
            "SELECT phase_id FROM conversation WHERE task_id = ? AND phase_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return row["phase_id"] if row else None
    finally:
        conn.close()


def check_keyword_in_history(task_id: str, keyword: str, limit: int = 100) -> bool:
    """Проверить было ли keyword в истории (case-insensitive)."""
    conn = _ensure_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM conversation WHERE task_id = ? AND content LIKE ? LIMIT 1",
            (task_id, f"%{keyword}%"),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


# ── Summary / Digest ──────────────────────────────────────────────────

def build_status_digest(task_id: str, task_key: str, current_phase: Optional[str] = None) -> dict:
    """Собрать краткий дайджест статуса из истории."""
    notes = get_messages(task_id, limit=50)
    phase_transitions = [m for m in notes if m.tags == "transition"]
    last_phase = current_phase or (phase_transitions[-1].phase_id if phase_transitions else None)

    # Какие keywords были упомянуты (простой heuristic)
    content_all = " ".join(m.content.lower() for m in notes)
    has_changelog = "changelog" in content_all
    has_progress = "progress" in content_all or "progress.json" in content_all
    has_info = "info/" in content_all or "info " in content_all

    return {
        "task_id": task_id,
        "task_key": task_key,
        "last_phase": last_phase,
        "total_messages": len(notes),
        "transitions_count": len(phase_transitions),
        "has_changelog": has_changelog,
        "has_progress": has_progress,
        "has_info": has_info,
        "latest_notes": [m.content[:120] for m in notes if m.role == "user"][-5:],
    }
