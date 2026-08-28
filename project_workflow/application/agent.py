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
    def _normalize_name(name: Any) -> str:
        if not isinstance(name, str):
            raise ValueError("Имя агента должно быть строкой")
        value = name.strip()
        if not value:
            raise ValueError("Имя агента не может быть пустым")
        return value

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

    def _validate_name_owner(self, name: str, *, agent_id: int | None = None) -> None:
        owner = self._uow.agents.get_by_name(name)
        if owner is not None and owner.id != agent_id:
            raise ConflictError(f"Агент {name!r} уже существует")

    def _lock_assigned_workflows(self, agent_id: int) -> None:
        """Serialize agent changes with evaluations that read its phase assignments."""
        for workflow_id in sorted(set(self._uow.phases.workflow_ids_for_agent(agent_id))):
            if self._uow.workflows.lock(workflow_id) is None:
                raise NotFoundError(f"Воркфлоу {workflow_id} не найден")

    def create_agent(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        payload["name"] = self._normalize_name(payload.get("name"))
        self._validate_name_owner(payload["name"])
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
        if "name" in payload:
            payload["name"] = self._normalize_name(payload["name"])
        if "hermes_profile" in payload:
            payload["hermes_profile"] = self._normalize_profile(payload["hermes_profile"])
        if self._uow.agents.lock(agent_id) is None:
            raise NotFoundError(f"Агент {agent_id} не найден")
        try:
            self._lock_assigned_workflows(agent_id)
            if "name" in payload:
                self._validate_name_owner(payload["name"], agent_id=agent_id)
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
        self._lock_assigned_workflows(agent_id)
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
