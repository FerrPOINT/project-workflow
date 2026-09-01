"""Negative branch coverage for application services."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from project_workflow.application.agent import AgentService
from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.project import ProjectService
from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
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


def test_workflow_create_rolls_back_when_default_phase_fails():
    uow = MagicMock()
    uow.workflows.create.return_value = 11
    uow.phases.create.side_effect = RuntimeError("phase write failed")

    with pytest.raises(RuntimeError, match="phase write failed"):
        WorkflowService(uow).create_workflow({"name": "Broken workflow"})

    uow.rollback.assert_called_once_with()
    uow.commit.assert_not_called()


def test_project_create_rolls_back_when_created_row_cannot_be_read():
    uow = MagicMock()
    uow.workflows.lock.return_value = SimpleNamespace(id=3)
    uow.projects.get_by_code.return_value = None
    uow.projects.get_by_cli_command.return_value = None
    uow.projects.create.return_value = 12
    uow.projects.get_by_id.return_value = None

    with pytest.raises(RuntimeError, match="Не удалось создать неймспейс"):
        ProjectService(uow).create_project(
            {
                "code": "ROLLBACK",
                "name": "Rollback namespace",
                "workflow_id": 3,
                "cli_command": "workflow-rollback",
            }
        )

    uow.rollback.assert_called_once_with()
    uow.commit.assert_not_called()


def test_task_create_rolls_back_when_created_row_cannot_be_read():
    namespace = SimpleNamespace(id=5, workflow_id=3)
    phase = SimpleNamespace(id=9)
    uow = MagicMock()
    uow.projects.get_by_id.return_value = namespace
    uow.projects.lock.return_value = namespace
    uow.workflows.lock.return_value = SimpleNamespace(id=3)
    uow.phases.list.return_value = [phase]
    uow.tasks.get_by_key.return_value = None
    uow.tasks.create.return_value = 44
    uow.tasks.get_by_id.return_value = None

    with pytest.raises(RuntimeError, match="Не удалось создать задачу"):
        TaskService(uow).create_task({"project_id": 5, "task_key": "RUN-44"})

    uow.rollback.assert_called_once_with()
    uow.commit.assert_not_called()


def test_phase_create_rolls_back_when_created_row_cannot_be_read():
    uow = _phase_create_uow()
    uow.phases.get_by_id.return_value = None

    with pytest.raises(RuntimeError, match="Не удалось создать фазу"):
        PhaseServiceApp(uow).create_phase({"workflow_id": 1, "phase_order": 1, "name": "Broken phase"})

    uow.rollback.assert_called_once_with()
    uow.commit.assert_not_called()


def test_phase_create_commit_false_leaves_rollback_to_outer_owner():
    uow = _phase_create_uow()
    uow.phases.get_by_id.return_value = None

    with pytest.raises(RuntimeError, match="Не удалось создать фазу"):
        PhaseServiceApp(uow).create_phase(
            {"workflow_id": 1, "phase_order": 1, "name": "Broken phase"},
            commit=False,
        )

    uow.rollback.assert_not_called()
    uow.commit.assert_not_called()


def test_phase_update_rolls_back_when_direct_write_fails():
    phase = SimpleNamespace(
        id=7,
        workflow_id=3,
        code="P1",
        phase_order=1,
        execution_type="sync",
        parallel_with_phase_id=None,
        rollback_target_phase_id=None,
    )
    uow = MagicMock()
    uow.phases.get_by_id.return_value = phase
    uow.workflows.lock.return_value = SimpleNamespace(id=3)
    uow.phases.list.return_value = [phase]
    uow.phases.update.side_effect = RuntimeError("phase update failed")

    with pytest.raises(RuntimeError, match="phase update failed"):
        PhaseServiceApp(uow).update_phase(7, {"name": "Updated"})

    uow.rollback.assert_called_once_with()
    uow.commit.assert_not_called()


def test_phase_delete_rolls_back_when_direct_delete_fails():
    phase = SimpleNamespace(id=7, workflow_id=3)
    uow = MagicMock()
    uow.phases.get_by_id.return_value = phase
    uow.workflows.lock.return_value = SimpleNamespace(id=3)
    uow.phases.reference_kinds.return_value = []
    uow.phases.delete.side_effect = RuntimeError("phase delete failed")

    with pytest.raises(RuntimeError, match="phase delete failed"):
        PhaseServiceApp(uow).delete_phase(7)

    uow.rollback.assert_called_once_with()
    uow.commit.assert_not_called()


def test_phase_reorder_rolls_back_when_direct_reorder_fails():
    first = SimpleNamespace(
        id=7,
        workflow_id=3,
        code="P1",
        phase_order=1,
        execution_type="sync",
        parallel_with_phase_id=None,
        rollback_target_phase_id=None,
    )
    second = SimpleNamespace(
        id=8,
        workflow_id=3,
        code="P2",
        phase_order=2,
        execution_type="sync",
        parallel_with_phase_id=None,
        rollback_target_phase_id=None,
    )
    uow = MagicMock()
    uow.phases.get_by_id.side_effect = lambda phase_id: {7: first, 8: second}.get(phase_id)
    uow.workflows.lock.return_value = SimpleNamespace(id=3)
    uow.phases.list.return_value = [first, second]
    uow.phases.reorder.side_effect = RuntimeError("phase reorder failed")

    with pytest.raises(RuntimeError, match="phase reorder failed"):
        PhaseServiceApp(uow).reorder_phases([(7, 2), (8, 1)])

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


def test_project_update_rolls_back_when_write_fails():
    existing = SimpleNamespace(id=4, code="RUN", workflow_id=1, cli_command="workflow-run")
    uow = MagicMock()
    uow.projects.get_by_id.return_value = existing
    uow.projects.lock.return_value = existing
    uow.workflows.lock.return_value = SimpleNamespace(id=1)
    uow.tasks.list_by_project.return_value = []
    uow.projects.update.side_effect = RuntimeError("update failed")

    with pytest.raises(RuntimeError, match="update failed"):
        ProjectService(uow).update_project(4, {"name": "Updated"})

    uow.rollback.assert_called_once_with()
    uow.commit.assert_not_called()


def test_project_delete_rolls_back_when_delete_fails():
    existing = SimpleNamespace(id=4, code="RUN", workflow_id=1, cli_command="workflow-run")
    uow = MagicMock()
    uow.projects.get_by_id.return_value = existing
    uow.projects.lock.return_value = existing
    uow.workflows.lock.return_value = SimpleNamespace(id=1)
    uow.tasks.list_by_project.return_value = []
    uow.projects.delete.side_effect = RuntimeError("delete failed")

    with pytest.raises(RuntimeError, match="delete failed"):
        ProjectService(uow).delete_project(4)

    uow.rollback.assert_called_once_with()
    uow.commit.assert_not_called()


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


@pytest.mark.parametrize("agent_id", [True, 0, -1, "1"])
def test_phase_agent_validation_rejects_non_positive_or_non_integer_values(agent_id):
    uow = MagicMock()

    with pytest.raises(ValueError, match="agent_id"):
        PhaseServiceApp(uow)._validate_agent(agent_id)

    uow.agents.lock.assert_not_called()


def _phase_create_uow() -> MagicMock:
    uow = MagicMock()
    uow.workflows.lock.return_value = SimpleNamespace(id=1)
    uow.phases.list.return_value = []
    uow.phases.create.return_value = 7
    created = SimpleNamespace(to_dict=lambda: {"id": 7})
    uow.phases.get_by_id.return_value = created
    return uow


@pytest.mark.parametrize("workflow_id", [True, 0, -1, "1"])
def test_phase_create_rejects_non_positive_or_non_integer_workflow_id(workflow_id):
    uow = _phase_create_uow()

    with pytest.raises(ValueError, match="workflow_id"):
        PhaseServiceApp(uow).create_phase(
            {"workflow_id": workflow_id, "phase_order": 1, "name": "Phase"}
        )

    uow.workflows.lock.assert_not_called()
    uow.phases.create.assert_not_called()


@pytest.mark.parametrize("phase_order", [True, 0, -1, "1"])
def test_phase_create_rejects_non_positive_or_non_integer_phase_order(phase_order):
    uow = _phase_create_uow()

    with pytest.raises(ValueError, match="phase_order"):
        PhaseServiceApp(uow).create_phase(
            {"workflow_id": 1, "phase_order": phase_order, "name": "Phase"}
        )

    uow.phases.create.assert_not_called()
