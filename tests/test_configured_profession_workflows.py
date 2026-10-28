"""Custom profession workflows use the same configured API and authority gates."""

from uuid import uuid4

import pytest

from project_workflow.application import configured_cli
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_configured_cli import MACHINE, WRITER, enroll, step
from tests.test_configured_cli import configured as configured


def add_workflow(assignment, *, linked=True):
    with SAUnitOfWork() as uow:
        workflow = uow.workflows.create({"key": "custom-file-work", "name": "File work",
                                         "create_default_mode": False})
        mode = uow.workflows.create_mode({"workflow_id": workflow, "key": assignment["mode_key"],
                                         "name": "File work", "mode_order": 1})
        for number in (1, 2, 3):
            phase = uow.phases.create({"workflow_id": workflow, "mode_id": mode,
                "code": f"FILE-{number}", "name": f"Files {number}", "phase_order": number})
            uow.phase_instructions.create(phase, {"step_num": 1, "description": f"Actual file instruction {number}"})
            uow.phase_checks.create(phase, {"description": "Files checked"})
        if linked:
            uow.workflows.assign_profession(workflow, assignment["namespace_id"])
    assignment["workflow_key"] = "custom-file-work"
    return workflow


@pytest.mark.parametrize("configured", [("project_manager", "draft"), ("developer", "rework")], indirect=True)
def test_assigned_custom_workflow_reads_and_advances_its_own_phases(configured, supervisor_llm):
    client, assignment = configured
    add_workflow(assignment)
    cursor = enroll(configured)
    read = step(configured)
    assert read.status_code == 200, read.text
    assert "Actual file instruction 1" in read.json()["result"]["instructions"]
    supervisor_llm("PASS")
    response = step(configured, report="Files checked", operation_key="custom-first",
                    expected_version=cursor["version"])
    assert response.status_code == 200, response.text
    assert response.json()["result"]["phase_code"] == "FILE-2"
    assert "Actual file instruction 2" in step(configured).json()["result"]["instructions"]
    history = client.get("/internal/runtime/history", headers=MACHINE, params={
        "interaction_protocol": "configured-cli-v1", "task": assignment["task"],
        "namespace_id": assignment["namespace_id"],
    })
    assert history.status_code == 200, history.text
    assert history.json()["result"]["records"][0]["worker_report"] == "Files checked"


def test_custom_workflow_outside_profession_is_not_enrolled(configured):
    client, assignment = configured
    add_workflow(assignment, linked=False)
    response = client.post("/internal/runtime/assign", headers=WRITER, json=assignment)
    assert response.status_code == 409
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_by_key(assignment["task"], project_id=assignment["namespace_id"]) is None


def test_detached_workflow_history_is_readable_but_cannot_execute(configured, supervisor_llm):
    client, assignment = configured
    workflow = add_workflow(assignment)
    enroll(configured)
    supervisor_llm("PASS")
    assert step(configured, report="First files checked", operation_key="before-unlink",
                expected_version=1).status_code == 200
    from sqlalchemy import delete

    from project_workflow.infrastructure.db.models import ProfessionWorkflow

    with SAUnitOfWork() as uow:
        uow.session.execute(delete(ProfessionWorkflow).where(ProfessionWorkflow.workflow_id == workflow))
    assert step(configured).status_code == 409
    assert step(configured, report="Must not advance", operation_key="after-unlink",
                expected_version=2).status_code == 409
    history = client.get("/internal/runtime/history", headers=MACHINE, params={
        "interaction_protocol": "configured-cli-v1", "task": assignment["task"],
        "namespace_id": assignment["namespace_id"],
    })
    assert history.status_code == 200, history.text
    assert [row["worker_report"] for row in history.json()["result"]["records"]] == ["First files checked"]


def test_custom_pm_terminal_requires_exact_owner_confirmation(configured, supervisor_llm, monkeypatch):
    _, assignment = configured
    add_workflow(assignment)
    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2):
        assert step(configured, report="Files checked", operation_key=f"file-{version}",
                    expected_version=version).status_code == 200
    assert step(configured).json()["result"]["report_parameters"] == [
        "--requirements-revision", "--requirements-sha256"]

    def absent(_payload):
        raise ConflictError("No real owner confirmation")

    monkeypatch.setattr(configured_cli, "confirmation", absent)
    final = {"report": "All files verified", "operation_key": "file-final", "expected_version": 3,
             "requirements_revision": 4, "requirements_sha256": "a" * 64}
    assert step(configured, **final).status_code == 409
    assert step(configured).json()["result"]["version"] == 3
    confirmed = {"id": str(uuid4()), "task_id": assignment["tracker_task_id"], "revision": 5,
                 "content_hash": "b" * 64, "owner_subject": assignment["owner_subject"], "stage": "Draft"}
    monkeypatch.setattr(configured_cli, "confirmation", lambda _: dict(confirmed))
    assert step(configured, **final).status_code == 409
    accepted = step(configured, **{**final, "requirements_revision": 5, "requirements_sha256": "b" * 64})
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()["result"]
    assert result["complete"] is True
    assert result["terminal_receipt"]["confirmation_id"] == confirmed["id"]


def test_membership_revoked_during_model_call_cannot_commit_progress(configured, supervisor_llm, monkeypatch):
    from sqlalchemy import delete

    from project_workflow.infrastructure.db.models import ProfessionWorkflow
    from project_workflow.infrastructure.llm import OpenAICompatibleClient

    client, assignment = configured
    workflow = add_workflow(assignment)
    enroll(configured)
    supervisor_llm("PASS")
    evaluate = OpenAICompatibleClient.chat

    def revoke(*args, **kwargs):
        with SAUnitOfWork() as uow:
            uow.session.execute(delete(ProfessionWorkflow).where(ProfessionWorkflow.workflow_id == workflow))
        return evaluate(*args, **kwargs)

    monkeypatch.setattr(OpenAICompatibleClient, "chat", revoke)
    result = step(configured, report="Files checked", operation_key="revoked-during-model", expected_version=1)
    assert result.status_code == 409, result.text
    history = client.get("/internal/runtime/history", headers=MACHINE, params={
        "interaction_protocol": "configured-cli-v1", "task": assignment["task"],
        "namespace_id": assignment["namespace_id"],
    })
    assert history.status_code == 200, history.text
    assert history.json()["result"]["records"] == []
    assert history.json()["result"]["version"] == 1
