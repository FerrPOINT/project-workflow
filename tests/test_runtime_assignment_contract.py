"""Contract tests for Business-owned runtime assignment bindings."""

from __future__ import annotations

import pytest

from project_workflow.application.workflow import WorkflowService
from project_workflow.interfaces.ui.schemas import RuntimeAssignmentRequest
from tests._db_helpers import prepared_sqlite_uow

TEST_RUNTIME_COMPATIBILITY = {
    "catalogVersion": 2,
    "catalogRevision": "a" * 40,
    "catalogSha256": "b" * 64,
    "skillsRevision": "c" * 40,
    "skillsManifestSha256": "d" * 64,
    "capabilityRevision": "hermes-sdlc-runtime/v2",
    "capabilitySha256": "e" * 64,
}


def _binding(**overrides: object) -> dict[str, object]:
    binding: dict[str, object] = {
        "runtime_compatibility": dict(TEST_RUNTIME_COMPATIBILITY),
        "role_key": "developer",
        "workflow_key": "hermes-sdlc:developer",
        "execution_scope": "delivery",
        "stage_key": "development",
        "attempt_number": 1,
        "business_task_ref": "business-task:DEV-1@7",
        "root_task_ref": "business-task:ROOT-1@3",
        "work_item_ref": "business-task:DEV-1@7",
        "work_item_revision": 7,
        "queue_item_ref": "queue-item:DEV-1:development:0",
        "task_workspace_ref": "task-workspace:tw-1",
        "workspace_revision": 2,
        "tech_execution_workspace_ref": "tech-workspace:workspace-1",
        "tech_execution_attempt_ref": "tech-attempt:attempt-1",
        "decomposition_revision_ref": "decomposition:ROOT-1@2",
        "stage_revision": "stage:developer@4",
        "assignment_ref": "assignment:DEV-1@1",
        "workspace_generation": 2,
        "lease_generation": 5,
        "exact_input_refs": [
            {
                "revision": "2",
                "ref": "comment:DEV-1:4",
                "kind": "comment",
                "hash": "b" * 64,
            },
            {
                "kind": "business_task",
                "ref": "business-task:DEV-1",
                "revision": "7",
                "hash": "a" * 64,
            },
        ],
    }
    binding.update(overrides)
    return binding


def _continuation(bound: dict[str, object], **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "task": bound["task_key"],
        "operation_key": "continue:DEV-1:1",
        "expected_assignment_revision": bound["assignment_revision"],
        "expected_assignment_ref": bound["assignment_ref"],
        "expected_binding_ref": bound["binding_ref"],
        "expected_hermes_run_ref": bound["hermes_run_ref"],
        "expected_phase_code": bound["current_phase_code"],
        "expected_status": bound["status"],
        "mode_key": bound["mode_key"],
        "execution_scope": bound["execution_scope"],
        "cycle_number": bound["cycle_number"],
        "attempt_number": bound["attempt_number"],
        "run_sequence": 1,
        "next_assignment_ref": "assignment:DEV-1:continued",
        "next_binding_ref": "binding:continued",
        "next_hermes_run_ref": "run:continued",
        "checkpoint_ref": "receipt:DEV-1:oldrun",
        "checkpoint_revision": "a" * 64,
        "checkpoint_owner_assignment_ref": bound["assignment_ref"],
        "checkpoint_hermes_run_ref": bound["hermes_run_ref"],
        "expected_work_item_revision": bound["work_item_revision"],
        "work_item_revision": bound["work_item_revision"],
        "expected_workspace_revision": bound["workspace_revision"],
        "expected_decomposition_revision_ref": bound["decomposition_revision_ref"],
        "expected_stage_revision": bound["stage_revision"],
        "expected_workspace_generation": bound["workspace_generation"],
        "expected_lease_generation": bound["lease_generation"],
        "exact_input_refs": [
            *bound["exact_input_refs"],
            {
                "kind": "tech-execution-terminal-receipt",
                "ref": "receipt:DEV-1:oldrun",
                "revision": "oldrun",
                "hash": "a" * 64,
            },
        ],
        "workspace_generation": 3,
        "lease_generation": 6,
        "tech_execution_workspace_ref": "workspace:continued",
        "tech_execution_attempt_ref": "attempt:continued",
    }
    values.update(overrides)
    return values


def test_runtime_assignment_requires_complete_business_execution_identity():
    payload = {
        "task": "DEV-1",
        "role_key": "developer",
        "mode_key": "initial",
        "execution_scope": "delivery",
        "cycle_number": 0,
        "operation_key": "assign-dev-1",
        "expected_revision": 0,
        "expected_status": "missing",
        **_binding(),
    }

    parsed = RuntimeAssignmentRequest.model_validate(payload)
    assert parsed.workflow_key == "hermes-sdlc:developer"
    assert parsed.stage_key == "development"
    assert parsed.attempt_number == 1
    assert parsed.work_item_revision == 7
    assert parsed.workspace_revision == 2

    for required_field in (
        "workflow_key",
        "stage_key",
        "attempt_number",
        "work_item_revision",
        "queue_item_ref",
        "workspace_revision",
    ):
        invalid = dict(payload)
        invalid.pop(required_field)
        with pytest.raises(ValueError):
            RuntimeAssignmentRequest.model_validate(invalid)


def test_catalog_and_assignment_share_strict_runtime_role_keys(tmp_path):
    with prepared_sqlite_uow(tmp_path, "role-keys.db") as uow:
        workflow_id = uow.workflows.create({"name": "Roles"})
        with pytest.raises(ValueError, match="role_key"):
            WorkflowService(uow).create_mode(
                workflow_id,
                {
                    "key": "invalid",
                    "name": "Invalid",
                    "role_key": "developer.v2",
                    "execution_scope": "delivery",
                    "tech_workspace_policy": "required",
                },
            )
