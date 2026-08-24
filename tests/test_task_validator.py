"""Tests for database-backed task-key validation."""

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.domain.validation import TaskKeyValidator, ValidatedTaskKey


def _validator(*prefixes: str) -> TaskKeyValidator:
    return TaskKeyValidator.from_projects([{"code": "project", "key_prefixes": list(prefixes)}])


class TestTaskKeyValidator:
    def test_matches_configured_project(self):
        result = _validator("RUN").validate("RUN-42")
        assert result.is_valid
        assert result.project == "project"
        assert result.prefix == "RUN"
        assert result.issue_number == "42"
        assert result.normalized == "RUN-42"

    @pytest.mark.parametrize("key", ["task-1", "TASK", "TASK 1", "OTHER-1", "", "123"])
    def test_rejects_invalid_or_unconfigured_keys(self, key: str):
        assert not _validator("TASK").validate(key).is_valid

    def test_empty_project_catalog_fails_closed(self):
        result = TaskKeyValidator.from_projects([]).validate("RUN-1")
        assert not result.is_valid
        assert "no configured prefixes" in (result.error_message or "")

    @pytest.mark.parametrize("key", ["RUN", "RUN-BROWSER", "RUN-12X"])
    def test_known_prefix_reports_numeric_suffix_contract(self, key: str):
        result = _validator("RUN").validate(key)
        assert not result.is_valid
        assert "RUN-<numeric issue number>" in (result.error_message or "")

    def test_unknown_prefix_reports_allowed_prefixes(self):
        result = _validator("RUN").validate("OTHER-1")
        assert not result.is_valid
        assert "Prefixes: RUN" in (result.error_message or "")

    @pytest.mark.parametrize("raw_prefixes", ['["RUN", "DEMO"]', "RUN", ["RUN", 1]])
    def test_rejects_noncanonical_project_prefix_shapes(self, raw_prefixes):
        with pytest.raises(ValueError, match="list of strings"):
            TaskKeyValidator.from_projects([{"code": "project", "key_prefixes": raw_prefixes}])

    def test_validated_key_string_uses_normalized_value(self):
        value = ValidatedTaskKey(raw="raw", is_valid=True, normalized="RUN-1")
        assert str(value) == "RUN-1"
