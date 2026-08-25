"""Tests for application.agent.AgentService."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from project_workflow.application.agent import AgentService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork


@dataclass
class FakeAgent:
    id: int
    name: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name}


def _make_uow(agents=None) -> UnitOfWork:
    uow = MagicMock(spec=UnitOfWork)
    uow.agents = agents or MagicMock()
    uow.agents.get_by_hermes_profile.return_value = None
    uow.phases.has_agent_reference.return_value = False
    uow.phases.workflow_ids_for_agent.return_value = []
    return uow


def test_create_agent_success():
    uow = _make_uow()
    uow.agents.create.return_value = 42
    uow.agents.get_by_id.return_value = FakeAgent(42, "Coder")
    svc = AgentService(uow)
    result = svc.create_agent({"name": "Coder"})
    assert result == {"id": 42, "name": "Coder"}
    uow.agents.create.assert_called_once_with({"name": "Coder"})
    uow.agents.get_by_id.assert_called_once_with(42)
    uow.commit.assert_called_once()


def test_create_agent_failure():
    uow = _make_uow()
    uow.agents.create.return_value = 1
    uow.agents.get_by_id.return_value = None
    svc = AgentService(uow)
    with pytest.raises(RuntimeError, match="Не удалось создать агента"):
        svc.create_agent({"name": "Ghost"})


def test_list_agents():
    uow = _make_uow()
    uow.agents.list.return_value = [FakeAgent(1, "A"), FakeAgent(2, "B")]
    svc = AgentService(uow)
    assert svc.list_agents() == [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]


def test_get_agent_found():
    uow = _make_uow()
    uow.agents.get_by_id.return_value = FakeAgent(7, "Find")
    svc = AgentService(uow)
    assert svc.get_agent(7) == {"id": 7, "name": "Find"}


def test_get_agent_not_found():
    uow = _make_uow()
    uow.agents.get_by_id.return_value = None
    svc = AgentService(uow)
    assert svc.get_agent(99) is None


def test_update_agent():
    uow = _make_uow()
    uow.phases.workflow_ids_for_agent.return_value = [7, 3]
    svc = AgentService(uow)
    assert svc.update_agent(3, {"name": "X"}) is None
    assert [call.args[0] for call in uow.workflows.lock.call_args_list] == [3, 7]
    uow.agents.update.assert_called_once_with(3, {"name": "X"})
    uow.commit.assert_called_once()


def test_create_agent_normalizes_hermes_profile():
    uow = _make_uow()
    uow.agents.create.return_value = 42
    uow.agents.get_by_id.return_value = FakeAgent(42, "Coder")

    AgentService(uow).create_agent({"name": "Coder", "hermes_profile": " profile_1 "})

    uow.agents.create.assert_called_once_with({"name": "Coder", "hermes_profile": "profile_1"})


def test_create_agent_rejects_invalid_hermes_profile():
    uow = _make_uow()

    with pytest.raises(ValueError, match="Профиль Hermes"):
        AgentService(uow).create_agent({"name": "Coder", "hermes_profile": "Bad Profile"})


def test_hermes_profile_must_have_one_agent_owner():
    uow = _make_uow()
    uow.agents.get_by_hermes_profile.return_value = FakeAgent(7, "Existing")

    with pytest.raises(ConflictError, match="уже назначен"):
        AgentService(uow).create_agent({"name": "Other", "hermes_profile": "shared"})

    uow.agents.create.assert_not_called()


def test_agent_can_keep_own_hermes_profile():
    uow = _make_uow()
    uow.agents.get_by_hermes_profile.return_value = FakeAgent(7, "Existing")

    AgentService(uow).update_agent(7, {"hermes_profile": "shared"})

    uow.agents.update.assert_called_once_with(7, {"hermes_profile": "shared"})


def test_delete_agent():
    uow = _make_uow()
    svc = AgentService(uow)
    assert svc.delete_agent(5) is None
    uow.agents.delete.assert_called_once_with(5)
    uow.commit.assert_called_once()


def test_delete_assigned_agent_is_conflict_and_rolls_back():
    uow = _make_uow()
    uow.phases.has_agent_reference.return_value = True

    with pytest.raises(ConflictError, match="назначен фазе"):
        AgentService(uow).delete_agent(5)

    uow.agents.delete.assert_not_called()
    uow.rollback.assert_called_once_with()
