"""SQLAlchemy repository implementations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from project_workflow.infrastructure.db import models as m


class SACLIHistoryRepository:
    """SQLAlchemy repository for CLI call history."""

    def __init__(self, session: Session):
        self._session = session

    def list(self, limit: int = 200) -> Sequence[dict[str, Any]]:
        rows = self._session.execute(select(m.CliHistory).order_by(m.CliHistory.id.asc()).limit(limit)).scalars().all()
        return [m.model_to_dict(r) for r in rows]

    def create(
        self,
        command: str,
        task_key: str | None = None,
        request: str | None = None,
        response: str | None = None,
    ) -> int:
        item = m.CliHistory(
            command=command,
            task_key=task_key,
            request=request,
            response=response,
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)


def _parse_skills(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return [str(s) for s in parsed] if isinstance(parsed, list) else []
    except Exception:
        return []


def _dump_skills(skills: Any) -> str | None:
    if skills in (None, [], ""):
        return None
    if isinstance(skills, str):
        return skills
    return json.dumps([str(s) for s in skills], ensure_ascii=False)
