"""Tests for task_validator with prefix-based validation."""

import pytest

from project_workflow.domain.validation import (
    TaskKeyValidator,
    TaskKeyValidationError,
    validate,
    validate_or_die,
)


class TestValidationBasics:
    def test_valid_jira(self):
        result = validate("AAT-123")
        assert result.is_valid
        assert result.project == "AAT"
        assert result.issue_number == "123"
        assert result.normalized == "AAT-123"

    def test_valid_internal(self):
        result = validate("TASK-42")
        assert result.is_valid
        assert result.project == "TASK"
        assert result.normalized == "TASK-42"

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


class TestStrictMode:
    def test_raise_on_invalid(self):
        with pytest.raises(TaskKeyValidationError) as exc_info:
            validate("invalid", raise_on_invalid=True)
        assert "Invalid task key" in str(exc_info.value)

    def test_validate_or_die(self):
        with pytest.raises(TaskKeyValidationError):
            validate_or_die("bad-key")

    def test_is_valid_quick(self):
        assert TaskKeyValidator().is_valid("TASK-123")
        assert not TaskKeyValidator().is_valid("bad")


class TestJiraOnlyValidator:
    def test_jira_only_accepts_aat(self):
        v = TaskKeyValidator.jira_only()
        assert v.is_valid("AAT-123")
        assert not v.is_valid("UNKNOWN-1")

    def test_jira_only_rejects_internal(self):
        v = TaskKeyValidator.jira_only()
        result = v.validate("TASK-1")
        assert not result.is_valid


class TestLenientValidator:
    def test_lenient_prefixes(self):
        v = TaskKeyValidator.lenient()
        assert v.is_valid("X-1")
        assert v.is_valid("abc-123")


class TestUiFactory:
    def test_from_prefixes(self):
        v = TaskKeyValidator.from_prefixes(["PROJ"])
        assert v.is_valid("PROJ-99")
        assert not v.is_valid("OTHER-1")


class TestProjectScopedFactory:
    def test_from_projects_matches_specific_project(self):
        v = TaskKeyValidator.from_projects(
            [
                {
                    "code": "AAT",
                    "name": "AAT",
                    "key_prefixes": ["AAT"],
                }
            ]
        )
        result = v.validate("AAT-42")
        assert result.is_valid
        assert result.project == "AAT"
        assert result.prefix == "AAT"
        assert result.normalized == "AAT-42"

    def test_from_projects_ignores_unknown_keys(self):
        v = TaskKeyValidator.from_projects(
            [
                {
                    "code": "AAT",
                    "name": "AAT",
                    "key_prefixes": ["AAT"],
                }
            ]
        )
        assert not v.validate("OTHER-7").is_valid
