"""Workflow completion and Tracker stage/status have different owners."""

from copy import deepcopy
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from project_workflow import config
from project_workflow.infrastructure import configured_cli_tracker
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from tests._report_helpers import report_json
from tests.test_configured_cli import WRITER, check_tracker_assignment, enroll, step
from tests.test_configured_cli import configured as configured


@pytest.fixture
def tracker_peer(configured, monkeypatch):
    assignment = configured[1]
    identity = {
        "assignment_id": assignment["assignment_ref"],
        "execution_id": assignment["tracker_execution_id"],
        "agent_id": assignment["concrete_agent_ref"],
        "version": assignment["assignment_version"],
        "machine_subject": assignment["machine_subject"],
    }
    context = {
        "contract_version": 1,
        "interaction_protocol": "configured-cli-v1",
        "task_id": assignment["tracker_task_id"],
        "root_task_id": assignment["tracker_task_id"],
        "owner_subject": assignment["owner_subject"],
        "workflow_task_key": assignment["task"],
        "stage": "Draft" if assignment["role_key"] == "project_manager" else "Analysis",
        "status": "InProgress",
        "assignment": identity,
    }
    confirmation = {
        "id": str(uuid4()), "task_id": assignment["tracker_task_id"], "revision": 2,
        "content_hash": "a" * 64, "owner_subject": assignment["owner_subject"], "stage": "Draft",
    }
    calls = []
    prefix = f"/api/v1/issues/{assignment['tracker_task_id']}/sdlc/"

    def handle(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET", "Workflow must not write Tracker business state"
        values = {
            prefix + "context": context,
            prefix + "requirements": {"revision": 2, "content_hash": "a" * 64},
            prefix + "requirements/2/confirmation": confirmation,
        }
        assert request.url.path in values
        return httpx.Response(200, json=values[request.url.path])

    client = httpx.Client
    monkeypatch.setattr(configured_cli_tracker.httpx, "Client",
                        lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setenv("PROJECT_WORKFLOW_CONFIGURED_TRACKER_URL", "https://tracker.test")
    monkeypatch.setenv("PROJECT_WORKFLOW_CONFIGURED_TRACKER_READ_TOKEN", "synthetic-read-token")
    config.get_settings.cache_clear()
    monkeypatch.setattr(configured_cli_tracker, "assignment", check_tracker_assignment)
    return context, identity, confirmation, calls


def test_pm_workflow_completion_leaves_tracker_stage_and_status_unchanged(
    configured, tracker_peer, supervisor_llm,
):
    context, _, confirmation, calls = tracker_peer
    before = deepcopy(context)
    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2, 3):
        command = {
            "report": report_json(f"Controlled completed PM phase {version}"),
            "operation_key": f"boundary-pm-{version}", "expected_version": version,
        }
        if version == 3:
            command.update(requirements_revision=2, requirements_sha256="a" * 64)
        response = step(configured, **command)
        assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["complete"] is True
    assert result["terminal_receipt"]["confirmation_id"] == confirmation["id"]
    assert context == before
    assert context["stage"] == "Draft" and context["status"] == "InProgress"
    assert calls and all(method == "GET" for method, _ in calls)
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key(configured[1]["task"], project_id=configured[1]["namespace_id"])
        assert task.status == "done"
        assert uow.session.scalar(select(func.count()).select_from(m.Task)) == 1
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 3


@pytest.mark.parametrize("configured", [("analyst", "analysis")], indirect=True)
def test_analyst_first_step_requires_tracker_running_assignment(configured, tracker_peer, monkeypatch):
    context, identity, _, calls = tracker_peer
    provider = Mock(side_effect=AssertionError("Instruction read must not invoke Advisor"))
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    context.update(status="Ready", assignment=None)
    client, assignment = configured
    denied = client.post("/internal/runtime/assign", headers=WRITER, json=assignment)
    assert denied.status_code == 409, denied.text
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.Task)) == 0
    # The controlled peer represents Tracker's accepted run binding, not an agent status patch.
    context.update(status="InProgress", assignment=identity)
    enroll(configured)
    response = step(configured)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["phase_contract"]["phase_code"] == result["phase_code"]
    assert result["complete"] is False and result["version"] == 1
    assert context["stage"] == "Analysis" and context["status"] == "InProgress"
    assert all(method == "GET" for method, _ in calls)
    provider.assert_not_called()
