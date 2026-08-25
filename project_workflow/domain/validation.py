"""Task-key validation against project prefixes stored in PostgreSQL."""

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


def _prefixes_to_regex(prefixes: list[str]) -> str:
    """Build a regex from plain prefixes that captures prefix and number."""
    escaped = [re.escape(p) for p in prefixes if p]
    if not escaped:
        # Match nothing
        return r"$^"
    return r"^(?P<prefix>" + "|".join(escaped) + r")-(?P<number>[0-9]+)$"

class TaskKeyValidator:
    """Validate task keys using the projects currently configured in the database."""

    REJECT_PATTERNS = [
        (r"^-", "Ключ не может начинаться с дефиса"),
        (r"[ _+]", "Пробелы и подчёркивания запрещены -- используй дефис"),
        (r"^\\d+$", "Только номер без префикса недопустим"),
    ]

    def __init__(self, project_prefixes: list[dict[str, Any]]):
        self.pattern_sources: list[tuple[str | None, re.Pattern[str]]] = []
        self.raw_prefixes: list[str] = []
        for project in project_prefixes:
            project_code = project.get("code")
            raw_prefixes = project.get("key_prefixes") or []
            if not isinstance(raw_prefixes, list) or not all(
                isinstance(prefix, str) for prefix in raw_prefixes
            ):
                raise ValueError("key_prefixes проекта должен быть массивом строк")
            prefixes = [str(prefix).strip() for prefix in raw_prefixes if str(prefix).strip()]
            if prefixes:
                self.raw_prefixes.extend(prefixes)
                pattern = re.compile(_prefixes_to_regex(prefixes))
                self.pattern_sources.append((str(project_code) if project_code else None, pattern))

    def validate(self, key: str) -> ValidatedTaskKey:
        """Validate a task key without inventing a default project."""
        if not key or not isinstance(key, str):
            return ValidatedTaskKey(
                raw=str(key),
                is_valid=False,
                error_message="Ключ пуст или не является строкой",
            )

        stripped = key.strip()
        example_prefix = self.raw_prefixes[0] if self.raw_prefixes else "PREFIX"
        if stripped.upper() != stripped:
            error_msg = (
                f"Ключ '{key}' содержит строчные буквы. Ключ задаётся В ВЕРХНЕМ РЕГИСТРЕ "
                f"(например: {example_prefix}-123)"
            )
            return ValidatedTaskKey(raw=key, is_valid=False, error_message=error_msg)

        for pat, reason in self.REJECT_PATTERNS:
            if re.search(pat, stripped):
                error_msg = f"Ключ '{key}' не прошёл проверку: {reason}"
                return ValidatedTaskKey(raw=key, is_valid=False, error_message=error_msg)

        for project_code, pattern in self.pattern_sources:
            match = pattern.fullmatch(stripped)
            if match:
                prefix = match.group("prefix")
                number = match.group("number")
                normalized = f"{prefix}-{number}"
                return ValidatedTaskKey(
                    raw=key,
                    is_valid=True,
                    project=project_code,
                    prefix=prefix,
                    issue_number=number,
                    normalized=normalized,
                )

        matching_prefix = next(
            (
                prefix
                for prefix in self.raw_prefixes
                if stripped == prefix or stripped.startswith(f"{prefix}-")
            ),
            None,
        )
        if matching_prefix is not None:
            return ValidatedTaskKey(
                raw=key,
                is_valid=False,
                error_message=(
                    f"Ключ '{stripped}' должен соответствовать шаблону {matching_prefix}-<номер задачи>"
                ),
            )

        allowed = ", ".join(self.raw_prefixes) or "нет настроенных префиксов"
        error_msg = (
            f"Ключ '{stripped}' не соответствует ни одному разрешённому префиксу. "
            f"Префиксы: {allowed}"
        )
        return ValidatedTaskKey(raw=key, is_valid=False, error_message=error_msg)

    @classmethod
    def from_projects(cls, projects: list[dict[str, Any]]) -> TaskKeyValidator:
        """Создать валидатор из project rows с key_prefixes."""
        return cls(projects)


def get_project_for_task_key(uow: Any, task_key: str) -> dict[str, Any] | None:
    """Resolve a project row from a task key using configured project prefixes."""
    match = re.fullmatch(r"(?P<prefix>[A-Z][A-Z0-9]*)-(?P<number>[0-9]+)", str(task_key).strip())
    if match is None:
        return None
    prefix = match.group("prefix")
    for project in uow.projects.list():
        project_dict = project.to_dict() if hasattr(project, "to_dict") else dict(project)
        key_prefixes = project_dict.get("key_prefixes", []) or []
        if not isinstance(key_prefixes, list) or not all(
            isinstance(item, str) for item in key_prefixes
        ):
            raise ValueError("key_prefixes проекта должен быть массивом строк")
        if prefix in key_prefixes:
            return project_dict
    return None
