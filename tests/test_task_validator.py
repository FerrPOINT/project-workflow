"""Tests for database-backed task-key validation."""

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.domain.validation import TaskKeyValidator, ValidatedTaskKey


def _validator(*prefixes: str) -> TaskKeyValidator:
    return TaskKeyValidator.from_projects([{"code": "project", "key_prefixes": list(prefixes)}])


class TestTaskKeyValidator:
    def test_matches_configured_project(self):
        result = _validator("TASK").validate("TASK-42")
        assert result.is_valid
        assert result.project == "project"
        assert result.prefix == "TASK"
        assert result.issue_number == "42"
        assert result.normalized == "TASK-42"

    @pytest.mark.parametrize("key", ["task-1", "TASK", "TASK 1", "OTHER-1", "", "123"])
    def test_rejects_invalid_or_unconfigured_keys(self, key: str):
        assert not _validator("TASK").validate(key).is_valid

    def test_empty_project_catalog_fails_closed(self):
        result = TaskKeyValidator.from_projects([]).validate("TASK-1")
        assert not result.is_valid
        assert "no configured prefixes" in (result.error_message or "")

    def test_reads_json_prefixes_from_database_rows(self):
        validator = TaskKeyValidator.from_projects([{"code": "project", "key_prefixes": '["TASK", "DEMO"]'}])
        assert validator.validate("TASK-1").is_valid
        assert validator.validate("DEMO-2").is_valid

    def test_invalid_json_prefixes_fail_closed(self):
        validator = TaskKeyValidator.from_projects([{"code": "project", "key_prefixes": "TASK"}])
        assert not validator.validate("TASK-1").is_valid

    def test_validated_key_string_uses_normalized_value(self):
        value = ValidatedTaskKey(raw="raw", is_valid=True, normalized="TASK-1")
        assert str(value) == "TASK-1"
