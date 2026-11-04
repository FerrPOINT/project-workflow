"""Standalone lock ordering and unambiguous operation readback regressions."""

import json
from dataclasses import replace
from unittest.mock import Mock

import pytest
import requests
from sqlalchemy import func, select

from project_workflow import config
from project_workflow.application import standalone
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.standalone import StandaloneFence, StandaloneStep
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from tests._report_helpers import report_json


@pytest.fixture
def local_task(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "standalone")
    config.get_settings.cache_clear()
    forbidden = Mock(side_effect=AssertionError("Real model calls are forbidden"))
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr(OpenAICompatibleClient, "chat", forbidden)
    with SAUnitOfWork() as uow:
        workflow = uow.workflows.create({"name": "Locking fixture", "key": "local-locking-fixture"})
        namespace = uow.projects.create({"workflow_id": workflow, "name": "Local", "code": "LCK"})
        phase = uow.phases.create({"workflow_id": workflow, "code": "locking.1",
                                   "name": "Local phase", "phase_order": 1})
        uow.phase_checks.create(phase, {"description": "The result is complete"})
        uow.commit()
        start = StandaloneStep(interaction_protocol="configured-cli-v1", task="LCK-1",
            namespace_id=namespace, start=True, workflow_id=workflow,
            mode_key="default", operation_key="start-locking")
        standalone.step(uow, start)
        yield uow, start


def report(start, *, key="report-locking", version=1):
    return StandaloneStep(interaction_protocol="configured-cli-v1", task=start.task,
        namespace_id=start.namespace_id, operation_key=key, expected_version=version,
        report=report_json("Actual result", source="Owner request"))


@pytest.mark.parametrize("operation", ["read", "history", "report"])
def test_entry_points_lock_workflow_before_task(local_task, monkeypatch, operation):
    uow, start = local_task
    locks = []
    workflow_lock = uow.workflows.lock
    task_lock = uow.tasks.lock

    def lock_workflow(workflow_id):
        locks.append("workflow")
        return workflow_lock(workflow_id)

    def lock_task(task_id):
        locks.append("task")
        return task_lock(task_id)

    def chat(*_args, **kwargs):
        assert not uow.session.in_transaction()
        payload = json.loads(kwargs["user"])
        return {"verdict": "PARTIAL", "blockers": [], "confidence": 1.0,
                "assessments": {item["id"]: {"covered": False, "reason": "Fixture incomplete result",
                                           "required_change": "Provide the missing result"}
                                for item in payload["criteria"]}}

    monkeypatch.setattr(uow.workflows, "lock", lock_workflow)
    monkeypatch.setattr(uow.tasks, "lock", lock_task)
    model = Mock(side_effect=chat)
    monkeypatch.setattr(OpenAICompatibleClient, "chat", model)
    if operation == "history":
        standalone.history(uow, start.task, start.namespace_id)
    elif operation == "report":
        result = standalone.step(uow, report(start))["result"]
        assert result["version"] == 2 and result["verdict"] == "PARTIAL"
    else:
        standalone.step(uow, StandaloneStep(interaction_protocol="configured-cli-v1",
            task=start.task, namespace_id=start.namespace_id))
    assert locks[:2] == ["workflow", "task"]
    assert model.call_count == (1 if operation == "report" else 0)


def test_missing_workflow_refuses_before_task_lock(local_task, monkeypatch):
    uow, start = local_task
    monkeypatch.setattr(uow.workflows, "lock", Mock(return_value=None))
    task_lock = Mock(wraps=uow.tasks.lock)
    monkeypatch.setattr(uow.tasks, "lock", task_lock)
    with pytest.raises(ConflictError, match="workflow disappeared"):
        standalone._task(uow, start.task, start.namespace_id)
    task_lock.assert_not_called()


def test_workflow_changed_between_read_and_lock_is_refused(local_task, monkeypatch):
    uow, start = local_task
    task = uow.tasks.get_by_key(start.task, project_id=start.namespace_id)
    assert task is not None
    monkeypatch.setattr(uow.tasks, "lock", Mock(return_value=replace(task, workflow_id=task.workflow_id + 1)))
    with pytest.raises(ConflictError, match="workflow changed during admission"):
        standalone._task(uow, start.task, start.namespace_id)


