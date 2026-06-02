"""Tests for task_validator with migration support."""

import pytest
from wartz_workflow.task_validator import (
    TaskKeyValidator, TaskKeyValidationError,
    migrate_key, validate, validate_or_die, ValidatedTaskKey,
)


class TestValidationBasics:
    def test_valid_jira(self):
        result = validate("AAT-123")
        assert result.is_valid
        assert result.project == "AAT"
        assert result.issue_number == "123"
        assert result.normalized == "AAT-123"

    def test_valid_internal(self):
        result = validate("TASKNEIROKLYUCH-42")
        assert result.is_valid
        assert result.project == "TASKNEIROKLYUCH"
        assert result.normalized == "TASKNEIROKLYUCH-42"

    def test_invalid_lowercase(self):
        result = validate("aat-123")
        assert not result.is_valid
        assert "ВЕРХНЕМ РЕГИСТРЕ" in (result.error_message or "")

    def test_invalid_no_number(self):
        result = validate("AAT")
        assert not result.is_valid

    def test_invalid_spaces(self):
        result = validate("AAT 123")
        assert not result.is_valid


class TestMigration:
    def test_legacy_hrrecruiter_migrates(self):
        result = validate("HRRECRUITER-7")
        assert result.is_valid
        assert result.was_migrated is True
        assert result.normalized == "TASKNEIROKLYUCH-7"
        assert result.migrated_from == "HRRECRUITER"
        assert result.migrated_to == "TASKNEIROKLYUCH"

    def test_legacy_not_migrates_on_explicit_no_migration(self):
        v = TaskKeyValidator(migrations={})
        result = v.validate("HRRECRUITER-7")
        assert result.is_valid  # Still valid (pattern matches)
        assert result.was_migrated is False
        assert result.project == "HRRECRUITER"

    def test_migrate_key_function(self):
        assert migrate_key("HRRECRUITER-42") == "TASKNEIROKLYUCH-42"
        assert migrate_key("HRRECRUITER-1") == "TASKNEIROKLYUCH-1"
        assert migrate_key("AAT-123") is None  # Not legacy
        assert migrate_key("DEV-1") is None


class TestStrictMode:
    def test_raise_on_invalid(self):
        with pytest.raises(TaskKeyValidationError) as exc_info:
            validate("invalid", raise_on_invalid=True)
        assert "Invalid task key" in str(exc_info.value)

    def test_validate_or_die(self):
        with pytest.raises(TaskKeyValidationError):
            validate_or_die("bad-key")

    def test_is_valid_quick(self):
        assert TaskKeyValidator().is_valid("AAT-123")
        assert not TaskKeyValidator().is_valid("bad")


class TestJiraOnlyValidator:
    def test_jira_only_accepts_aat(self):
        v = TaskKeyValidator.jira_only()
        assert v.is_valid("AAT-123")
        assert not v.is_valid("TASKNEIROKLYUCH-42")

    def test_jira_only_no_migration(self):
        v = TaskKeyValidator.jira_only()
        # HRRECRUITER won't match Jira-only pattern
        assert not v.is_valid("HRRECRUITER-7")


class TestLenientValidator:
    def test_lenient_prefixes(self):
        v = TaskKeyValidator.lenient()
        assert v.is_valid("X-1")
        assert v.is_valid("abc-123")


class TestUiFactory:
    def test_from_patterns(self):
        v = TaskKeyValidator.from_patterns([
            r"^(?P<prefix>[A-Z]+)-(?P<number>[0-9]+)$",
        ])
        assert v.is_valid("PROJ-99")

    def test_with_migration_custom(self):
        v = TaskKeyValidator.with_migration({"OLD": "NEW"})
        result = v.validate("OLD-5")
        assert result.was_migrated
        assert result.normalized == "NEW-5"
