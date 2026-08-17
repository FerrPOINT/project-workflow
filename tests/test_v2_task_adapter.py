from __future__ import annotations

import json
import subprocess

import pytest

from project_workflow.v2.engine import ContractViolation
from project_workflow.v2.task_adapter import CommandTaskAdapter


def test_command_task_adapter_returns_exact_configured_profile(monkeypatch):
    payload = {
        "schemaVersion": "sdlc-jira-issue/v1",
        "taskKey": "AAT-77",
        "summary": "Добавить фильтры",
        "description": "Фильтры списка заявок",
        "status": "Сделать",
        "issueTypeId": "10001",
        "issueType": "История",
        "workflowProfile": "feature",
        "labels": ["agentic-e2e"],
        "jiraRevision": "2026-08-17T10:00:00+0300",
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    task = CommandTaskAdapter(["jira-task", "read"]).read("AAT-77")

    assert task.profile == "feature"
    assert task.issue_type_id == "10001"
    assert task.as_dict()["issueType"] == {"id": "10001", "name": "История"}


def test_command_task_adapter_blocks_unknown_issue_type_mapping(monkeypatch):
    payload = {
        "schemaVersion": "sdlc-jira-issue/v1",
        "taskKey": "AAT-77",
        "issueTypeId": "99999",
        "issueType": "Unknown",
        "workflowProfile": None,
        "jiraRevision": "jira-1",
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    with pytest.raises(ContractViolation, match="no configured workflow profile"):
        CommandTaskAdapter(["jira-task", "read"]).read("AAT-77")


def test_command_task_adapter_unwraps_intake_client_envelope(monkeypatch):
    payload = {
        "ok": True,
        "result": {
            "schemaVersion": "sdlc-jira-issue/v1",
            "taskKey": "AAT-78",
            "summary": "Исправить гонку",
            "description": "Два решения конфликтуют",
            "status": "Сделать",
            "issueTypeId": "10102",
            "issueType": "Ошибка",
            "workflowProfile": "bug",
            "labels": [],
            "jiraRevision": "2026-08-17T10:00:00+0300",
        },
    }
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout=json.dumps(payload), stderr=""
        ),
    )

    task = CommandTaskAdapter(["sdlc-jira-intake", "read"]).read("AAT-78")

    assert task.profile == "bug"
    assert task.issue_type_id == "10102"
