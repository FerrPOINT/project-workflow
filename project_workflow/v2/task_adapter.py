"""Configured task source used by the agent-facing ``current`` command."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any

from .engine import ContractViolation


@dataclass(frozen=True)
class TaskSnapshot:
    task_key: str
    summary: str
    description: str
    status: str
    issue_type_id: str
    issue_type: str
    profile: str
    jira_revision: str
    labels: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "taskKey": self.task_key,
            "summary": self.summary,
            "description": self.description,
            "status": self.status,
            "issueType": {"id": self.issue_type_id, "name": self.issue_type},
            "jiraRevision": self.jira_revision,
            "labels": list(self.labels),
        }


class CommandTaskAdapter:
    """Read one Jira task through a server-configured, credential-owning adapter."""

    def __init__(self, command: list[str], *, timeout_seconds: int = 30):
        if not command:
            raise ContractViolation("PROJECT_WORKFLOW_TASK_ADAPTER_COMMAND is empty")
        self.command = command
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_env(cls) -> CommandTaskAdapter:
        raw = os.getenv("PROJECT_WORKFLOW_TASK_ADAPTER_COMMAND", "").strip()
        if not raw:
            raise ContractViolation("PROJECT_WORKFLOW_TASK_ADAPTER_COMMAND is required")
        return cls(shlex.split(raw, posix=os.name != "nt"))

    def read(self, task_key: str) -> TaskSnapshot:
        try:
            completed = subprocess.run(
                [*self.command, task_key],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ContractViolation("configured Jira task adapter is unavailable") from exc
        if completed.returncode != 0:
            raise ContractViolation("configured Jira task adapter rejected the task")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ContractViolation("configured Jira task adapter returned invalid JSON") from exc
        if payload.get("ok") is True and isinstance(payload.get("result"), dict):
            payload = payload["result"]
        if payload.get("schemaVersion") != "sdlc-jira-issue/v1":
            raise ContractViolation("configured Jira task adapter returned an unsupported contract")
        if payload.get("taskKey") != task_key:
            raise ContractViolation("configured Jira task adapter returned another task")
        profile = payload.get("workflowProfile")
        if profile not in {"feature", "bug"}:
            raise ContractViolation("Jira issue type has no configured workflow profile")
        issue_type_id = str(payload.get("issueTypeId") or "")
        if not issue_type_id:
            raise ContractViolation("configured Jira task adapter omitted issueTypeId")
        jira_revision = str(payload.get("jiraRevision") or "")
        if not jira_revision:
            raise ContractViolation("configured Jira task adapter omitted jiraRevision")
        labels = payload.get("labels", [])
        if not isinstance(labels, list) or not all(isinstance(item, str) for item in labels):
            raise ContractViolation("configured Jira task adapter returned invalid labels")
        return TaskSnapshot(
            task_key=task_key,
            summary=str(payload.get("summary") or ""),
            description=str(payload.get("description") or ""),
            status=str(payload.get("status") or ""),
            issue_type_id=issue_type_id,
            issue_type=str(payload.get("issueType") or ""),
            profile=profile,
            jira_revision=jira_revision,
            labels=tuple(labels),
        )
