"""A retained namespace can share a human key with the single active protocol."""

import json
from contextlib import contextmanager

from sqlalchemy import select

from project_workflow import config
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._retained_pm_history import retained_pm
from tests.test_configured_cli import MACHINE, enroll, step
from tests.test_configured_cli import configured as configured


def test_same_key_in_legacy_and_configured_namespaces_keeps_history_separate(
    configured,
    monkeypatch,
    supervisor_llm,
):
    client, assignment = configured
    with contextmanager(retained_pm)(monkeypatch, task_key=assignment["task"]):
        with SAUnitOfWork() as uow:
            namespace = uow.projects.get_by_cli_command("workflow-project_manager")
            old = uow.tasks.get_by_key(assignment["task"], project_id=namespace.id)
            old_id, old_namespace = old.id, namespace.id
            uow.record_step(
                task_id=old.id,
                phase_id=old.current_phase_id,
                verdict="pass",
                worker_report="Retained namespace's original report",
                covered_item_ids=[],
                missing_item_ids=[],
                blocker_messages=[],
                evaluation_snapshot={"original": "archived"},
                supervisor_response={"status": "active"},
            )
            old_history = [row.to_dict() for row in uow.step_history.list(task_id=old_id)]
        monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"project_manager": "w" * 40}))
        monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", "")
        config.get_settings.cache_clear()
        cursor = enroll(configured)
        supervisor_llm("PASS")
        response = step(
            configured,
            report="New namespace's own report",
            operation_key="namespace-separated",
            expected_version=cursor["version"],
        )
        assert response.status_code == 200, response.text
        history = client.get(
            "/internal/runtime/history",
            headers=MACHINE,
            params={
                "interaction_protocol": "configured-cli-v1",
                "task": assignment["task"],
                "namespace_id": assignment["namespace_id"],
            },
        )
        assert history.status_code == 200, history.text
        assert len(history.json()["result"]["records"]) == 1
        assert history.json()["result"]["records"][0]["worker_report"] == "New namespace's own report"
        with SAUnitOfWork() as uow:
            new = uow.tasks.get_by_key(assignment["task"], project_id=assignment["namespace_id"])
            assert new.id != old_id and new.project_id != old_namespace
            assert [row.to_dict() for row in uow.step_history.list(task_id=old_id)] == old_history
            assert uow.session.scalar(select(m.PMExecution).where(m.PMExecution.task_id == old_id)) is not None
            assert uow.session.scalar(select(m.PMExecution).where(m.PMExecution.task_id == new.id)) is None
