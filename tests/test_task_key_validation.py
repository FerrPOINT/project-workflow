"""Task keys are accepted only through configured project prefixes."""

from unittest.mock import MagicMock

import pytest

from project_workflow.domain.validation import (
    TaskKeyValidationError,
    TaskKeyValidator,
    ValidatedTaskKey,
    get_project_for_task_key,
)

pytestmark = [pytest.mark.unit]


def test_configured_prefix_is_normalized_and_mapped():
    validator = TaskKeyValidator.from_projects([{"code": "REL", "key_prefixes": ["REL"]}])
    result = validator.validate("REL-360")
    assert result.is_valid
    assert result.project == "REL"
    assert result.normalized == "REL-360"


@pytest.mark.parametrize("key", ["rel-360", "REL", "REL_360", "REL-ABC", "OTHER-1"])
def test_unconfigured_or_malformed_key_is_rejected(key):
    validator = TaskKeyValidator.from_prefixes(["REL"])
    assert not validator.validate(key).is_valid


def test_empty_configuration_is_fail_closed():
    assert not TaskKeyValidator().validate("REL-360").is_valid


def test_raise_on_invalid():
    with pytest.raises(TaskKeyValidationError):
        TaskKeyValidator.from_prefixes(["REL"]).validate_or_die("OTHER-1")


def test_invalid_project_prefix_storage_is_rejected():
    with pytest.raises(ValueError, match="must be a list"):
        TaskKeyValidator.from_projects([{"code": "REL", "key_prefixes": '["REL"]'}])


def test_duplicate_prefix_mapping_is_rejected():
    with pytest.raises(ValueError, match="multiple projects"):
        TaskKeyValidator.from_projects(
            [
                {"code": "ONE", "key_prefixes": ["REL"]},
                {"code": "TWO", "key_prefixes": ["REL"]},
            ]
        )


def test_project_resolution_uses_configured_mapping():
    project = {"id": 7, "code": "REL", "key_prefixes": ["REL"]}
    row = MagicMock()
    row.to_dict.return_value = project
    uow = MagicMock()
    uow.projects.list.return_value = [row]
    assert get_project_for_task_key(uow, "REL-360") == project
    assert get_project_for_task_key(uow, "OTHER-1") is None


def test_validated_key_string_uses_normalized_value():
    assert str(ValidatedTaskKey(raw="raw", is_valid=True, normalized="REL-1")) == "REL-1"
