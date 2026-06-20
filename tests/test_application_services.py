"""Tests for SQLAlchemy-based application services."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from workflow_cli.application import (
    AgentService,
    PhaseServiceApp,
    ProjectService,
    TaskService,
    WorkflowService,
)
from workflow_cli.domain.exceptions import ConflictError, LastPhaseError, NotFoundError
from workflow_cli.infrastructure.db.models import Base
from workflow_cli.infrastructure.db.uow import SAUnitOfWork


@pytest.fixture
def sa_engine(tmp_path):
    db_path = tmp_path / "sa.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def uow(sa_engine):
    return SAUnitOfWork(sa_engine)


class TestWorkflowService:
    def test_create_workflow_adds_default_phase(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "New Workflow"})
        assert wf["name"] == "New Workflow"

        phases = PhaseServiceApp(uow).list_phases(wf["id"])
        assert len(phases) == 1
        assert phases[0]["name"] == "Новая фаза"

    def test_delete_workflow_blocked_by_phases(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Deletable?"})
        with pytest.raises(ConflictError):
            svc.delete_workflow(wf["id"])

    def test_delete_workflow_blocked_by_projects(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Linked WF", "_skip_default_phase": True})
        ProjectService(uow).create_project({"code": "LINKED", "workflow_id": wf["id"]})
        with pytest.raises(ConflictError):
            svc.delete_workflow(wf["id"])

    def test_ensure_default_exists_creates_default(self, uow):
        svc = WorkflowService(uow)
        wf = svc.ensure_default_exists()
        assert wf["name"] == "Default Workflow"
        assert wf["is_default"] is True


class TestPhaseServiceApp:
    def test_insert_phase_shifts_orders(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Phase Ordering"})
        ps = PhaseServiceApp(uow)
        # Default phase is at order 1; insert at 2
        p2 = ps.create_phase({"workflow_id": wf["id"], "phase_order": 2, "name": "Second"})
        p3 = ps.create_phase({"workflow_id": wf["id"], "phase_order": 3, "name": "Third"})
        phases = ps.list_phases(wf["id"])
        orders = sorted([p["phase_order"] for p in phases])
        assert orders == [1, 2, 3]

        # Insert before second (order 2)
        p_new = ps.create_phase({"workflow_id": wf["id"], "phase_order": 2, "name": "New"})
        phases = ps.list_phases(wf["id"])
        orders = sorted([p["phase_order"] for p in phases])
        assert orders == [1, 2, 3, 4]
        assert p_new["phase_order"] == 2

    def test_cannot_delete_last_phase(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Single Phase"})
        ps = PhaseServiceApp(uow)
        phases = ps.list_phases(wf["id"])
        with pytest.raises(LastPhaseError):
            ps.delete_phase(phases[0]["id"])

    def test_phase_includes_workflow_name(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Named WF"})
        ps = PhaseServiceApp(uow)
        phase = ps.list_phases(wf["id"])[0]
        assert phase["workflow_name"] == "Named WF"


class TestProjectService:
    def test_create_project_uses_default_workflow(self, uow):
        svc = WorkflowService(uow)
        svc.ensure_default_exists()
        ps = ProjectService(uow)
        proj = ps.create_project({"code": "NOPROJ"})
        assert proj["workflow_id"] is not None
        assert proj["name"] == "NOPROJ"
        assert proj["workflow_name"] is not None


class TestTaskService:
    def test_task_has_current_phase_name(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Task WF"})
        ps = PhaseServiceApp(uow)
        phases = ps.list_phases(wf["id"])
        psvc = ProjectService(uow)
        proj = psvc.create_project({"code": "TASKPROJ", "workflow_id": wf["id"]})
        ts = TaskService(uow)
        task = ts.create_task(
            {
                "project_id": proj["id"],
                "task_key": "TASK-1",
                "current_phase": str(phases[0]["id"]),
            }
        )
        assert task["current_phase_name"] == phases[0]["name"]
