"""Application services — use cases."""

from __future__ import annotations

import re
from typing import Any

from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork


class AgentService:
    """Use cases for agents."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    @staticmethod
    def _normalize_profile(profile: Any) -> str | None:
        value = str(profile or "").strip()
        if not value:
            return None
        if len(value) > 251 or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
            raise ValueError("Hermes profile must match [a-z0-9][a-z0-9_-]* and be at most 251 characters")
        return value

    def _validate_profile_owner(self, profile: str | None, *, agent_id: int | None = None) -> None:
        if not profile:
            return
        owner = self._uow.agents.get_by_hermes_profile(profile)
        if owner is not None and owner.id != agent_id:
            raise ConflictError(f"Hermes profile {profile!r} is already assigned to agent {owner.name!r}")

    def create_agent(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        if "hermes_profile" in payload:
            payload["hermes_profile"] = self._normalize_profile(payload["hermes_profile"])
        self._validate_profile_owner(payload.get("hermes_profile"))
        aid = self._uow.agents.create(payload)
        agent = self._uow.agents.get_by_id(aid)
        if not agent:
            raise RuntimeError("Agent creation failed")
        self._uow.commit()
        return agent.to_dict()

    def list_agents(self) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self._uow.agents.list()]

    def get_agent(self, agent_id: int) -> dict[str, Any] | None:
        a = self._uow.agents.get_by_id(agent_id)
        return a.to_dict() if a else None

    def update_agent(self, agent_id: int, data: dict[str, Any]) -> None:
        payload = dict(data)
        if "hermes_profile" in payload:
            payload["hermes_profile"] = self._normalize_profile(payload["hermes_profile"])
        self._validate_profile_owner(payload.get("hermes_profile"), agent_id=agent_id)
        self._uow.agents.update(agent_id, payload)
        self._uow.commit()
        return None

    def delete_agent(self, agent_id: int) -> None:
        self._uow.agents.delete(agent_id)
        self._uow.commit()
        return None
