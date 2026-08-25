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
            raise ValueError("Профиль Hermes должен быть строкой или null")
        value = profile.strip()
        if not value:
            raise ValueError("Профиль Hermes не может быть пустым")
        if len(value) > 251 or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
            raise ValueError(
                "Профиль Hermes должен соответствовать [a-z0-9][a-z0-9_-]* "
                "и содержать не более 251 символа"
            )
        return value

    def _validate_profile_owner(self, profile: str | None, *, agent_id: int | None = None) -> None:
        if not profile:
            return
        owner = self._uow.agents.get_by_hermes_profile(profile)
        if owner is not None and owner.id != agent_id:
            raise ConflictError(f"Профиль Hermes {profile!r} уже назначен агенту {owner.name!r}")

    def _ensure_agent_catalog_is_mutable(self, agent_id: int) -> None:
        workflow_ids = sorted(
            {
                int(phase.workflow_id)
                for phase in self._uow.phases.list()
                if phase.agent_id == agent_id and phase.workflow_id is not None
            }
        )
        for workflow_id in workflow_ids:
            workflow = self._uow.workflows.lock(workflow_id)
            if workflow is not None and getattr(workflow, "is_locked", False) is True:
                raise ConflictError("Locked workflow revision agent cannot be changed")

    def create_agent(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        if "hermes_profile" in payload:
            payload["hermes_profile"] = self._normalize_profile(payload["hermes_profile"])
        self._validate_profile_owner(payload.get("hermes_profile"))
        try:
            aid = self._uow.agents.create(payload)
            agent = self._uow.agents.get_by_id(aid)
            if not agent:
                raise RuntimeError("Не удалось создать агента")
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
            raise NotFoundError(f"Агент {agent_id} не найден")
        try:
            self._ensure_agent_catalog_is_mutable(agent_id)
            self._validate_profile_owner(payload.get("hermes_profile"), agent_id=agent_id)
            self._uow.agents.update(agent_id, payload)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return None

    def delete_agent(self, agent_id: int) -> None:
        if self._uow.agents.lock(agent_id) is None:
            raise NotFoundError(f"Агент {agent_id} не найден")
        if self._uow.phases.has_agent_reference(agent_id):
            self._uow.rollback()
            raise ConflictError("Агент назначен фазе, поэтому удалить его нельзя")
        try:
            self._uow.agents.delete(agent_id)
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return None
