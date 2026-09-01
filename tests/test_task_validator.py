"""Tests for database-backed task-key validation."""

import pytest

pytestmark = [pytest.mark.unit]

from project_workflow.domain.validation import TaskKeyValidator, ValidatedTaskKey


def _validator(*prefixes: str) -> TaskKeyValidator:
    return TaskKeyValidator.from_projects([{"code": "project", "key_prefixes": list(prefixes)}])


class TestTaskKeyValidator:
    def test_matches_configured_project_metadata_when_present(self):
        result = _validator("RUN").validate("RUN-42")
        assert result.is_valid
        assert result.project == "project"
        assert result.prefix == "RUN"
        assert result.issue_number == "42"
        assert result.normalized == "RUN-42"

    @pytest.mark.parametrize("key", ["task-1", "TASK", "TASK 1", "", "123"])
    def test_rejects_invalid_key_shapes(self, key: str):
        assert not _validator("TASK").validate(key).is_valid

    def test_empty_project_catalog_still_validates_key_shape(self):
        result = TaskKeyValidator.from_projects([]).validate("RUN-1")
        assert result.is_valid
        assert result.project is None
        assert result.normalized == "RUN-1"

    @pytest.mark.parametrize("key", ["RUN", "RUN-BROWSER", "RUN-12X"])
    def test_reports_numeric_suffix_contract(self, key: str):
        result = _validator("RUN").validate(key)
        assert not result.is_valid
        assert "<номер задачи>" in (result.error_message or "")

    def test_unknown_prefix_is_not_a_routing_error(self):
        result = _validator("RUN").validate("OTHER-1")
        assert result.is_valid
        assert result.project is None
        assert result.normalized == "OTHER-1"

    def test_digits_only_reports_missing_prefix(self):
        result = _validator("RUN").validate("123")

        assert not result.is_valid
        assert "Только номер без префикса недопустим" in (result.error_message or "")

    @pytest.mark.parametrize("raw_prefixes", ['["RUN", "DEMO"]', "RUN", ["RUN", 1]])
    def test_rejects_noncanonical_project_prefix_shapes(self, raw_prefixes):
        with pytest.raises(ValueError, match="массивом строк"):
            TaskKeyValidator.from_projects([{"code": "project", "key_prefixes": raw_prefixes}])

    @pytest.mark.parametrize("project_code", [None, "", "   ", 7])
    def test_rejects_noncanonical_project_codes(self, project_code):
        with pytest.raises(ValueError, match="code должен быть непустой строкой"):
            TaskKeyValidator.from_projects([{"code": project_code, "key_prefixes": ["RUN"]}])

    def test_validated_key_string_uses_normalized_value(self):
        value = ValidatedTaskKey(raw="raw", is_valid=True, normalized="RUN-1")
        assert str(value) == "RUN-1"
