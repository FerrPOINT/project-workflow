"""Tests for application layer services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.project import ProjectService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork


@dataclass
class FakeWorkflow:
    id: int = 1
    name: str = "W"
    is_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name}


@dataclass
class FakeProject:
    id: int
    code: str
    workflow_id: int

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "code": self.code, "workflow_id": self.workflow_id}


@dataclass
class FakeTask:
    id: int
    project_id: int


def _make_uow() -> UnitOfWork:
    uow = MagicMock(spec=UnitOfWork)
    uow.phase_instructions = MagicMock()
    uow.projects = MagicMock()
    uow.tasks = MagicMock()
    uow.workflows = MagicMock()
    uow.phases = MagicMock()
    uow.projects.get_by_code.return_value = None
    uow.projects.list.return_value = []
    return uow


class TestInstructionService:
    def test_list_instructions(self):
        uow = _make_uow()
        uow.phase_instructions.list.return_value = [{"id": 1, "description": "D"}]
        svc = InstructionService(uow)
        assert svc.list_instructions(7) == [{"id": 1, "description": "D"}]

    def test_get_instruction(self):
        uow = _make_uow()
        uow.phase_instructions.get_by_id.return_value = {"id": 2, "description": "X"}
        svc = InstructionService(uow)
        assert svc.get_instruction(2) == {"id": 2, "description": "X"}

    def test_create_instruction_success(self):
        uow = _make_uow()
        phase = MagicMock(id=3, workflow_id=7)
        uow.phases.get_by_id.return_value = phase
        uow.phases.list.return_value = [phase]
        uow.phase_instructions.create.return_value = 5
        uow.phase_instructions.get_by_id.return_value = {"id": 5, "description": "Y"}
        svc = InstructionService(uow)
        assert svc.create_instruction(3, {"description": "Y"}) == {"id": 5, "description": "Y"}
        uow.phase_instructions.create.assert_called_once_with(3, {"description": "Y"})
        uow.commit.assert_called_once()

    def test_create_instruction_inserts_at_requested_step(self):
        uow = _make_uow()
        phase = MagicMock(id=3, workflow_id=7)
        uow.phases.get_by_id.return_value = phase
        uow.phases.list.return_value = [phase]
        uow.phase_instructions.list.return_value = [{"id": 10}, {"id": 20}]
        uow.phase_instructions.create.return_value = 30
        uow.phase_instructions.get_by_id.return_value = {"id": 30, "description": "Y"}

        result = InstructionService(uow).create_instruction(
            3, {"description": "Y", "step_num": 2}
        )

        assert result == {"id": 30, "description": "Y"}
        uow.phase_instructions.create.assert_called_once_with(3, {"description": "Y"})
        uow.phase_instructions.reorder.assert_called_once_with(3, [(10, 1), (30, 2), (20, 3)])
        uow.commit.assert_called_once()

    def test_create_instruction_failure(self):
        uow = _make_uow()
        phase = MagicMock(id=1, workflow_id=7)
        uow.phases.get_by_id.return_value = phase
        uow.phases.list.return_value = [phase]
        uow.phase_instructions.create.return_value = 1
        uow.phase_instructions.get_by_id.return_value = None
        svc = InstructionService(uow)
        with pytest.raises(RuntimeError, match="Не удалось создать инструкцию"):
            svc.create_instruction(1, {})

    @pytest.mark.parametrize(
        ("phase", "locked_workflow", "listed_phases", "message"),
        [
            (None, MagicMock(), [], "Фаза 3 не найдена"),
            (MagicMock(id=3, workflow_id=7), None, [], "Воркфлоу 7 не найден"),
            (MagicMock(id=3, workflow_id=7), MagicMock(), [], "Фаза 3 не найдена"),
        ],
    )
    def test_create_instruction_rechecks_locked_owners(
        self, phase, locked_workflow, listed_phases, message
    ):
        uow = _make_uow()
        uow.phases.get_by_id.return_value = phase
        uow.workflows.lock.return_value = locked_workflow
        uow.phases.list.return_value = listed_phases

        with pytest.raises(NotFoundError, match=message):
            InstructionService(uow).create_instruction(3, {"description": "Y"})

        uow.phase_instructions.create.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.parametrize("step_num", ["2", True, 1.5, "second"])
    def test_create_instruction_rejects_non_numeric_internal_step(self, step_num):
        uow = _make_uow()
        phase = MagicMock(id=3, workflow_id=7)
        uow.phases.get_by_id.return_value = phase
        uow.phases.list.return_value = [phase]

        with pytest.raises(ValueError, match="step_num должен быть положительным целым числом"):
            InstructionService(uow).create_instruction(
                3, {"description": "Y", "step_num": step_num}
            )

        uow.phase_instructions.create.assert_not_called()
        uow.commit.assert_not_called()

    def test_update_and_delete_instruction(self):
        uow = _make_uow()
        phase = MagicMock(id=10, workflow_id=7)
        uow.phases.get_by_id.return_value = phase
        uow.phases.list.return_value = [phase]
        uow.phase_instructions.get_by_id.return_value = {"id": 2, "phase_id": 10}
        uow.phase_instructions.list.return_value = [{"id": 2}, {"id": 3}]
        svc = InstructionService(uow)
        assert svc.update_instruction(2, {"description": "Z"}) is None
        assert svc.delete_instruction(2) is None
        uow.phase_instructions.update.assert_called_once_with(2, {"description": "Z"})
        uow.phase_instructions.delete.assert_called_once_with(2)
        uow.phase_instructions.reorder.assert_called_once_with(10, [(3, 1)])
        assert uow.commit.call_count == 2

    def test_reorder_instructions(self):
        uow = _make_uow()
        phase = MagicMock(id=10, workflow_id=7)
        uow.phases.get_by_id.return_value = phase
        uow.phases.list.return_value = [phase]
        uow.phase_instructions.list.return_value = [{"id": 3}, {"id": 1}, {"id": 2}]
        svc = InstructionService(uow)
        svc.reorder_instructions(10, [2, 3, 1])
        uow.phase_instructions.reorder.assert_called_once_with(10, [(2, 1), (3, 2), (1, 3)])
        uow.commit.assert_called_once()

    def test_reorder_instructions_rejects_partial_set(self):
        uow = _make_uow()
        phase = MagicMock(id=10, workflow_id=7)
        uow.phases.get_by_id.return_value = phase
        uow.phases.list.return_value = [phase]
        uow.phase_instructions.list.return_value = [{"id": 3}, {"id": 1}, {"id": 2}]

        with pytest.raises(ConflictError, match="полный набор"):
            InstructionService(uow).reorder_instructions(10, [2, 3])

        uow.phase_instructions.reorder.assert_not_called()
        uow.commit.assert_not_called()

    @pytest.mark.parametrize("instruction_ids", [[True, 2, 3], ["1", 2, 3], [0, 2, 3]])
    def test_reorder_instructions_rejects_non_strict_ids(self, instruction_ids):
        uow = _make_uow()
        phase = MagicMock(id=10, workflow_id=7)
        uow.phases.get_by_id.return_value = phase
        uow.phases.list.return_value = [phase]
        uow.phase_instructions.list.return_value = [{"id": 3}, {"id": 1}, {"id": 2}]

        with pytest.raises(ValueError, match="положительные целые числа"):
            InstructionService(uow).reorder_instructions(10, instruction_ids)

        uow.phase_instructions.reorder.assert_not_called()
        uow.commit.assert_not_called()


class TestProjectService:
    def test_create_project_requires_explicit_workflow(self):
        uow = _make_uow()
        svc = ProjectService(uow)
        with pytest.raises(ValueError, match="workflow_id неймспейса"):
            svc.create_project({"code": "PRJ", "key_prefixes": ["PRJ"]})
        uow.workflows.ensure_default_exists.assert_not_called()
        uow.projects.create.assert_not_called()
        uow.commit.assert_not_called()

    def test_create_project_with_workflow_id(self):
        uow = _make_uow()
        uow.projects.create.return_value = 9
        uow.projects.get_by_id.return_value = FakeProject(9, "P2", 10)
        svc = ProjectService(uow)
        svc.create_project(
            {"code": "P2", "workflow_id": 10, "name": "", "key_prefixes": ["P2"]}
        )
        args, kwargs = uow.projects.create.call_args
        payload = args[0] if args else kwargs
        assert payload["workflow_id"] == 10
        assert payload["name"] == "P2"

    def test_list_get_update_delete(self):
        uow = _make_uow()
        uow.projects.list.return_value = [FakeProject(1, "A", 1)]
        uow.projects.get_by_id.return_value = FakeProject(1, "A", 1)
        uow.projects.lock.return_value = FakeProject(1, "A", 1)
        uow.tasks.list_by_project.return_value = []
        svc = ProjectService(uow)
        assert svc.list_projects() == [{"id": 1, "code": "A", "workflow_id": 1}]
        assert svc.get_project(1) == {"id": 1, "code": "A", "workflow_id": 1}
        assert svc.update_project(1, {"name": "B"}) is None
        assert svc.delete_project(1) is None
        uow.projects.delete.assert_called_once_with(1)

    def test_delete_project_with_linked_tasks(self):
        uow = _make_uow()
        project = FakeProject(7, "P", 3)
        uow.projects.get_by_id.return_value = project
        uow.projects.lock.return_value = project
        uow.tasks.list_by_project.return_value = [FakeTask(1, 7)]
        svc = ProjectService(uow)
        with pytest.raises(ConflictError, match="связан с задачами"):
            svc.delete_project(7)

    def test_create_project_rejects_prefix_owned_by_another_project(self):
        uow = _make_uow()
        existing = MagicMock(id=2, code="OTHER", workflow_id=1, key_prefixes=["TASK"])
        uow.projects.list.return_value = [existing]
        svc = ProjectService(uow)

        with pytest.raises(ConflictError, match="уже назначен"):
            svc.create_project({"code": "NEW", "workflow_id": 1, "key_prefixes": ["TASK"]})

        uow.projects.create.assert_not_called()

    def test_create_project_allows_same_prefix_in_another_workflow(self):
        uow = _make_uow()
        existing = MagicMock(id=2, code="OTHER", workflow_id=2, key_prefixes=["TASK"])
        uow.projects.list.return_value = [existing]
        uow.projects.create.return_value = 3
        uow.projects.get_by_id.return_value = FakeProject(3, "NEW", 1)

        result = ProjectService(uow).create_project(
            {"code": "NEW", "workflow_id": 1, "key_prefixes": ["TASK"]}
        )

        assert result == {"id": 3, "code": "NEW", "workflow_id": 1}
        uow.projects.create.assert_called_once()

    def test_update_project_rejects_duplicate_code(self):
        uow = _make_uow()
        project = MagicMock(id=1, code="OLD", workflow_id=3)
        uow.projects.get_by_id.return_value = project
        uow.projects.lock.return_value = project
        uow.projects.get_by_code.return_value = MagicMock(id=2, code="NEW")

        with pytest.raises(ConflictError, match="уже существует"):
            ProjectService(uow).update_project(1, {"code": "NEW"})

        uow.projects.update.assert_not_called()


class TestWorkflowService:
    def test_create_workflow(self):
        uow = _make_uow()
        uow.workflows.create.return_value = 4
        uow.workflows.get_by_id.return_value = FakeWorkflow(4, "Flow")
        svc = WorkflowService(uow)
        result = svc.create_workflow({"name": "Flow"})
        assert result["id"] == 4
        uow.phases.create.assert_called_once()
        uow.commit.assert_called_once()

    def test_list_get_update_delete(self):
        uow = _make_uow()
        uow.workflows.list.return_value = [FakeWorkflow(1, "W")]
        uow.workflows.get_by_id.return_value = FakeWorkflow(1, "W")
        svc = WorkflowService(uow)
        assert svc.list_workflows() == [{"id": 1, "name": "W"}]
        assert svc.get_workflow(1) == {"id": 1, "name": "W"}
        assert svc.update_workflow(1, {"name": "Z"}) is None
        uow.projects.list.return_value = []
        uow.workflows.lock.return_value = FakeWorkflow(1, "W")
        uow.phases.list.return_value = [MagicMock(code="wf-1-default")]
        assert svc.delete_workflow(1) is None
        uow.workflows.delete.assert_called_once_with(1)

    def test_delete_workflow_linked_projects(self):
        uow = _make_uow()
        uow.projects.list.return_value = [FakeProject(1, "P", 3)]
        uow.workflows.lock.return_value = FakeWorkflow(3, "W")
        svc = WorkflowService(uow)
        with pytest.raises(ConflictError, match="связан с неймспейсами"):
            svc.delete_workflow(3)
