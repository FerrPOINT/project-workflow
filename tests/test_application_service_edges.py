"""Negative branch coverage for application services."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from project_workflow.application.agent import AgentService
from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.project import ProjectService
from project_workflow.domain.exceptions import ConflictError, NotFoundError

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("profile", [42, "", "UPPER", "bad profile"])
def test_agent_profile_validation_rejects_invalid_values(profile):
    with pytest.raises(ValueError):
        AgentService._normalize_profile(profile)


def test_agent_create_rolls_back_when_created_row_cannot_be_read():
    uow = MagicMock()
    uow.agents.get_by_name.return_value = None
    uow.agents.get_by_hermes_profile.return_value = None
    uow.agents.create.return_value = 10
    uow.agents.get_by_id.return_value = None

    with pytest.raises(RuntimeError, match="Не удалось создать агента"):
        AgentService(uow).create_agent({"name": "Review"})

    uow.rollback.assert_called_once_with()
    uow.commit.assert_not_called()


def test_agent_update_locks_assigned_workflows_before_write():
    owner = SimpleNamespace(id=7, name="Reviewer")
    uow = MagicMock()
    uow.agents.lock.return_value = owner
    uow.phases.workflow_ids_for_agent.return_value = [3, 3, 2]
    uow.workflows.lock.side_effect = lambda workflow_id: SimpleNamespace(id=workflow_id)
    uow.agents.get_by_hermes_profile.return_value = owner

    AgentService(uow).update_agent(7, {"hermes_profile": "review_profile"})

    assert [call.args[0] for call in uow.workflows.lock.call_args_list] == [2, 3]
    uow.agents.update.assert_called_once_with(7, {"hermes_profile": "review_profile"})


@pytest.mark.parametrize("raw", ["bad", [""]])
def test_project_prefix_normalization_rejects_invalid_shapes(raw):
    with pytest.raises(ValueError):
        ProjectService._normalized_prefixes(raw)


def test_project_prefix_normalization_allows_empty_legacy_list():
    assert ProjectService._normalized_prefixes([]) == []


def test_project_prefix_normalization_rejects_duplicates():
    with pytest.raises(ConflictError):
        ProjectService._normalized_prefixes(["run", "RUN"])


def test_project_update_allows_legacy_prefix_change_with_existing_task():
    existing = SimpleNamespace(id=4, code="RUN", workflow_id=1, key_prefixes=["RUN"])
    task = SimpleNamespace(task_key="RUN-42")
    uow = MagicMock()
    uow.projects.get_by_id.return_value = existing
    uow.projects.lock.return_value = existing
    uow.workflows.lock.return_value = SimpleNamespace(id=1)
    uow.projects.list.return_value = [existing]
    uow.tasks.list_by_project.return_value = [task]

    ProjectService(uow).update_project(4, {"key_prefixes": ["NEW"]})

    uow.projects.update.assert_called_once_with(4, {"key_prefixes": ["NEW"]})


def test_instruction_lock_rejects_phase_removed_after_workflow_lock():
    instruction = {"id": 5, "phase_id": 9, "description": "Step"}
    phase = SimpleNamespace(id=9, workflow_id=3)
    uow = MagicMock()
    uow.phase_instructions.get_by_id.return_value = instruction
    uow.phases.get_by_id.return_value = phase
    uow.workflows.lock.return_value = SimpleNamespace(id=3)
    uow.phases.list.return_value = []

    with pytest.raises(NotFoundError, match="Фаза 9 не найдена"):
        InstructionService(uow).update_instruction(5, {"description": "New"})

    uow.phase_instructions.update.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        {"parallel_with_phase_id": True},
        {"rollback_target_phase_id": 0},
        {"parallel_with_phase_id": "2"},
    ],
)
def test_phase_link_normalization_rejects_non_positive_or_non_integer_values(data):
    with pytest.raises(ValueError):
        PhaseServiceApp._normalize_links(data)