def test_fence_still_rejects_version_drift(local_task, monkeypatch):
    uow, start = local_task
    task = standalone._task(uow, start.task, start.namespace_id)
    fence = StandaloneFence(task.id, task.project_id, task.workflow_id, task.mode_id,
        task.cycle_number, task.assignment_revision, task.assignment_operation_key,
        task.current_phase_id, task.status, 1, report(start))
    monkeypatch.setattr(standalone, "version", lambda *_args: 2)
    with pytest.raises(ConflictError, match="operation version changed"):
        standalone.check_fence(uow, fence)


def test_report_cannot_reuse_start_key_or_hide_start_readback(local_task, monkeypatch):
    from project_workflow import supervisor

    uow, start = local_task
    before = standalone.history(uow, start.task, start.namespace_id,
                                operation_key=start.operation_key)["result"]
    engine = Mock(side_effect=AssertionError("Conflicting key must not construct an engine"))
    monkeypatch.setattr(supervisor, "SupervisorEngine", engine)
    with pytest.raises(ConflictError, match="must differ from the accepted start"):
        standalone.step(uow, report(start, key=start.operation_key))
    engine.assert_not_called()
    assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 0
    task = standalone._task(uow, start.task, start.namespace_id)
    assert standalone.version(uow, task) == 1 and task.status == "active"
    assert standalone.history(uow, start.task, start.namespace_id,
                              operation_key=start.operation_key)["result"] == before


@pytest.mark.parametrize("count", [2, 3, 4], ids=["n-minus-one", "n", "n-plus-one"])
def test_history_page_boundaries_preserve_saved_snapshots(local_task, count):
    uow, start = local_task
    task = standalone._task(uow, start.task, start.namespace_id)
    saved = []
    for number in range(count):
        snapshot = {"standalone": {"result_version": number + 2}, "fixture_detail": f"Saved snapshot {number}"}
        worker_report = report_json(f"Result {number}", source="Owner request")
        result = {"verdict": "PARTIAL", "version": number + 2}
        history_id = uow.step_history.create({"task_id": task.id, "phase_id": task.current_phase_id,
            "mode_id": task.mode_id, "cycle_number": task.cycle_number, "verdict": "partial",
            "worker_report": worker_report, "covered_item_ids": [], "missing_item_ids": [],
            "blocker_messages": [], "evaluation_snapshot": snapshot, "supervisor_response": result})
        saved.append({"history_id": history_id, "worker_report": worker_report, "result": result})
    uow.commit()
    stored_snapshots = list(uow.session.scalars(select(m.TaskStepHistoryEntry.evaluation_snapshot)
                                               .where(m.TaskStepHistoryEntry.task_id == task.id)
                                               .order_by(m.TaskStepHistoryEntry.id)))
    page = standalone.history(uow, start.task, start.namespace_id, n=3)["result"]
    newest = list(reversed(saved))
    assert page["records"] == newest[:3]
    assert page["next_before"] == (newest[2]["history_id"] if count > 3 else None)
    if page["next_before"] is not None:
        following = standalone.history(uow, start.task, start.namespace_id, n=3,
                                       before_history_id=page["next_before"])["result"]
        assert following["records"] == newest[3:]
        assert following["next_before"] is None
    assert list(uow.session.scalars(select(m.TaskStepHistoryEntry.evaluation_snapshot)
                                   .where(m.TaskStepHistoryEntry.task_id == task.id)
                                   .order_by(m.TaskStepHistoryEntry.id))) == stored_snapshots


@pytest.mark.parametrize("operation_key", ["start-locking", "report-locking"])
def test_history_refuses_operation_key_with_page_cursor(local_task, operation_key):
    uow, start = local_task
    with pytest.raises(ConflictError, match="cursor cannot select an operation"):
        standalone.history(uow, start.task, start.namespace_id,
                           operation_key=operation_key, before_history_id=1)


def test_history_unknown_operation_is_not_found_but_empty_page_is_valid(local_task):
    uow, start = local_task
    page = standalone.history(uow, start.task, start.namespace_id)["result"]
    assert page["records"] == [] and page["next_before"] is None
    with pytest.raises(NotFoundError, match="Standalone operation receipt not found"):
        standalone.history(uow, start.task, start.namespace_id, operation_key="unknown-operation")
