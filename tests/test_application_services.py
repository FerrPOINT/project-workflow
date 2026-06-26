"""Tests for SQLAlchemy-based application services."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from unittest.mock import MagicMock

pytestmark = [pytest.mark.unit]

from project_workflow.application import (
    AgentService,
    PhaseServiceApp,
    ProjectService,
    TaskService,
    WorkflowService,
)
from project_workflow.domain.exceptions import ConflictError, LastPhaseError
from project_workflow.infrastructure.db.models import Base
from project_workflow.infrastructure.db.uow import SAUnitOfWork


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

    def test_delete_workflow_cascade_deletes_phases(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Deletable"})
        svc.delete_workflow(wf["id"])
        assert svc.get_workflow(wf["id"]) is None
        assert PhaseServiceApp(uow).list_phases(wf["id"]) == []

    def test_delete_workflow_blocked_by_projects(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Linked WF", "_skip_default_phase": True})
        ProjectService(uow).create_project({"code": "LINKED", "workflow_id": wf["id"]})
        with pytest.raises(ConflictError):
            svc.delete_workflow(wf["id"])

    def test_get_or_create_smoke_workflow_creates_when_missing(self, uow):
        from project_workflow import config
        svc = WorkflowService(uow)
        wf = svc.get_or_create_smoke_workflow()
        assert wf["name"] == config.SMOKE_WORKFLOW_NAME
        # second call returns existing
        wf2 = svc.get_or_create_smoke_workflow()
        assert wf2["id"] == wf["id"]

    def test_create_workflow_failure_raises(self):
        uow = MagicMock()
        uow.workflows.create.return_value = 1
        uow.workflows.get_by_id.return_value = None
        svc = WorkflowService(uow)
        with pytest.raises(RuntimeError, match="Workflow creation failed"):
            svc.create_workflow({"name": "X"})

    def test_get_workflow_by_name(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "By Name"})
        found = svc.get_workflow_by_name("By Name")
        assert found is not None
        assert found["id"] == wf["id"]
        assert svc.get_workflow_by_name("Missing") is None

    def test_update_workflow(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Old"})
        svc.update_workflow(wf["id"], {"name": "New"})
        assert svc.get_workflow(wf["id"])["name"] == "New"


class TestAgentService:
    def test_create_list_get_update_delete(self, uow):
        svc = AgentService(uow)
        agent = svc.create_agent({"name": "A1", "description": "d"})
        assert agent["name"] == "A1"
        assert len(svc.list_agents()) == 1
        assert svc.get_agent(agent["id"])["name"] == "A1"
        svc.update_agent(agent["id"], {"name": "A2"})
        assert svc.get_agent(agent["id"])["name"] == "A2"
        svc.delete_agent(agent["id"])
        assert svc.get_agent(agent["id"]) is None


    def test_create_agent_failure_raises(self):
        uow = MagicMock()
        uow.agents.create.return_value = 1
        uow.agents.get_by_id.return_value = None
        svc = AgentService(uow)
        with pytest.raises(RuntimeError, match="Agent creation failed"):
            svc.create_agent({"name": "X"})


class TestPhaseServiceApp:
    def test_generate_code_with_non_numeric_suffix(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Code"})
        ps = PhaseServiceApp(uow)
        # Create a phase with a code that has a non-numeric suffix
        ps.create_phase({"workflow_id": wf["id"], "code": f"wf-{wf['id']}-phase-abc", "name": "A"})
        # Suffix parsing ignores non-numeric, so next generated code is wf-{id}-phase-1
        p2 = ps.create_phase({"workflow_id": wf["id"], "name": "B"})
        assert p2["code"] == f"wf-{wf['id']}-phase-1"

    def test_create_phase_failure_raises(self):
        uow = MagicMock()
        uow.phases.list.return_value = []
        uow.phases.get_next_order.return_value = 1
        uow.phases.create.return_value = 1
        uow.phases.get_by_id.return_value = None
        svc = PhaseServiceApp(uow)
        with pytest.raises(RuntimeError, match="Phase creation failed"):
            svc.create_phase({"workflow_id": 1, "name": "X"})

    def test_insert_phase_shifts_orders(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Phase Ordering"})
        ps = PhaseServiceApp(uow)
        # Default phase is at order 1; insert at 2
        _ = ps.create_phase({"workflow_id": wf["id"], "phase_order": 2, "name": "Second"})
        _ = ps.create_phase({"workflow_id": wf["id"], "phase_order": 3, "name": "Third"})
        phases = ps.list_phases(wf["id"])
        orders = sorted([p["phase_order"] for p in phases])
        assert orders == [1, 2, 3]

        # Insert before second (order 2)
        p_new = ps.create_phase({"workflow_id": wf["id"], "phase_order": 2, "name": "New"})
        phases = ps.list_phases(wf["id"])
        orders = sorted([p["phase_order"] for p in phases])
        assert orders == [1, 2, 3, 4]
        assert p_new["phase_order"] == 2

    def test_create_phase_without_order_appends(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Append"})
        ps = PhaseServiceApp(uow)
        p1 = ps.create_phase({"workflow_id": wf["id"], "name": "First"})
        p2 = ps.create_phase({"workflow_id": wf["id"], "name": "Second"})
        assert p2["phase_order"] == p1["phase_order"] + 1

    def test_get_update_delete_phase(self, uow):
        svc = WorkflowService(uow)
        wf = svc.create_workflow({"name": "Mutate"})
        ps = PhaseServiceApp(uow)
        p = ps.create_phase({"workflow_id": wf["id"], "name": "Orig"})
        assert ps.get_phase(p["id"])["name"] == "Orig"
        ps.update_phase(p["id"], {"name": "Renamed"})
        assert ps.get_phase(p["id"])["name"] == "Renamed"
        ps.delete_phase(p["id"])
        assert ps.get_phase(p["id"]) is None

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

    def test_create_project_with_name_default(self, uow):
        svc = WorkflowService(uow)
        svc.ensure_default_exists()
        ps = ProjectService(uow)
        proj = ps.create_project({"code": "NN", "workflow_id": 1})
        assert proj["name"] == "NN"

    def test_create_project_with_linked_tasks_fails_delete(self, uow):
        from project_workflow.domain.exceptions import ConflictError
        svc = WorkflowService(uow)
        svc.ensure_default_exists()
        ps = ProjectService(uow)
        p = ps.create_project({"code": "DELME"})
        ts = TaskService(uow)
        ts.create_task({"task_key": "DEL-1", "project_id": p["id"]})
        with pytest.raises(ConflictError):
            ps.delete_project(p["id"])


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

    def test_create_task_without_project(self, uow):
        ts = TaskService(uow)
        task = ts.create_task({"task_key": "AUTO-1"})
        assert task["task_key"] == "AUTO-1"
        assert task["project_id"] is not None

    def test_create_task_failure_raises(self):
        uow = MagicMock()
        project = MagicMock()
        project.to_dict.return_value = {"id": 1}
        uow.projects.get_by_code.return_value = project
        uow.tasks.create.return_value = 1
        uow.tasks.get_by_id.return_value = None
        ts = TaskService(uow)
        with pytest.raises(RuntimeError, match="Task creation failed"):
            ts.create_task({"task_key": "FAIL-1"})

    def test_get_update_delete_task(self, uow):
        ts = TaskService(uow)
        task = ts.create_task({"task_key": "GET-1"})
        assert ts.get_task(task["id"])["task_key"] == "GET-1"
        assert ts.get_task_by_key("GET-1")["task_key"] == "GET-1"
        ts.update_task(task["id"], {"status": "done"})
        assert ts.get_task(task["id"])["status"] == "done"
        ts.add_history(task["id"], int(task["current_phase"]), "done")
        # add_history commits; task.to_dict does not expose history, so just ensure no exception
        assert ts.get_task(task["id"]) is not None

    def test_list_tasks(self, uow):
        ts = TaskService(uow)
        ts.create_task({"task_key": "L-1"})
        assert len(ts.list_tasks()) == 1
