"""Per-task memory store for the wizard.

Sandboxed: no external access, only DB-backed memory.
"""
from __future__ import annotations

from typing import Any

from project_workflow.infrastructure.db.models import WizardMemory


class MemoryStore:
    """Store and retrieve wizard memories bound to a task."""

    def __init__(self, uow: Any):
        self.uow = uow

    def add(self, task_id: int, memory_type: str, content: str) -> int:
        if memory_type not in {"correction", "lesson", "blocker_pattern", "preference"}:
            raise ValueError(f"Invalid memory_type: {memory_type}")
        session = self.uow.session
        mem = WizardMemory(task_id=task_id, memory_type=memory_type, content=content)
        session.add(mem)
        session.flush()
        return int(mem.id)

    def list_for_task(self, task_id: int, limit: int = 10) -> list[dict[str, Any]]:
        session = self.uow.session
        rows = (
            session.query(WizardMemory)
            .filter(WizardMemory.task_id == task_id)
            .order_by(WizardMemory.created_at.desc(), WizardMemory.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": int(r.id),
                "task_id": int(r.task_id),
                "memory_type": r.memory_type,
                "content": r.content,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    def find_by_type(self, task_id: int, memory_type: str, limit: int = 5) -> list[dict[str, Any]]:
        if memory_type not in {"correction", "lesson", "blocker_pattern", "preference"}:
            raise ValueError(f"Invalid memory_type: {memory_type}")
        session = self.uow.session
        rows = (
            session.query(WizardMemory)
            .filter(WizardMemory.task_id == task_id, WizardMemory.memory_type == memory_type)
            .order_by(WizardMemory.created_at.desc(), WizardMemory.id.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": int(r.id),
                "task_id": int(r.task_id),
                "memory_type": r.memory_type,
                "content": r.content,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    def format_for_prompt(self, task_id: int, limit: int = 5) -> list[str]:
        rows = self.list_for_task(task_id, limit=limit)
        bullets: list[str] = []
        for r in rows:
            bullets.append(f"[{r['memory_type']}] {r['content']}")
        return bullets
