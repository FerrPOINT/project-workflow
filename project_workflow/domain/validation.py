"""Validation and project resolution for configured Jira task keys."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

TASK_KEY_RE = re.compile(r"^(?P<prefix>[A-Z][A-Z0-9]+)-(?P<number>[0-9]+)$")


@dataclass(frozen=True)
class ValidatedTaskKey:
    raw: str
    is_valid: bool
    project: str | None = None
    prefix: str | None = None
    issue_number: str | None = None
    normalized: str | None = None
    error_message: str | None = None

    def __str__(self) -> str:
        return self.normalized or self.raw


class TaskKeyValidationError(ValueError):
    def __init__(self, key: str, reason: str):
        self.key = key
        self.reason = reason
        super().__init__(f"Invalid task key '{key}': {reason}")


class TaskKeyValidator:
    """Validate Jira keys against the exact prefixes configured for projects."""

    def __init__(
        self,
        prefixes: list[str] | None = None,
        project_prefixes: list[dict[str, Any]] | None = None,
    ) -> None:
        self._projects_by_prefix: dict[str, str | None] = {}
        for prefix in prefixes or []:
            self._add_prefix(str(prefix), None)
        for project in project_prefixes or []:
            project_code = str(project.get("code") or "").strip() or None
            raw_prefixes = project.get("key_prefixes") or []
            if not isinstance(raw_prefixes, list):
                raise ValueError(f"Project {project_code or '<unknown>'} key_prefixes must be a list")
            for prefix in raw_prefixes:
                self._add_prefix(str(prefix), project_code)

    def _add_prefix(self, raw_prefix: str, project_code: str | None) -> None:
        prefix = raw_prefix.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]+", prefix):
            raise ValueError(f"Invalid task key prefix: {raw_prefix!r}")
        previous = self._projects_by_prefix.get(prefix)
        if prefix in self._projects_by_prefix and previous != project_code:
            raise ValueError(f"Task key prefix {prefix} is configured for multiple projects")
        self._projects_by_prefix[prefix] = project_code

    def validate(self, key: str, raise_on_invalid: bool = False) -> ValidatedTaskKey:
        raw = str(key)
        stripped = key.strip() if isinstance(key, str) else ""
        match = TASK_KEY_RE.fullmatch(stripped)
        if not match:
            return self._invalid(raw, "Expected an uppercase Jira key in PREFIX-NUMBER format", raise_on_invalid)

        prefix = match.group("prefix")
        if prefix not in self._projects_by_prefix:
            allowed = ", ".join(sorted(self._projects_by_prefix)) or "none configured"
            message = f"Prefix {prefix} is not configured; allowed prefixes: {allowed}"
            return self._invalid(raw, message, raise_on_invalid)

        number = match.group("number")
        normalized = f"{prefix}-{number}"
        return ValidatedTaskKey(
            raw=raw,
            is_valid=True,
            project=self._projects_by_prefix[prefix] or prefix,
            prefix=prefix,
            issue_number=number,
            normalized=normalized,
        )

    @staticmethod
    def _invalid(raw: str, reason: str, raise_on_invalid: bool) -> ValidatedTaskKey:
        if raise_on_invalid:
            raise TaskKeyValidationError(raw, reason)
        return ValidatedTaskKey(raw=raw, is_valid=False, error_message=reason)

    def validate_or_die(self, key: str) -> ValidatedTaskKey:
        return self.validate(key, raise_on_invalid=True)

    def is_valid(self, key: str) -> bool:
        return self.validate(key).is_valid

    @classmethod
    def from_prefixes(cls, prefixes: list[str]) -> TaskKeyValidator:
        return cls(prefixes=prefixes)

    @classmethod
    def from_projects(cls, projects: list[dict[str, Any]]) -> TaskKeyValidator:
        return cls(project_prefixes=projects)


def get_project_for_task_key(uow: Any, task_key: str) -> dict[str, Any] | None:
    """Resolve a task key through the configured project prefix mapping."""
    projects = [row.to_dict() if hasattr(row, "to_dict") else dict(row) for row in uow.projects.list()]
    validated = TaskKeyValidator.from_projects(projects).validate(task_key)
    if not validated.is_valid:
        return None
    return next((project for project in projects if project.get("code") == validated.project), None)
