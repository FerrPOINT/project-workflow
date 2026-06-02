"""Task Key Validator — configurable regex validation for task identifiers.

Supports multiple project key formats:
  • Jira: AAT-123, PROJ-4567
  • Internal: TASKNEIROKLYUCH-42
  • Short: DEV-1, HOTFIX-99

Patterns are configurable via constructor for UI/CLI flexibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Pattern


@dataclass(frozen=True)
class ValidatedTaskKey:
    """Результат валидации ключа задачи."""
    raw: str
    is_valid: bool
    project: Optional[str] = None
    issue_number: Optional[str] = None
    matched_pattern: Optional[str] = None
    normalized: Optional[str] = None
    error_message: Optional[str] = None

    def __str__(self) -> str:
        return self.normalized or self.raw


class TaskKeyValidationError(Exception):
    """Выбрасывается при невалидном ключе задачи."""
    def __init__(self, key: str, reason: str):
        self.key = key
        self.reason = reason
        super().__init__(f"Invalid task key '{key}': {reason}")


# ── Default Patterns ────────────────────────────────────────────────────

# Named groups: (?P<prefix>...) and (?P<number>...) are REQUIRED for extraction
DEFAULT_PATTERNS = [
    # Jira standard: AAT-123, PROJ-4567, X-1
    r"^(?P<prefix>[A-Z][A-Z0-9]*)-(?P<number>[0-9]+)$",
    # Internal prefix: TASKNEIROKLYUCH-42
    r"^(?P<prefix>TASKNEIROKLYUCH)-(?P<number>[0-9]+)$",
    # Legacy HR Recruiter prefix
    r"^(?P<prefix>HRRECRUITER)-(?P<number>[0-9]+)$",
]

# Minimum lengths to prevent false positives like "X-1"
MIN_PREFIX_LEN = 2   # e.g. "AAT" (3) ok, "X" (1) — borderline
MIN_NUMBER_LEN = 1


class TaskKeyValidator:
    """Валидатор ключей задач с configurable regex patterns.

    Проверка: lowercase буквы, пробелы, подчеркивания -- до попытки совпадения с patterns.
    """

    # Default rejection patterns
    REJECT_PATTERNS = [
        (r"^-", "Ключ не может начинаться с дефиса"),
        (r"[ _+]", "Пробелы и подчеркивания запрещены -- используй дефис"),
        (r"^\d+$", "Только номер без префикса недопустим"),
    ]

    def __init__(
        self,
        patterns: Optional[List[str]] = None,
        strict: bool = True,
        min_prefix_len: int = MIN_PREFIX_LEN,
        min_number_len: int = MIN_NUMBER_LEN,
        reject_patterns: Optional[List[tuple]] = None,
    ):
        self.raw_patterns = patterns or DEFAULT_PATTERNS
        self._patterns: List[Pattern] = [re.compile(p) for p in self.raw_patterns]
        self.strict = strict
        self.min_prefix_len = min_prefix_len
        self.min_number_len = min_number_len
        self.reject_patterns = reject_patterns or self.REJECT_PATTERNS

    # ── Public API ──────────────────────────────────────────────────────

    def validate(self, key: str, raise_on_invalid: bool = False) -> ValidatedTaskKey:
        """Провалидировать ключ задачи.

        Args:
            key: Raw task key string (e.g. "AAT-123")
            raise_on_invalid: If True — raise TaskKeyValidationError on failure

        Returns:
            ValidatedTaskKey with project/number extraction if matched
        """
        if not key or not isinstance(key, str):
            result = ValidatedTaskKey(
                raw=str(key),
                is_valid=False,
                error_message="Key is empty or not a string",
            )
            if raise_on_invalid:
                raise TaskKeyValidationError(str(key), result.error_message or "empty")
            return result

        stripped = key.strip()

        # 1. Проверка lowercase
        if stripped.upper() != stripped:
            error_msg = (
                f"Key '{key}' содержит строчные буквы. "
                "Ключ задаётся В ВЕРХНЕМ РЕГИСТРЕ (например: AAT-123)"
            )
            result = ValidatedTaskKey(
                raw=key,
                is_valid=False,
                error_message=error_msg,
            )
            if raise_on_invalid:
                raise TaskKeyValidationError(key, error_msg)
            return result

        # 2. Reject patterns (пробелы, подчёркивания, неправильный формат)
        for pat, reason in self.reject_patterns:
            if re.search(pat, stripped):
                error_msg = f"Key '{key}' не прошёл проверку: {reason}"
                result = ValidatedTaskKey(
                    raw=key,
                    is_valid=False,
                    error_message=error_msg,
                )
                if raise_on_invalid:
                    raise TaskKeyValidationError(key, error_msg)
                return result

        # 3. Try each allowed pattern
        for raw_pat, compiled_pat in zip(self.raw_patterns, self._patterns):
            match = compiled_pat.match(stripped)
            if match:
                prefix = match.group("prefix")
                number = match.group("number")

                # Check minimum lengths
                if len(prefix) < self.min_prefix_len:
                    continue
                if len(number) < self.min_number_len:
                    continue

                normalized = f"{prefix}-{number}"
                result = ValidatedTaskKey(
                    raw=key,
                    is_valid=True,
                    project=prefix,
                    issue_number=number,
                    matched_pattern=raw_pat,
                    normalized=normalized,
                )
                return result

        # No match
        allowed = " | ".join(self.raw_patterns)
        error_msg = (
            f"Key '{stripped}' does not match any allowed pattern. "
            f"Expected formats: PROJECT-NUMBER (e.g. AAT-123, TASKNEIROKLYUCH-42). "
            f"Allowed patterns: {allowed}"
        )
        result = ValidatedTaskKey(
            raw=key,
            is_valid=False,
            error_message=error_msg,
        )
        if raise_on_invalid:
            raise TaskKeyValidationError(key, error_msg)
        return result

    def validate_or_die(self, key: str) -> ValidatedTaskKey:
        """Строгая валидация — выбрасывает исключение при ошибке."""
        return self.validate(key, raise_on_invalid=True)

    def is_valid(self, key: str) -> bool:
        """Быстрая проверка без создания полного результата."""
        return self.validate(key).is_valid

    # ── Factory Methods for UI ──────────────────────────────────────────

    @classmethod
    def from_patterns(cls, patterns: List[str]) -> "TaskKeyValidator":
        """Создать валидатор из списка regex patterns (для UI конфигурации)."""
        return cls(patterns=patterns)

    @classmethod
    def jira_only(cls) -> "TaskKeyValidator":
        """Валидатор только для Jira-ключей (AAT-123)."""
        return cls(patterns=[r"^(?P<prefix>[A-Z][A-Z0-9]*)-(?P<number>[0-9]+)$"])

    @classmethod
    def lenient(cls) -> "TaskKeyValidator":
        """Разрешительный валидатор — минимальные проверки."""
        return cls(
            patterns=[r"^(?P<prefix>[A-Za-z0-9]+)-(?P<number>[0-9]+)$"],
            min_prefix_len=1,
        )


# ── Module-level convenience ──────────────────────────────────────────

_default_validator = TaskKeyValidator()


def validate(key: str, raise_on_invalid: bool = False) -> ValidatedTaskKey:
    """Глобальная функция валидации (использует default patterns)."""
    return _default_validator.validate(key, raise_on_invalid)


def validate_or_die(key: str) -> ValidatedTaskKey:
    return _default_validator.validate_or_die(key)
