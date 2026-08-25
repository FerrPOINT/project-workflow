"""Tests for application.task and application.state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from project_workflow.application.state import _AppState
from project_workflow.application.task import TaskService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork


@dataclass
class FakeProject:
    id: int
    code: str
    workflow_id: int = 1

    @property
    def key_prefixes(self) -> list[str]:
        return [self.code]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "code": self.code, "key_prefixes": [self.code]}


@dataclass
class FakeTask:
    id: int
    task_key: str = "A-1"
    project_id: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "task_key": self.task_key, "project_id": self.project_id}


@dataclass
class FakePhase:
    code: str = "1.INTAKE"


def _make_uow() -> UnitOfWork:
    uow = MagicMock(spec=UnitOfWork)
    uow.tasks = MagicMock()
    uow.projects = MagicMock()
    uow.workflows = MagicMock()
    uow.phases = MagicMock()
    uow.tasks.get_by_key.return_value = None
    uow.workflows.lock.return_value = object()
    uow.phases.list.return_value = [FakePhase()]
    uow.phases.get_by_code.return_value = FakePhase()
    uow.projects.get_by_id.side_effect = lambda _project_id: uow.projects.lock.return_value
    return uow


class TestTaskService:
    def test_create_task_with_project_id(self):
        uow = _make_uow()
        uow.tasks.create.return_value = 7
        uow.tasks.get_by_id.return_value = FakeTask(7, "B-2", 5)
        uow.projects.lock.return_value = FakeProject(5, "B")
        svc = TaskService(uow)
        result = svc.create_task({"task_key": "B-2", "project_id": 5})
        assert result["id"] == 7
        assert result["project_id"] == 5
        uow.commit.assert_called_once()
        uow.workflows.lock.assert_called_once_with(1)
        assert uow.tasks.create.call_args.args[0]["current_phase"] == "1.INTAKE"

    def test_create_task_rejects_non_string_phase_code(self):
        uow = _make_uow()
        uow.projects.lock.return_value = FakeProject(5, "B")
        uow.tasks.create.return_value = 7
        uow.tasks.get_by_id.return_value = FakeTask(7, "B-2", 5)

        with pytest.raises(ValueError, match="строковым кодом фазы"):
            TaskService(uow).create_task(
                {"task_key": "B-2", "project_id": 5, "current_phase": 0}
            )

        uow.tasks.create.assert_not_called()

    def test_create_task_without_project_id(self):
        uow = _make_uow()
        uow.projects.list.return_value = [FakeProject(4, "PRJ")]
        uow.projects.lock.return_value = FakeProject(4, "PRJ")
        uow.tasks.create.return_value = 8
        uow.tasks.get_by_id.return_value = FakeTask(8, "PRJ-1", 4)
        svc = TaskService(uow)
        result = svc.create_task({"task_key": "PRJ-1"})
        assert result["project_id"] == 4

    def test_create_task_unknown_prefix_fails_without_writes(self):
        uow = _make_uow()
        uow.projects.list.return_value = []
        with pytest.raises(ValueError, match="не настроен проект"):
            TaskService(uow).create_task({"task_key": "NEW-1"})
        uow.projects.create.assert_not_called()
        uow.tasks.create.assert_not_called()

    def test_duplicate_task_key_is_a_deterministic_conflict(self):
        uow = _make_uow()
        uow.projects.lock.return_value = FakeProject(5, "B")
        uow.tasks.get_by_key.return_value = FakeTask(7, "B-2", 5)

        with pytest.raises(ConflictError, match="уже существует"):
            TaskService(uow).create_task({"task_key": "B-2", "project_id": 5})

        uow.tasks.create.assert_not_called()

    @pytest.mark.parametrize("task_key", ["B", "B-RACE", "b-2", "B-2X"])
    def test_create_task_uses_the_same_numeric_key_contract_as_cli(self, task_key):
        uow = _make_uow()
        uow.projects.lock.return_value = FakeProject(5, "B")

        with pytest.raises(ConflictError, match="Ключ"):
            TaskService(uow).create_task({"task_key": task_key, "project_id": 5})

        uow.tasks.create.assert_not_called()

    def test_get_list_delete(self):
        uow = _make_uow()
        uow.tasks.get_by_id.return_value = FakeTask(1, "A-1", 1)
        uow.tasks.lock.return_value = FakeTask(1, "A-1", 1)
        uow.tasks.get_by_key.return_value = FakeTask(1, "A-1", 1)
        uow.tasks.list.return_value = [FakeTask(1, "A-1", 1)]
        uow.projects.get_by_id.return_value = FakeProject(1, "A", 1)
        uow.projects.lock.return_value = FakeProject(1, "A", 1)
        svc = TaskService(uow)
        assert svc.get_task(1) == {"id": 1, "task_key": "A-1", "project_id": 1}
        assert svc.get_task_by_key("A-1") == {"id": 1, "task_key": "A-1", "project_id": 1}
        assert svc.list_tasks() == [{"id": 1, "task_key": "A-1", "project_id": 1}]
        assert svc.delete_task(1) is None
        uow.workflows.lock.assert_called_with(1)
        uow.projects.lock.assert_called_with(1)
        uow.tasks.lock.assert_called_once_with(1)


class TestAppState:
    def test_init_default_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite:///env.db")
        from project_workflow.config import get_settings

        get_settings.cache_clear()
        state = _AppState()
        assert state._database_url is None
        assert state._database_url_normalized().endswith("env.db")

    def test_database_url_normalized(self):
        state = _AppState("sqlite:///tmp/../test.db")
        assert state._database_url_normalized().replace("\\", "/").endswith("/test.db")

    def test_service_factories(self):
        state = MagicMock(spec=_AppState)
        state.get_uow.return_value = MagicMock()
        # Bind real methods to the mock so we exercise the implementation logic.
        from project_workflow.application.state import _AppState as RealState

        state.workflow_service = lambda: RealState.workflow_service(state)
        state.phase_service = lambda: RealState.phase_service(state)
        state.project_service = lambda: RealState.project_service(state)
        state.task_service = lambda: RealState.task_service(state)
        state.agent_service = lambda: RealState.agent_service(state)
        state.instruction_service = lambda: RealState.instruction_service(state)
        state.get_service = lambda: RealState.get_service(state)
        state.get_db = lambda: RealState.get_db(state)
        assert state.workflow_service() is not None
        assert state.phase_service() is not None
        assert state.project_service() is not None
        assert state.task_service() is not None
        assert state.agent_service() is not None
        assert state.instruction_service() is not None
        assert state.get_service() is not None
        assert state.get_db() is not None
        assert state.get_uow.call_count >= 7

    def test_get_uow_sqlite(self):
        import tempfile
        from pathlib import Path

        from project_workflow.infrastructure.db.session import reset_engine

        reset_engine()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "appstate.db"
            state = _AppState(f"sqlite:///{db}")
            uow = state.get_uow()
            assert uow is not None
            uow2 = state.get_uow()
            assert uow2 is not None
            uow3 = state.get_uow()
            assert uow3 is not None
