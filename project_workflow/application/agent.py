"""Application services — use cases."""
from __future__ import annotations

from typing import Any

from project_workflow.domain.repositories import UnitOfWork


class AgentService:
    """Use cases for agents."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    def create_agent(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._uow:
            aid = self._uow.agents.create(data)
            agent = self._uow.agents.get_by_id(aid)
            if not agent:
                raise RuntimeError("Agent creation failed")
            return agent.to_dict()

    def list_agents(self) -> list[dict[str, Any]]:
        with self._uow:
            return [a.to_dict() for a in self._uow.agents.list()]

    def get_agent(self, agent_id: int) -> dict[str, Any] | None:
        with self._uow:
            a = self._uow.agents.get_by_id(agent_id)
            return a.to_dict() if a else None

    def update_agent(self, agent_id: int, data: dict[str, Any]) -> None:
        with self._uow:
            self._uow.agents.update(agent_id, data)
            return None

    def delete_agent(self, agent_id: int) -> None:
        with self._uow:
            self._uow.agents.delete(agent_id)
            return None

