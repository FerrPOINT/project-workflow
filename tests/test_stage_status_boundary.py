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
from tests.test_configured_cli import MACHINE, WRITER, check_tracker_assignment, enroll, step
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
        "stage": next(iter(configured_cli_tracker.STAGES[(assignment["role_key"], assignment["mode_key"])]
                           - {"Backlog"})),
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
def test_analyst_first_step_requires_tracker_assignment(configured, tracker_peer, monkeypatch):
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


@pytest.mark.parametrize("configured", [
    ("project_manager", "draft"), ("analyst", "analysis"),
    ("architect", "decomposition"), ("developer", "initial"),
    ("developer", "rework"), ("reviewer", "delivery"),
    ("tester", "delivery"), ("devops", "delivery"),
], indirect=True)
def test_first_instruction_precedes_agent_start_but_report_requires_in_progress(
    configured, tracker_peer, supervisor_llm, monkeypatch,
):
    context, identity, _, calls = tracker_peer
    context["status"] = "Ready"
    supervisor_llm("PASS")
    provider = Mock(wraps=OpenAICompatibleClient.respond)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    original = enroll(configured)
    before = deepcopy(context)
    response = step(configured)
    assert response.status_code == 200, response.text
    first = response.json()["result"]
    assert first["execution_ref"] == original["execution_ref"]
    assert first["version"] == 1 and first["complete"] is False
    assert first["phase_contract"]["phase_code"] == first["phase_code"]
    assert first["assignment_ref"] == identity["assignment_id"]
    command = {"report": report_json("Actual work after the assigned agent starts"),
               "operation_key": "first-report-after-start", "expected_version": 1}
    denied = step(configured, **command)
    assert denied.status_code == 409, denied.text
    provider.assert_not_called()
    assert context == before
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 0
    # The controlled peer now reflects the agent's separately accepted Tracker Start.
    context["status"] = "InProgress"
    accepted = step(configured, **command)
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()["result"]
    assert result["version"] == 2 and result["execution_ref"] == original["execution_ref"]
    assert result["verdict"] == "PASS"
    assert context["assignment"] == identity
    provider.assert_called_once()
    assert calls and all(method == "GET" for method, _ in calls)


@pytest.mark.parametrize("configured", [("analyst", "analysis")], indirect=True)
@pytest.mark.parametrize("field", [
    "assignment_id", "execution_id", "agent_id", "machine_subject", "version",
    "task_id", "root_task_id", "owner_subject", "workflow_task_key", "stage",
])
def test_ready_admission_keeps_exact_assignment_and_business_identity(configured, tracker_peer, field):
    context, identity, _, _ = tracker_peer
    context["status"] = "Ready"
    if field in identity:
        identity[field] = identity[field] + 1 if field == "version" else str(uuid4())
    else:
        context[field] = "Architecture" if field == "stage" else str(uuid4())
    client, assignment = configured
    response = client.post("/internal/runtime/assign", headers=WRITER, json=assignment)
    assert response.status_code == 409, response.text
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.Task)) == 0


@pytest.mark.parametrize("configured", [("project_manager", "draft"), ("analyst", "analysis")], indirect=True)
def test_completed_tracker_assignment_cannot_enroll_read_or_report(configured, tracker_peer, monkeypatch):
    context, _, _, _ = tracker_peer
    provider = Mock(side_effect=AssertionError("Completed assignment must not invoke Advisor"))
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    context["status"] = "Completed"
    client, assignment = configured
    refused = client.post("/internal/runtime/assign", headers=WRITER, json=assignment)
    assert refused.status_code == 409, refused.text
    context["status"] = "Ready"
    enroll(configured)
    context["status"] = "Completed"
    assert step(configured).status_code == 409
    refused = step(configured, report=report_json("Must not reopen completed work"),
                   operation_key="completed-report", expected_version=1)
    assert refused.status_code == 409, refused.text
    provider.assert_not_called()
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 0


@pytest.mark.parametrize("configured", [("project_manager", "draft"), ("analyst", "analysis")], indirect=True)
def test_report_rechecks_in_progress_before_commit(configured, tracker_peer, supervisor_llm, monkeypatch):
    context, _, _, _ = tracker_peer
    enroll(configured)
    supervisor_llm("PASS")
    respond = OpenAICompatibleClient.respond

    def stopped_during_evaluation(*args, **kwargs):
        context["status"] = "Ready"
        return respond(*args, **kwargs)

    provider = Mock(side_effect=stopped_during_evaluation)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    response = step(configured, report=report_json("Work before the status changed"),
                    operation_key="status-changed-during-evaluation", expected_version=1)
    assert response.status_code == 409, response.text
    provider.assert_called_once()
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key(configured[1]["task"], project_id=configured[1]["namespace_id"])
        assert task.status == "active"
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 0


@pytest.mark.parametrize("configured", [("project_manager", "draft"), ("analyst", "analysis")], indirect=True)
def test_ready_first_instruction_does_not_broaden_history_or_later_phase_reads(
    configured, tracker_peer, supervisor_llm,
):
    context, _, _, _ = tracker_peer
    enroll(configured)
    supervisor_llm("PASS")
    accepted = step(configured, report=report_json("Completed first phase"),
                    operation_key="first-phase-done", expected_version=1)
    assert accepted.status_code == 200, accepted.text
    context["status"] = "Ready"
    assert step(configured).status_code == 409
    client, assignment = configured
    response = client.get("/internal/runtime/history", headers=MACHINE,
                          params={"interaction_protocol": "configured-cli-v1", "task": assignment["task"],
                                  "namespace_id": assignment["namespace_id"]})
    assert response.status_code == 409, response.text


def test_completed_workflow_replay_is_read_only_and_does_not_authorize_new_reports(
    configured, tracker_peer, supervisor_llm, monkeypatch,
):
    context, _, _, _ = tracker_peer
    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2, 3):
        command = {"report": report_json(f"Actual PM phase {version}"),
                   "operation_key": f"completed-pm-{version}", "expected_version": version}
        if version == 3:
            command.update(requirements_revision=2, requirements_sha256="a" * 64)
        accepted = step(configured, **command)
        assert accepted.status_code == 200, accepted.text
    context.update(stage="Backlog", status="Ready")
    provider = Mock(side_effect=AssertionError("Readback cannot invoke Advisor"))
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    replay = step(configured, **command)
    assert replay.status_code == 200, replay.text
    assert replay.json() == accepted.json()
    refused = step(configured, **{**command, "operation_key": "new-completed-report", "expected_version": 4})
    assert refused.status_code == 409, refused.text
    provider.assert_not_called()
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 3
