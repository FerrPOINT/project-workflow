"""Tests for task_validator.py — configurable task key validation."""

import pytest
from wartz_workflow.task_validator import (
    TaskKeyValidator,
    TaskKeyValidationError,
    validate_or_die,
    validate,
    DEFAULT_PATTERNS,
)


class TestValidKeys:
    """Ключи которые должны проходить валидацию."""

    @pytest.mark.parametrize("key", [
        "AAT-123",
        "AAT-1",
        "PROJ-4567",
        "DEV-1",
        "FE-42",
        "HOTFIX-99",
        "TASKNEIROKLYUCH-42",
        "HRRECRUITER-7",
        "XX-1",
    ])
    def test_standard_keys_pass(self, key):
        v = TaskKeyValidator()
        result = v.validate(key)
        assert result.is_valid, f"Expected {key} to be valid"
        assert result.normalized == key.upper()

    def test_prefix_extraction(self):
        v = TaskKeyValidator()
        result = v.validate("AAT-12345")
        assert result.project == "AAT"
        assert result.issue_number == "12345"

    def test_internal_neiro_prefix(self):
        v = TaskKeyValidator()
        result = v.validate("TASKNEIROKLYUCH-99")
        assert result.is_valid
        assert result.project == "TASKNEIROKLYUCH"


class TestInvalidKeys:
    """Ключи которые должны отклоняться."""

    @pytest.mark.parametrize("key,contains_reason", [
        ("aat-123", "ВЕРХНЕМ РЕГИСТРЕ"),
        ("", "empty"),
        ("123", "префикса недопустим"),
        ("AAT", "does not match"),
        ("AAT-ABC", "does not match"),
        ("PROJ_456", "дефис"),
        ("MY TASK-1", "дефис"),
        ("-123", "дефис"),
        ("X-1", "does not match"),  # min_prefix_len=2 blocks single-char prefix
    ])
    def test_invalid_keys_rejected(self, key, contains_reason):
        v = TaskKeyValidator()
        result = v.validate(key)
        assert not result.is_valid, f"Expected {key!r} to be invalid"
        msg = result.error_message or ""
        assert contains_reason.lower() in msg.lower() or \
               contains_reason in msg, \
               f"Expected reason containing '{contains_reason}' but got: {msg}"

    def test_raise_on_invalid(self):
        v = TaskKeyValidator()
        with pytest.raises(TaskKeyValidationError) as exc:
            v.validate("invalid-key", raise_on_invalid=True)
        assert "invalid-key" in str(exc.value)

    def test_validate_or_die_raises(self):
        with pytest.raises(TaskKeyValidationError):
            validate_or_die("invalid")


class TestStrict:
    """Строгая валидация: минимальные длины префикса/номера."""

    def test_short_prefix_blocked_in_strict(self):
        v = TaskKeyValidator(min_prefix_len=3)
        result = v.validate("X-1")
        assert not result.is_valid  # prefix "X" length 1 < 3

    def test_lenient_allows_short_prefix(self):
        v = TaskKeyValidator.lenient()
        result = v.validate("X-1")
        assert result.is_valid  # lenient allows 1-char prefix

    def test_short_number_blocked(self):
        v = TaskKeyValidator(min_number_len=2)
        result = v.validate("AAT-1")
        assert not result.is_valid  # number "1" length 1 < 2


class TestCustomPatterns:
    """Конфигурация через произвольные patterns (для UI)."""

    def test_custom_pattern(self):
        patterns = [r"^(?P<prefix>CUSTOM)-(?P<number>[0-9]{3,})$"]
        v = TaskKeyValidator.from_patterns(patterns)
        assert v.validate("CUSTOM-001").is_valid
        assert not v.validate("OTHER-001").is_valid

    def test_jira_only(self):
        v = TaskKeyValidator.jira_only()
        assert v.validate("AAT-123").is_valid
        # jira_only uses broad jira pattern -- it CAN match internal prefixes
        assert v.validate("TASKNEIROKLYUCH-42").is_valid
        assert not v.validate("lower-42").is_valid  # lowercase rejected

    def test_multiple_patterns(self):
        patterns = [
            r"^(?P<prefix>BUG)-(?P<number>[0-9]+)$",
            r"^(?P<prefix>FEATURE)-(?P<number>[0-9]+)$",
        ]
        v = TaskKeyValidator.from_patterns(patterns)
        assert v.validate("BUG-1").is_valid
        assert v.validate("FEATURE-99").is_valid
        assert not v.validate("AAT-1").is_valid


class TestValidatedTaskKeyDataclass:
    def test_str_returns_normalized(self):
        result = validate("AAT-123")
        assert str(result) == "AAT-123"

    def test_none_project_for_invalid(self):
        result = validate("invalid")
        assert result.project is None
        assert result.issue_number is None


class TestGlobalFunctions:
    def test_global_validate(self):
        assert validate("AAT-1").is_valid
        assert not validate("bad-key").is_valid

    def test_global_validate_raises(self):
        with pytest.raises(TaskKeyValidationError):
            validate_or_die("bad")
