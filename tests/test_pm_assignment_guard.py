"""A Workflow PASS is not authority to replace an enrolled PM execution."""

import json

import pytest
from sqlalchemy import select

from project_workflow.application.task import TaskService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_pm_execution import ADAPTER, BASE, NEW_RUN, RUNTIME, bind_pm, prepare_pm
from tests.test_pm_execution_edges import test_resumed_supervisor_report_is_persistent_and_replayable as verify_done
from tests.test_runtime_api import _assignment, _step_payload


@pytest.fixture
def pm(monkeypatch):
    yield from prepare_pm(monkeypatch)


def replacement(cycle_number=1):
    request = _assignment("PM-1", "assign:pm:replacement", "project_manager")
    request.update(expected_revision=1, expected_status="done", expected_mode_key="assigned",
                   expected_cycle_number=0, cycle_number=cycle_number,
                   attempt_number=1 if cycle_number else 2)
    return request


def persisted_assignment_state():
    with SAUnitOfWork() as uow:
        return tuple(tuple(tuple(row) for row in uow.session.execute(
            select(*model.__table__.columns).order_by(*model.__table__.primary_key.columns)
        )) for model in (
            m.Task, m.TaskRuntimeAssignment, m.TaskPhaseEvent, m.TaskStepHistoryEntry,
            m.PMExecution, m.PMRun, m.PMOperation,
        ))


def complete_unenrolled_assignment(pm, supervisor_llm):
    supervisor_llm("PASS")
    response = pm[0].post("/internal/runtime/step", headers=RUNTIME,
                          json=_step_payload(pm[4], report="Verified ordinary assignment"))
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "done"


def test_unenrolled_pm_role_done_still_accepts_generic_cycle(pm, supervisor_llm):
    complete_unenrolled_assignment(pm, supervisor_llm)
    response = pm[0].post("/internal/runtime/assign", headers=ADAPTER, json=replacement())
    assert response.status_code == 200, response.text
    assert response.json()["result"]["assignment_revision"] == 2
    assert response.json()["result"]["cycle_number"] == 1
    assert tuple(len(rows) for rows in persisted_assignment_state()[4:]) == (0, 0, 0)


@pytest.mark.parametrize("cycle_number", [0, 1])
def test_normal_scoped_pass_cannot_replace_running_pm_assignment(pm, supervisor_llm, cycle_number):
    verify_done(pm, supervisor_llm)
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("PM-1")
        execution = uow.session.scalar(select(m.PMExecution))
        run = uow.session.get(m.PMRun, NEW_RUN)
        assert task.status == "done" and task.assignment_revision == 1
        assert execution.state == "active" and execution.session_run_id == NEW_RUN
        assert run.terminal_json is None and pm[3][NEW_RUN]["status"] == "running"
    before = persisted_assignment_state()
    response = pm[0].post("/internal/runtime/assign", headers=ADAPTER, json=replacement(cycle_number))
    assert response.status_code == 409, response.text
    assert response.json()["ok"] is False
    assert "Enrolled PM task requires terminal/quiescent replacement admission" in response.text
    assert persisted_assignment_state() == before
    read = pm[0].post(BASE + "/readback", headers=ADAPTER, json=pm[1])
    assert read.status_code == 200, read.text
    assert read.json()["result"]["identity"] == pm[1]
    assert read.json()["result"]["workflow_step_allowed"] is False


def test_terminal_readback_alone_does_not_authorize_pm_replacement(pm, supervisor_llm):
    verify_done(pm, supervisor_llm)
    pm[3][NEW_RUN]["status"] = "completed"
    with SAUnitOfWork() as uow:
        uow.session.get(m.PMRun, NEW_RUN).terminal_json = json.dumps(pm[3][NEW_RUN])
    before = persisted_assignment_state()
    response = pm[0].post("/internal/runtime/assign", headers=ADAPTER, json=replacement())
    assert response.status_code == 409, response.text
    assert response.json()["ok"] is False
    assert persisted_assignment_state() == before


def test_historical_assign_replay_after_pm_done_is_read_only(pm, supervisor_llm):
    verify_done(pm, supervisor_llm)
    request = _assignment("PM-1", "assign:pm:1", "project_manager")
    before = persisted_assignment_state()
    replay = pm[0].post("/internal/runtime/assign", headers=ADAPTER, json=request)
    assert replay.status_code == 200, replay.text
    for key in ("assignment_operation_key", "assignment_ref", "assignment_revision", "concrete_agent_ref"):
        assert replay.json()["result"][key] == pm[4][key]
    assert replay.json()["result"]["status"] == "done"
    assert persisted_assignment_state() == before
    changed = pm[0].post("/internal/runtime/assign", headers=ADAPTER, json={
        **request, "assignment_ref": "assignment:changed",
    })
    assert changed.status_code == 409, changed.text
    assert persisted_assignment_state() == before


def test_assign_replay_is_reconciled_again_under_owner_lock(pm, supervisor_llm, monkeypatch):
    from project_workflow.infrastructure.db.repositories.task import SATaskRepository

    verify_done(pm, supervisor_llm)
    original = SATaskRepository.get_assignment_by_operation_key
    reads = []

    def initially_unseen(self, operation_key):
        reads.append(operation_key)
        return None if len(reads) == 1 else original(self, operation_key)

    monkeypatch.setattr(SATaskRepository, "get_assignment_by_operation_key", initially_unseen)
    before = persisted_assignment_state()
    replay = pm[0].post("/internal/runtime/assign", headers=ADAPTER,
                        json=_assignment("PM-1", "assign:pm:1", "project_manager"))
    assert replay.status_code == 200, replay.text
    assert reads == ["assign:pm:1", "assign:pm:1"]
    assert replay.json()["result"]["assignment_revision"] == 1
    assert persisted_assignment_state() == before


def test_service_rejects_new_pm_assignment_with_typed_conflict(pm, supervisor_llm):
    verify_done(pm, supervisor_llm)
    request = replacement()
    request.pop("task")
    request.update(task_key="PM-1", tech_execution_workspace_ref=None, tech_execution_attempt_ref=None)
    before = persisted_assignment_state()
    with SAUnitOfWork() as uow:
        request["project_id"] = uow.tasks.get_by_key("PM-1").project_id
        with pytest.raises(ConflictError, match="Enrolled PM task requires terminal/quiescent replacement admission"):
            TaskService(uow).assign_runtime_task(**request)
    assert persisted_assignment_state() == before


def test_new_assignment_checks_task_enrollment_not_only_current_assignment(pm):
    # Owner-history corruption cannot hide the older immutable PM enrollment.
    bind_pm(pm)
    with SAUnitOfWork() as uow:
        task = uow.session.scalar(select(m.Task))
        task.status = "done"
        task.assignment_operation_key = None
    before = persisted_assignment_state()
    response = pm[0].post("/internal/runtime/assign", headers=ADAPTER, json=replacement())
    assert response.status_code == 409, response.text
    assert "Enrolled PM task requires terminal/quiescent replacement admission" in response.text
    assert persisted_assignment_state() == before
