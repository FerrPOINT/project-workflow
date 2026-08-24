"""Application services — use cases."""

from __future__ import annotations

import re
from typing import Any

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork


class AgentService:
    """Use cases for agents."""

    def __init__(self, uow: UnitOfWork):
        self._uow = uow

    @staticmethod
    def _normalize_profile(profile: Any) -> str | None:
        if profile is None:
            return None
        if not isinstance(profile, str):
            raise ValueError("Hermes profile must be a string or null")
        value = profile.strip()
        if not value:
            raise ValueError("Hermes profile must not be blank")
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
        try:
            aid = self._uow.agents.create(payload)
            agent = self._uow.agents.get_by_id(aid)
            if not agent:
                raise RuntimeError("Agent creation failed")
            self._uow.commit()
            return agent.to_dict()
        except Exception:
            self._uow.rollback()
            raise

    def list_agents(self) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self._uow.agents.list()]

    def get_agent(self, agent_id: int) -> dict[str, Any] | None:
        a = self._uow.agents.get_by_id(agent_id)
        return a.to_dict() if a else None

    def update_agent(self, agent_id: int, data: dict[str, Any]) -> None:
        payload = dict(data)
        if "hermes_profile" in payload:
            payload["hermes_profile"] = self._normalize_profile(payload["hermes_profile"])
        if self._uow.agents.lock(agent_id) is None:
            raise NotFoundError(f"Agent {agent_id} not found")
        try:
            self._validate_profile_owner(payload.get("hermes_profile"), agent_id=agent_id)
            self._uow.agents.update(agent_id, payload)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return None

    def delete_agent(self, agent_id: int) -> None:
        if self._uow.agents.lock(agent_id) is None:
            raise NotFoundError(f"Agent {agent_id} not found")
        if self._uow.phases.has_agent_reference(agent_id):
            self._uow.rollback()
            raise ConflictError("Agent is assigned to a phase and cannot be deleted")
        try:
            self._uow.agents.delete(agent_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return None
