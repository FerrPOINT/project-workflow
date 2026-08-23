"""Tests for application layer services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.project import ProjectService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork


@dataclass
class FakeWorkflow:
    id: int = 1
    name: str = "W"

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
    uow.instructions = MagicMock()
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
        uow.instructions.list.return_value = [{"id": 1, "description": "D"}]
        svc = InstructionService(uow)
        assert svc.list_instructions(7) == [{"id": 1, "description": "D"}]

    def test_get_instruction(self):
        uow = _make_uow()
        uow.instructions.get_by_id.return_value = {"id": 2, "description": "X"}
        svc = InstructionService(uow)
        assert svc.get_instruction(2) == {"id": 2, "description": "X"}

    def test_create_instruction_success(self):
        uow = _make_uow()
        uow.instructions.create.return_value = 5
        uow.instructions.get_by_id.return_value = {"id": 5, "description": "Y"}
        svc = InstructionService(uow)
        assert svc.create_instruction(3, {"description": "Y"}) == {"id": 5, "description": "Y"}
        uow.instructions.create.assert_called_once_with(3, {"description": "Y"})
        uow.commit.assert_called_once()

    def test_create_instruction_failure(self):
        uow = _make_uow()
        uow.instructions.create.return_value = 1
        uow.instructions.get_by_id.return_value = None
        svc = InstructionService(uow)
        with pytest.raises(RuntimeError, match="Instruction creation failed"):
            svc.create_instruction(1, {})

    def test_update_and_delete_instruction(self):
        uow = _make_uow()
        svc = InstructionService(uow)
        assert svc.update_instruction(2, {"description": "Z"}) is None
        assert svc.delete_instruction(2) is None
        uow.instructions.update.assert_called_once_with(2, {"description": "Z"})
        uow.instructions.delete.assert_called_once_with(2)
        assert uow.commit.call_count == 2

    def test_reorder_instructions(self):
        uow = _make_uow()
        uow.instructions.list.return_value = [{"id": 3}, {"id": 1}, {"id": 2}]
        svc = InstructionService(uow)
        svc.reorder_instructions(10, [2, 3])
        uow.instructions.reorder.assert_called_once_with(10, [(2, 1), (3, 2), (1, 3)])
        uow.commit.assert_called_once()


class TestProjectService:
    def test_create_project_defaults(self):
        uow = _make_uow()
        uow.workflows.ensure_default_exists.return_value = FakeWorkflow(5)
        uow.projects.create.return_value = 8
        uow.projects.get_by_id.return_value = FakeProject(8, "PRJ", 5)
        svc = ProjectService(uow)
        result = svc.create_project({"code": "PRJ"})
        assert result["id"] == 8
        assert result["code"] == "PRJ"
        assert result["workflow_id"] == 5
        uow.projects.create.assert_called_once()
        uow.commit.assert_called_once()

    def test_create_project_with_workflow_id(self):
        uow = _make_uow()
        uow.projects.create.return_value = 9
        uow.projects.get_by_id.return_value = FakeProject(9, "P2", 10)
        svc = ProjectService(uow)
        svc.create_project({"code": "P2", "workflow_id": 10, "name": ""})
        args, kwargs = uow.projects.create.call_args
        payload = args[0] if args else kwargs
        assert payload["workflow_id"] == 10
        assert payload["name"] == "P2"

    def test_list_get_update_delete(self):
        uow = _make_uow()
        uow.projects.list.return_value = [FakeProject(1, "A", 1)]
        uow.projects.get_by_id.return_value = FakeProject(1, "A", 1)
        svc = ProjectService(uow)
        assert svc.list_projects() == [{"id": 1, "code": "A", "workflow_id": 1}]
        assert svc.get_project(1) == {"id": 1, "code": "A", "workflow_id": 1}
        assert svc.update_project(1, {"name": "B"}) is None
        assert svc.delete_project(1) is None
        uow.projects.delete.assert_called_once_with(1)

    def test_delete_project_with_linked_tasks(self):
        uow = _make_uow()
        uow.tasks.list.return_value = [FakeTask(1, 7)]
        svc = ProjectService(uow)
        with pytest.raises(ConflictError, match="linked tasks"):
            svc.delete_project(7)

    def test_create_project_rejects_prefix_owned_by_another_project(self):
        uow = _make_uow()
        existing = MagicMock(id=2, code="OTHER", key_prefixes=["TASK"])
        uow.projects.list.return_value = [existing]
        svc = ProjectService(uow)

        with pytest.raises(ConflictError, match="already assigned"):
            svc.create_project({"code": "NEW", "workflow_id": 1, "key_prefixes": ["TASK"]})

        uow.projects.create.assert_not_called()

    def test_update_project_rejects_duplicate_code(self):
        uow = _make_uow()
        uow.projects.get_by_id.return_value = MagicMock(id=1, code="OLD")
        uow.projects.get_by_code.return_value = MagicMock(id=2, code="NEW")

        with pytest.raises(ConflictError, match="already exists"):
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

    def test_create_workflow_skip_default_phase(self):
        uow = _make_uow()
        uow.workflows.create.return_value = 4
        uow.workflows.get_by_id.return_value = FakeWorkflow(4, "Flow")
        svc = WorkflowService(uow)
        svc.create_workflow({"name": "Flow", "_skip_default_phase": True})
        uow.phases.create.assert_not_called()

    def test_list_get_update_delete(self):
        uow = _make_uow()
        uow.workflows.list.return_value = [FakeWorkflow(1, "W")]
        uow.workflows.get_by_id.return_value = FakeWorkflow(1, "W")
        uow.workflows.get_by_name.return_value = FakeWorkflow(1, "W")
        svc = WorkflowService(uow)
        assert svc.list_workflows() == [{"id": 1, "name": "W"}]
        assert svc.get_workflow(1) == {"id": 1, "name": "W"}
        assert svc.get_workflow_by_name("W") == {"id": 1, "name": "W"}
        assert svc.update_workflow(1, {"name": "Z"}) is None
        uow.projects.list.return_value = []
        assert svc.delete_workflow(1) is None
        uow.workflows.delete.assert_called_once_with(1)

    def test_delete_workflow_linked_projects(self):
        uow = _make_uow()
        uow.projects.list.return_value = [FakeProject(1, "P", 3)]
        svc = WorkflowService(uow)
        with pytest.raises(ConflictError, match="linked projects"):
            svc.delete_workflow(3)

    def test_ensure_default_exists(self):
        uow = _make_uow()
        uow.workflows.ensure_default_exists.return_value = FakeWorkflow(5, "Default")
        svc = WorkflowService(uow)
        assert svc.ensure_default_exists() == {"id": 5, "name": "Default"}
        uow.workflows.ensure_default_exists.assert_called_once_with("sdlc-business-tech-v1")
