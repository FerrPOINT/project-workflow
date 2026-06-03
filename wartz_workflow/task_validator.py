"""Task Key Validator — configurable regex + migration support.

Features:
  • Multi-format validation (Jira, internal, legacy)
  • Automatic migration: HRRECRUITER-* → TASKNEIROKLYUCH-*
  • Configurable via YAML/constructor for UI flexibility
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Pattern


# ═════════════════════════════════════════════════════════════════════════
# MIGRATION MAP — legacy → new prefixes
# ═════════════════════════════════════════════════════════════════════════

LEGACY_MIGRATIONS = {
    "HRRECRUITER": "TASKNEIROKLYUCH",  # Старый HR Recruiter prefix
    "LEGACY": "TASKNEIROKLYUCH",           # Generic legacy
}


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
    # Migration info
    was_migrated: bool = False
    migrated_from: Optional[str] = None
    migrated_to: Optional[str] = None

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
    r"^(?P<prefix>[A-Z][A-Z0-9]*)-(?P<number>[0-9]+)$",   # Jira: AAT-123
    r"^(?P<prefix>TASKNEIROKLYUCH)-(?P<number>[0-9]+)$",  # Internal
    r"^(?P<prefix>HRRECRUITER)-(?P<number>[0-9]+)$",      # Legacy (auto-migrate)
]

# Minimum lengths to prevent false positives like "X-1"
MIN_PREFIX_LEN = 2
MIN_NUMBER_LEN = 1


class TaskKeyValidator:
    """Валидатор ключей задач с configurable regex + migration support."""

    REJECT_PATTERNS = [
        (r"^-", "Ключ не может начинаться с дефиса"),
        (r"[ _+]", "Пробелы и подчёркивания запрещены -- используй дефис"),
        (r"^\\d+$", "Только номер без префикса недопустим"),
    ]

    def __init__(
        self,
        patterns: Optional[List[str]] = None,
        strict: bool = True,
        min_prefix_len: int = MIN_PREFIX_LEN,
        min_number_len: int = MIN_NUMBER_LEN,
        reject_patterns: Optional[List[tuple]] = None,
        migrations: Optional[dict] = None,
    ):
        self.raw_patterns = patterns or DEFAULT_PATTERNS
        self._patterns: List[Pattern] = [re.compile(p) for p in self.raw_patterns]
        self.strict = strict
        self.min_prefix_len = min_prefix_len
        self.min_number_len = min_number_len
        self.reject_patterns = reject_patterns or self.REJECT_PATTERNS
        self.migrations = migrations if migrations is not None else LEGACY_MIGRATIONS
        self.skip_uppercase = False

    # ── Public API ──────────────────────────────────────────────────────

    def validate(self, key: str, raise_on_invalid: bool = False) -> ValidatedTaskKey:
        """Валидировать ключ задачи. Авто-миграция legacy → new.

        Args:
            key: Raw task key string (e.g. "AAT-123")
            raise_on_invalid: If True -- raise TaskKeyValidationError on failure

        Returns:
            ValidatedTaskKey with migration info if applicable
        """
        if not key or not isinstance(key, str):
            result = ValidatedTaskKey(
                raw=str(key), is_valid=False,
                error_message="Key is empty or not a string",
            )
            if raise_on_invalid:
                raise TaskKeyValidationError(str(key), result.error_message or "empty")
            return result

        stripped = key.strip()

        # 1. Uppercase check (skip for lenient mode)
        if not getattr(self, 'skip_uppercase', False) and stripped.upper() != stripped:
            error_msg = (
                f"Key '{key}' содержит строчные буквы. "
                "Ключ задаётся В ВЕРХНЕМ РЕГИСТРЕ (например: AAT-123)"
            )
            result = ValidatedTaskKey(raw=key, is_valid=False, error_message=error_msg)
            if raise_on_invalid:
                raise TaskKeyValidationError(key, error_msg)
            return result

        # 2. Reject patterns (spaces, underscores, etc.)
        for pat, reason in self.reject_patterns:
            if re.search(pat, stripped):
                error_msg = f"Key '{key}' не прошёл проверку: {reason}"
                result = ValidatedTaskKey(raw=key, is_valid=False, error_message=error_msg)
                if raise_on_invalid:
                    raise TaskKeyValidationError(key, error_msg)
                return result

        # 3. Try each allowed pattern (with migration)
        for raw_pat, compiled_pat in zip(self.raw_patterns, self._patterns):
            match = compiled_pat.match(stripped)
            if match:
                prefix = match.group("prefix")
                number = match.group("number")

                # Check minimum lengths
                if len(prefix) < self.min_prefix_len or len(number) < self.min_number_len:
                    continue

                # Migration: legacy prefix → new prefix
                was_migrated = False
                original_prefix = prefix
                if prefix in self.migrations:
                    original_prefix = prefix
                    prefix = self.migrations[prefix]
                    was_migrated = True

                normalized = f"{prefix}-{number}"
                result = ValidatedTaskKey(
                    raw=key,
                    is_valid=True,
                    project=prefix,
                    issue_number=number,
                    matched_pattern=raw_pat,
                    normalized=normalized,
                    was_migrated=was_migrated,
                    migrated_from=original_prefix if was_migrated else None,
                    migrated_to=prefix if was_migrated else None,
                )
                return result

        # No match
        allowed = " | ".join(self.raw_patterns)
        error_msg = (
            f"Key '{stripped}' does not match any allowed pattern. "
            f"Expected: PROJECT-NUMBER (e.g. AAT-123, TASKNEIROKLYUCH-42). "
            f"Patterns: {allowed}"
        )
        result = ValidatedTaskKey(raw=key, is_valid=False, error_message=error_msg)
        if raise_on_invalid:
            raise TaskKeyValidationError(key, error_msg)
        return result

    def validate_or_die(self, key: str) -> ValidatedTaskKey:
        """Строгая валидация — выбрасывает исключение при ошибке."""
        return self.validate(key, raise_on_invalid=True)

    def is_valid(self, key: str) -> bool:
        return self.validate(key).is_valid

    # ── Factory Methods ─────────────────────────────────────────────────

    @classmethod
    def from_patterns(cls, patterns: List[str]) -> "TaskKeyValidator":
        """Создать валидатор из списка regex patterns (для UI конфигурации)."""
        return cls(patterns=patterns)

    @classmethod
    def jira_only(cls) -> "TaskKeyValidator":
        """Валидатор только для чистых Jira-ключей (AAT-123), без internal/migration."""
        v = cls(
            patterns=[r"^(?P<prefix>[A-Z][A-Z0-9]*)-(?P<number>[0-9]+)$"],
            reject_patterns=[
                (r"^(TASKNEIROKLYUCH|HRRECRUITER)", "Internal/legacy prefixes excluded in Jira-only mode"),
            ] + cls.REJECT_PATTERNS,
        )
        return v

    @classmethod
    def lenient(cls) -> "TaskKeyValidator":
        """Разрешительный валидатор — минимальные проверки."""
        v = cls(
            patterns=[r"^(?P<prefix>[A-Za-z0-9]+)-(?P<number>[0-9]+)$"],
            min_prefix_len=1,
        )
        v.skip_uppercase = True
        return v

    @classmethod
    def with_migration(cls, migrations: Optional[dict] = None) -> "TaskKeyValidator":
        """Валидатор с кастомной картой миграций legacy → new."""
        return cls(migrations=migrations or LEGACY_MIGRATIONS)


# ── Module-level convenience ──────────────────────────────────────────

_default_validator = TaskKeyValidator(migrations=LEGACY_MIGRATIONS)


def validate(key: str, raise_on_invalid: bool = False) -> ValidatedTaskKey:
    """Глобальная функция валидации (использует default patterns + migration)."""
    return _default_validator.validate(key, raise_on_invalid)


def validate_or_die(key: str) -> ValidatedTaskKey:
    return _default_validator.validate_or_die(key)


def migrate_key(key: str) -> Optional[str]:
    """Fast migration: HRRECRUITER-42 -> TASKNEIROKLYUCH-42.

    Returns migrated key or None if not a legacy key.
    """
    match = re.match(r"^HRRECRUITER-(?P<number>[0-9]+)$", key.strip())
    if match:
        return f"TASKNEIROKLYUCH-{match.group('number')}"
    return None

# Backward-compat alias
ValidationResult = ValidatedTaskKey
