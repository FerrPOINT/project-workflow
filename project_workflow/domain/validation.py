"""Task-key validation and explicit run selection helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidatedTaskKey:
    """Результат валидации ключа задачи."""

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
    """Выбрасывается при невалидном ключе задачи."""

    def __init__(self, key: str, reason: str):
        self.key = key
        self.reason = reason
        super().__init__(f"Недопустимый ключ задачи '{key}': {reason}")


TASK_KEY_PATTERN = re.compile(r"^(?P<prefix>[A-Z][A-Z0-9]*)-(?P<number>[0-9]+)$")


class TaskKeyValidator:
    """Validate task keys without using configurable prefixes as routing rules."""

    REJECT_PATTERNS = [
        (r"^-", "Ключ не может начинаться с дефиса"),
        (r"[ _+]", "Пробелы и подчёркивания запрещены -- используй дефис"),
        (r"^\d+$", "Только номер без префикса недопустим"),
    ]

    def __init__(self, project_prefixes: list[dict[str, Any]]):
        self.prefix_to_project: dict[str, str | None] = {}
        for project in project_prefixes:
            project_code = project.get("code")
            if not isinstance(project_code, str) or not project_code.strip():
                raise ValueError("code должен быть непустой строкой")
            raw_prefixes = project.get("key_prefixes") or []
            if not isinstance(raw_prefixes, list) or not all(
                isinstance(prefix, str) for prefix in raw_prefixes
            ):
                raise ValueError("key_prefixes должен быть массивом строк")
            prefixes = [prefix.strip() for prefix in raw_prefixes if prefix.strip()]
            for prefix in prefixes:
                self.prefix_to_project.setdefault(prefix, project_code.strip())

    def validate(self, key: str) -> ValidatedTaskKey:
        """Validate a task key without inferring a selected workflow."""
        if not key or not isinstance(key, str):
            return ValidatedTaskKey(
                raw=str(key),
                is_valid=False,
                error_message="Ключ пуст или не является строкой",
            )

        stripped = key.strip()
        if stripped.upper() != stripped:
            error_msg = (
                f"Ключ '{key}' содержит строчные буквы. Ключ задаётся В ВЕРХНЕМ РЕГИСТРЕ "
                "(например: TASK-123)"
            )
            return ValidatedTaskKey(raw=key, is_valid=False, error_message=error_msg)

        for pat, reason in self.REJECT_PATTERNS:
            if re.search(pat, stripped):
                error_msg = f"Ключ '{key}' не прошёл проверку: {reason}"
                return ValidatedTaskKey(raw=key, is_valid=False, error_message=error_msg)

        match = TASK_KEY_PATTERN.fullmatch(stripped)
        if match:
            prefix = match.group("prefix")
            number = match.group("number")
            normalized = f"{prefix}-{number}"
            return ValidatedTaskKey(
                raw=key,
                is_valid=True,
                project=self.prefix_to_project.get(prefix),
                prefix=prefix,
                issue_number=number,
                normalized=normalized,
            )

        prefix_hint = stripped.split("-", 1)[0] if "-" in stripped else "TASK"
        if not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix_hint):
            prefix_hint = "TASK"
        error_msg = f"Ключ '{stripped}' должен соответствовать шаблону {prefix_hint}-<номер задачи>"
        return ValidatedTaskKey(raw=key, is_valid=False, error_message=error_msg)

    @classmethod
    def from_projects(cls, projects: list[dict[str, Any]]) -> TaskKeyValidator:
        """Create a validator from legacy rows without making prefixes authoritative."""
        return cls(projects)


def get_project_for_task_key(
    uow: Any,
    task_key: str,
    workflow_id: int | None = None,
    project_id: int | None = None,
) -> dict[str, Any] | None:
    """Resolve an explicitly scoped row for a valid task key."""
    if not TaskKeyValidator.from_projects([]).validate(str(task_key)).is_valid:
        return None
    matches: list[dict[str, Any]] = []
    for project in uow.projects.list():
        project_dict = project.to_dict() if hasattr(project, "to_dict") else dict(project)
        if project_id is not None and project_dict.get("id") != project_id:
            continue
        if workflow_id is not None and project_dict.get("workflow_id") != workflow_id:
            continue
        matches.append(project_dict)
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(
            f"Для ключа задачи {task_key!r} доступно несколько неймспейсов; запустите через нужный wrapper"
        )
    return matches[0]
