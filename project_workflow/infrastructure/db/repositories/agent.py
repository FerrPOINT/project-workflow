"""SQLAlchemy repository implementations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from project_workflow.domain import Agent
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import AgentRepository
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.converters import _row_to_agent


class SAAgentRepository(AgentRepository):
    """SQLAlchemy implementation of AgentRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self) -> Sequence[Agent]:
        rows = self._session.execute(select(m.Agent).order_by(m.Agent.id)).scalars().all()
        return [_row_to_agent(r) for r in rows]

    def get_by_name(self, name: str) -> Agent | None:
        row = self._session.execute(select(m.Agent).where(m.Agent.name == name)).scalar_one_or_none()
        return _row_to_agent(row) if row else None

    def get_by_id(self, agent_id: int) -> Agent | None:
        row = self._session.get(m.Agent, agent_id)
        return _row_to_agent(row) if row else None

    def get_by_hermes_profile(self, profile: str) -> Agent | None:
        row = self._session.execute(
            select(m.Agent).where(m.Agent.hermes_profile == profile)
        ).scalar_one_or_none()
        return _row_to_agent(row) if row else None

    def lock(self, agent_id: int) -> Agent | None:
        row = self._session.execute(
            select(m.Agent).where(m.Agent.id == agent_id).with_for_update()
        ).scalar_one_or_none()
        return _row_to_agent(row) if row else None

    def _flush_profile(self, profile: str | None) -> None:
        try:
            self._session.flush()
        except IntegrityError as exc:
            label = repr(profile) if profile else "the requested value"
            raise ConflictError(f"Профиль Hermes {label} уже назначен другому агенту") from exc

    def create(self, data: dict[str, Any]) -> int:
        item = m.Agent(
            name=data["name"],
            description=data.get("description", ""),
            hermes_profile=data.get("hermes_profile") or None,
        )
        self._session.add(item)
        self._flush_profile(item.hermes_profile)
        return int(item.id)

    def update(self, agent_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.Agent, agent_id)
        if row is None:
            raise NotFoundError(f"Агент {agent_id} не найден")
        if "name" in data:
            row.name = data["name"]
        if "description" in data:
            row.description = data["description"]
        if "hermes_profile" in data:
            row.hermes_profile = data["hermes_profile"] or None
        self._flush_profile(row.hermes_profile)

    def delete(self, agent_id: int) -> None:
        row = self._session.get(m.Agent, agent_id)
        if row is None:
            raise NotFoundError(f"Агент {agent_id} не найден")
        self._session.delete(row)


