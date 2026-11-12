"""Public v3 wire validation, neighboring cases and strict v2 compatibility."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from project_workflow.domain.execution_context import ExecutionContextV3
from project_workflow.domain.resource_context import ExecutionContextV2


def payload():
    tracker = uuid4()
    return {
        "schema_version": 3,
        "operation_id": str(uuid4()),
        "project": {"tracker_instance_id": str(tracker), "project_id": str(uuid4())},
        "task": {"tracker_instance_id": str(tracker), "task_id": str(uuid4())},
        "repositories": [],
    }


def test_explicit_project_does_not_choose_a_wiki_space_or_profession():
    context = ExecutionContextV3.model_validate(payload())
    assert context.space is None
    with pytest.raises(ValueError, match="Explicit Wiki space"):
        context.require_wiki_space()
    body = context.model_dump(mode="json")
    body["space"] = {"registry_instance_id": str(uuid4()), "space_id": str(uuid4())}
    with_space = ExecutionContextV3.model_validate(body)
    assert with_space.project == context.project
    assert with_space.require_wiki_space() == with_space.space
    assert ExecutionContextV3.model_validate_json(with_space.model_dump_json()) == with_space


@pytest.mark.parametrize("version", [2, "3", 3.0, True, None])
def test_version_is_separate_and_never_coerces_legacy_or_non_integer(version):
    body = payload()
    body["schema_version"] = version
    with pytest.raises(ValidationError):
        ExecutionContextV3.model_validate(body)


@pytest.mark.parametrize("part", ["project", "task", "space", "operation_id"])
def test_nil_and_foreign_resource_identities_are_rejected(part):
    body = payload()
    if part == "project":
        body[part]["project_id"] = str(UUID(int=0))
    elif part == "task":
        body[part]["tracker_instance_id"] = str(uuid4())
    elif part == "space":
        body[part] = {"registry_instance_id": str(uuid4()), "space_id": str(UUID(int=0))}
    else:
        body[part] = str(UUID(int=0))
    with pytest.raises(ValidationError):
        ExecutionContextV3.model_validate(body)


def test_repositories_are_bounded_unique_and_immutable_after_validation():
    body = payload()
    repo = {"forge_instance_id": str(uuid4()), "repository_id": str(uuid4())}
    body["repositories"] = [repo, repo]
    with pytest.raises(ValidationError):
        ExecutionContextV3.model_validate(body)
    body["repositories"] = [{"forge_instance_id": str(uuid4()), "repository_id": str(uuid4())} for _ in range(101)]
    with pytest.raises(ValidationError):
        ExecutionContextV3.model_validate(body)
    body["repositories"] = [repo]
    context = ExecutionContextV3.model_validate(body)
    assert isinstance(context.repositories, tuple)
    assert context.model_dump(mode="json")["repositories"] == [repo]


def test_no_implicit_upgrade_from_namespace_only_or_task_only_v2():
    body = payload()
    old = {
        "schema_version": 2,
        "operation_id": body["operation_id"],
        "namespace": {"registry_instance_id": str(uuid4()), "namespace_id": str(uuid4())},
        "task": body["task"],
        "repositories": [],
    }
    assert ExecutionContextV2.model_validate(old).schema_version == 2
    with pytest.raises(ValidationError):
        ExecutionContextV3.model_validate(old)
    with pytest.raises(ValidationError):
        ExecutionContextV2.model_validate(body)
    body["namespace"] = old["namespace"]
    with pytest.raises(ValidationError):
        ExecutionContextV3.model_validate(body)
    body.pop("namespace")
    body.pop("project")
    with pytest.raises(ValidationError):
        ExecutionContextV3.model_validate(body)
