"""Task Key Validator — configurable prefix-based validation.

Features:
  • Multi-format validation (Jira, internal)
  • Configurable via YAML/constructor for UI flexibility
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional, Pattern


@dataclass(frozen=True)
class ValidatedTaskKey:
    """Результат валидации ключа задачи."""

    raw: str
    is_valid: bool
    project: Optional[str] = None
    prefix: Optional[str] = None
    issue_number: Optional[str] = None
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


# ── Defaults ────────────────────────────────────────────────────────────

DEFAULT_PREFIXES = ["AAT", "TASK"]

# Minimum lengths to prevent false positives like "X-1"
MIN_PREFIX_LEN = 2
MIN_NUMBER_LEN = 1

# Valid prefix characters: uppercase letters and digits
PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9]*$")


def _prefixes_to_regex(prefixes: List[str]) -> str:
    """Build a regex from plain prefixes that captures prefix and number."""
    escaped = [re.escape(p) for p in prefixes if p]
    if not escaped:
        # Match nothing
        return r"$^"
    return r"^(?P<prefix>" + "|".join(escaped) + r")-(?P<number>[0-9]+)$"


def _compile_raw_pattern(raw: str) -> tuple[str, Pattern]:
    """Compile a raw regex string, ensuring prefix/number groups exist."""
    return (raw, re.compile(raw))


class TaskKeyValidator:
    """Валидатор ключей задач с configurable prefixes."""

    REJECT_PATTERNS = [
        (r"^-", "Ключ не может начинаться с дефиса"),
        (r"[ _+]", "Пробелы и подчёркивания запрещены -- используй дефис"),
        (r"^\\d+$", "Только номер без префикса недопустим"),
    ]

    def __init__(
        self,
        prefixes: Optional[List[str]] = None,
        patterns: Optional[List[str]] = None,
        project_prefixes: Optional[List[dict]] = None,
        strict: bool = True,
        min_prefix_len: int = MIN_PREFIX_LEN,
        min_number_len: int = MIN_NUMBER_LEN,
        reject_patterns: Optional[List[tuple]] = None,
    ):
        self.project_prefixes = project_prefixes or []
        self.raw_patterns = patterns or []
        if self.project_prefixes:
            self.pattern_sources: List[tuple[Optional[str], str, Pattern]] = []
            self.project_prefix_lists: List[tuple[Optional[str], List[str]]] = []
            for project in self.project_prefixes:
                project_code = project.get("code")
                raw_project_prefixes = project.get("key_prefixes") or project.get("prefixes") or []
                if isinstance(raw_project_prefixes, str):
                    try:
                        parsed = json.loads(raw_project_prefixes)
                        raw_project_prefixes = parsed if isinstance(parsed, list) else [raw_project_prefixes]
                    except Exception:
                        raw_project_prefixes = [raw_project_prefixes]
                project_prefixes_list = [str(p) for p in raw_project_prefixes if str(p).strip()]
                if project_prefixes_list:
                    regex_text = _prefixes_to_regex(project_prefixes_list)
                    self.pattern_sources.append((project_code, regex_text, re.compile(regex_text)))
                    self.project_prefix_lists.append((project_code, project_prefixes_list))
            self.raw_prefixes = [raw for _, raw, _ in self.pattern_sources]
        elif prefixes is not None or self.raw_patterns:
            self.raw_prefixes = prefixes or []
            regex_text = _prefixes_to_regex(self.raw_prefixes)
            self.pattern_sources = [(None, regex_text, re.compile(regex_text))]
            self.project_prefix_lists = []
            for raw in self.raw_patterns:
                self.pattern_sources.append((None, raw, re.compile(raw)))
        else:
            self.raw_prefixes = DEFAULT_PREFIXES
            regex_text = _prefixes_to_regex(self.raw_prefixes)
            self.pattern_sources = [(None, regex_text, re.compile(regex_text))]
            self.project_prefix_lists = []
        self.strict = strict
        self.min_prefix_len = min_prefix_len
        self.min_number_len = min_number_len
        self.reject_patterns = reject_patterns or self.REJECT_PATTERNS
        self.skip_uppercase = False

    # ── Public API ──────────────────────────────────────────────────────

    def validate(self, key: str, raise_on_invalid: bool = False) -> ValidatedTaskKey:
        """Валидировать ключ задачи.

        Args:
            key: Raw task key string (e.g. "AAT-123")
            raise_on_invalid: If True -- raise TaskKeyValidationError on failure

        Returns:
            ValidatedTaskKey
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

        # 1. Uppercase check (skip for lenient mode)
        if not getattr(self, "skip_uppercase", False) and stripped.upper() != stripped:
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

        # 3. Try each allowed pattern
        for project_code, raw_pat, compiled_pat in self.pattern_sources:
            match = compiled_pat.match(stripped)
            if match:
                prefix = match.group("prefix")
                number = match.group("number")

                # Check minimum lengths
                if len(prefix) < self.min_prefix_len or len(number) < self.min_number_len:
                    continue

                normalized = f"{prefix}-{number}"
                result = ValidatedTaskKey(
                    raw=key,
                    is_valid=True,
                    project=project_code or prefix,
                    prefix=prefix,
                    issue_number=number,
                    normalized=normalized,
                )
                return result

        # No match
        allowed = ", ".join(self.raw_prefixes)
        error_msg = (
            f"Key '{stripped}' does not match any allowed prefix. "
            f"Expected: PREFIX-NUMBER (e.g. {allowed}-123). "
            f"Prefixes: {allowed}"
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
    def from_prefixes(cls, prefixes: List[str]) -> "TaskKeyValidator":
        """Создать валидатор из списка plain prefixes (для UI конфигурации)."""
        return cls(prefixes=prefixes)

    @classmethod
    def from_projects(cls, projects: List[dict]) -> "TaskKeyValidator":
        """Создать валидатор из project rows с key_prefixes."""
        return cls(project_prefixes=projects)

    @classmethod
    def jira_only(cls) -> "TaskKeyValidator":
        """Валидатор только для чистых Jira-ключей (AAT-123), без internal prefixes."""
        return cls(prefixes=["AAT"], reject_patterns=cls.REJECT_PATTERNS)

    @classmethod
    def lenient(cls) -> "TaskKeyValidator":
        """Разрешительный валидатор — минимальные проверки."""
        v = cls(
            prefixes=[],
            patterns=[r"^(?P<prefix>[A-Za-z]+)-(?P<number>[0-9]+)$"],
            min_prefix_len=1,
        )
        v.skip_uppercase = True
        return v


# ── Module-level convenience ──────────────────────────────────────────

_default_validator = TaskKeyValidator()


def validate(key: str, raise_on_invalid: bool = False) -> ValidatedTaskKey:
    """Глобальная функция валидации (использует default prefixes)."""
    return _default_validator.validate(key, raise_on_invalid)


def validate_or_die(key: str) -> ValidatedTaskKey:
    return _default_validator.validate_or_die(key)


# Backward-compat alias
ValidationResult = ValidatedTaskKey
