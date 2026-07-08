"""Tests for application.agent.AgentService."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from project_workflow.application.agent import AgentService
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
    with pytest.raises(RuntimeError, match="Agent creation failed"):
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
    svc = AgentService(uow)
    assert svc.update_agent(3, {"name": "X"}) is None
    uow.agents.update.assert_called_once_with(3, {"name": "X"})
    uow.commit.assert_called_once()


def test_delete_agent():
    uow = _make_uow()
    svc = AgentService(uow)
    assert svc.delete_agent(5) is None
    uow.agents.delete.assert_called_once_with(5)
    uow.commit.assert_called_once()
