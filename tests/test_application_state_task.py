"""Tests for application.task and application.state."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

from project_workflow.application.state import _AppState
from project_workflow.application.task import TaskService
from project_workflow.domain.repositories import UnitOfWork


@dataclass
class FakeProject:
    id: int
    code: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "code": self.code}


@dataclass
class FakeTask:
    id: int
    task_key: str = "A-1"
    project_id: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "task_key": self.task_key, "project_id": self.project_id}


def _make_uow() -> UnitOfWork:
    uow = MagicMock(spec=UnitOfWork)
    uow.tasks = MagicMock()
    uow.projects = MagicMock()
    return uow


class TestTaskService:
    def test_create_task_with_project_id(self):
        uow = _make_uow()
        uow.tasks.create.return_value = 7
        uow.tasks.get_by_id.return_value = FakeTask(7, "B-2", 5)
        svc = TaskService(uow)
        result = svc.create_task({"task_key": "B-2", "project_id": 5})
        assert result["id"] == 7
        assert result["project_id"] == 5
        uow.commit.assert_called_once()

    def test_create_task_without_project_id(self):
        uow = _make_uow()
        uow.projects.get_by_code.return_value = FakeProject(4, "PRJ")
        uow.tasks.create.return_value = 8
        uow.tasks.get_by_id.return_value = FakeTask(8, "PRJ-1", 4)
        svc = TaskService(uow)
        result = svc.create_task({"task_key": "PRJ-1"})
        assert result["project_id"] == 4

    def test_create_task_auto_project(self):
        uow = _make_uow()
        uow.projects.get_by_code.return_value = None
        uow.tasks.create.return_value = 9
        uow.tasks.get_by_id.return_value = FakeTask(9, "NEW-1", 10)
        with patch("project_workflow.application.project.ProjectService") as ps_cls:
            ps_cls.return_value.create_project.return_value = {"id": 10, "code": "NEW"}
            svc = TaskService(uow)
            result = svc.create_task({"task_key": "NEW-1"})
            assert result["project_id"] == 10
            ps_cls.assert_called_once_with(uow)
            ps_cls.return_value.create_project.assert_called_once_with({"name": "NEW", "code": "NEW"})

    def test_get_update_list_delete(self):
        uow = _make_uow()
        uow.tasks.get_by_id.return_value = FakeTask(1, "A-1", 1)
        uow.tasks.get_by_key.return_value = FakeTask(1, "A-1", 1)
        uow.tasks.list.return_value = [FakeTask(1, "A-1", 1)]
        svc = TaskService(uow)
        assert svc.get_task(1) == {"id": 1, "task_key": "A-1", "project_id": 1}
        assert svc.get_task_by_key("A-1") == {"id": 1, "task_key": "A-1", "project_id": 1}
        assert svc.list_tasks() == [{"id": 1, "task_key": "A-1", "project_id": 1}]
        assert svc.update_task(1, {"status": "done"}) is None
        assert svc.add_history(1, 2, "done") is None
        assert svc.delete_task(1) is None


class TestAppState:
    def test_init_default_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite:///env.db")
        from project_workflow.config import get_settings
        get_settings.cache_clear()
        state = _AppState()
        assert state._database_url == "sqlite:///env.db"

    def test_database_url_normalized(self):
        state = _AppState("sqlite:///tmp/../test.db")
        assert state._database_url_normalized().endswith("/test.db")

    def test_reset(self):
        state = _AppState("sqlite:///reset.db")
        url = state._database_url_normalized()
        from project_workflow.application.state import _CATALOG_ENSURED_URLS, _MIGRATED_URLS
        _CATALOG_ENSURED_URLS.add(url)
        _MIGRATED_URLS.add(url)
        state.reset()
        assert url not in _CATALOG_ENSURED_URLS
        assert url not in _MIGRATED_URLS

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

    def test_db_property(self):
        state = _AppState()
        assert state.db is None

    def test_get_uow_sqlite(self):
        from pathlib import Path
        import tempfile
        from project_workflow.infrastructure.db.session import reset_engine
        reset_engine()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "appstate.db"
            state = _AppState(f"sqlite:///{db}")
            uow = state.get_uow()
            assert uow is not None
            uow2 = state.get_uow()
            assert uow2 is not None
            state.reset()
            uow3 = state.get_uow()
            assert uow3 is not None
