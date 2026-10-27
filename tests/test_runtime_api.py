"""Closed historical packet constructors; execution regressions use configured API tests."""

from __future__ import annotations

import hashlib

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.schemas import RuntimeStepRequest

TEST_RUNTIME_COMPATIBILITY = {
    "catalogVersion": 2,
    "catalogRevision": "a" * 40,
    "catalogSha256": "b" * 64,
    "skillsRevision": "c" * 40,
    "skillsManifestSha256": "d" * 64,
    "capabilityRevision": "hermes-sdlc-runtime/v2",
    "capabilitySha256": "e" * 64,
}


def test_optional_pm_uuid_preserves_ordinary_runtime_command_hash():
    from project_workflow.domain.runtime_assignment import payload_sha256

    legacy = {**_unknown_step_payload("DEV-25"), "report": "durable ordinary report"}
    parsed = RuntimeStepRequest.model_validate(legacy)
    assert payload_sha256(parsed.model_dump(mode="json")) == payload_sha256(legacy)
    assert "session_run_id" not in parsed.model_dump()
    pm_run_id = "11111111-1111-4111-8111-111111111111"
    scoped = RuntimeStepRequest.model_validate({**legacy, "session_run_id": pm_run_id})
    assert scoped.model_dump()["session_run_id"] == pm_run_id


def _namespace(code: str, cli_command: str, prefix: str) -> None:
    role = cli_command.removeprefix("workflow-")
    scope = "delivery" if role == "developer" else "business"
    with SAUnitOfWork() as uow:
        workflow_id = uow.workflows.create(
            {"key": f"hermes-sdlc:{role}", "name": f"Runtime {role}", "active_catalog_version": 2}
        )
        mode_id = uow.workflows.create_mode(
            {
                "workflow_id": workflow_id,
                "key": "assigned",
                "catalog_version": 2,
                "name": "Assigned",
                "mode_order": 2,
                "role_key": role,
                "execution_scope": scope,
                "execution_scopes": [scope],
                "tech_workspace_policy": "required" if scope != "business" else "forbidden",
            }
        )
        uow.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": mode_id,
                "code": "assigned",
                "name": "Assigned",
                "phase_order": 1,
            }
        )
        uow.projects.create(
            {
                "code": code,
                "name": code,
                "workflow_id": workflow_id,
                "cli_command": cli_command,
                "key_prefixes": [prefix],
            }
        )
        uow.commit()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assignment(task: str, operation_key: str, role: str) -> dict[str, object]:
    scope = "delivery" if role == "developer" else "business"
    payload: dict[str, object] = {
        "task": task,
        "runtime_compatibility": dict(TEST_RUNTIME_COMPATIBILITY),
        "workflow_key": f"hermes-sdlc:{role}",
        "role_key": role,
        "mode_key": "assigned",
        "stage_key": role,
        "execution_scope": scope,
        "cycle_number": 0,
        "attempt_number": 1,
        "operation_key": operation_key,
        "business_task_ref": f"business-task:{task}@1",
        "root_task_ref": f"business-task:{task}@1",
        "work_item_ref": f"business-task:{task}@1",
        "work_item_revision": 1,
        "queue_item_ref": f"queue-item:{task}:{role}:0",
        "task_workspace_ref": f"task-workspace:{task}",
        "workspace_revision": 1,
        "decomposition_revision_ref": f"decomposition:{task}@1",
        "stage_revision": f"stage:{role}@1",
        "assignment_ref": f"assignment:{operation_key}",
        "workspace_generation": 1,
        "lease_generation": 1,
        "exact_input_refs": [{"kind": "business_task", "ref": f"business-task:{task}", "revision": "1"}],
        "expected_revision": 0,
        "expected_status": "missing",
    }
    if scope == "delivery":
        payload["tech_execution_workspace_ref"] = f"tech-workspace:{task}"
        payload["tech_execution_attempt_ref"] = f"tech-attempt:{task}"
    return payload


def _bind_payload(
    assignment: dict[str, object],
    *,
    bind_operation_key: str | None = None,
    binding_ref: str | None = None,
    hermes_run_ref: str | None = None,
) -> dict[str, object]:
    operation_key = str(assignment["assignment_operation_key"])
    return {
        "task": assignment["task_key"],
        "bind_operation_key": bind_operation_key or f"bind:{operation_key}",
        "assignment_operation_key": operation_key,
        "assignment_revision": assignment["assignment_revision"],
        "assignment_ref": assignment["assignment_ref"],
        "binding_ref": binding_ref or f"binding:{operation_key}",
        "hermes_run_ref": hermes_run_ref or f"hermes-run:{operation_key}",
        "mode_key": assignment["mode_key"],
        "cycle_number": assignment["cycle_number"],
        "attempt_number": assignment["attempt_number"],
        "expected_binding_state": "unbound",
    }


def _step_payload(
    assignment: dict[str, object],
    report: str | None = None,
    *,
    step_operation_key: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "task": assignment["task_key"],
        "step_operation_key": step_operation_key
        or "step:"
        + hashlib.sha256(
            (f"{assignment['task_key']}:{assignment['assignment_revision']}:{report or 'instructions'}").encode()
        ).hexdigest()[:24],
        "assignment_revision": assignment["assignment_revision"],
        "assignment_ref": assignment["assignment_ref"],
        "binding_ref": assignment["binding_ref"],
        "hermes_run_ref": assignment["hermes_run_ref"],
        "mode_key": assignment["mode_key"],
        "cycle_number": assignment["cycle_number"],
        "attempt_number": assignment["attempt_number"],
        "expected_phase_code": assignment.get("current_phase_code", "assigned"),
        "expected_status": assignment["status"],
    }
    if report is not None:
        payload["report"] = report
    return payload


def _unknown_step_payload(task: str) -> dict[str, object]:
    return {
        "task": task,
        "step_operation_key": f"step:{task}:unknown",
        "assignment_revision": 1,
        "assignment_ref": "assignment:unknown",
        "binding_ref": "binding:unknown",
        "hermes_run_ref": "hermes-run:unknown",
        "mode_key": "assigned",
        "cycle_number": 0,
        "attempt_number": 1,
        "expected_phase_code": "assigned",
        "expected_status": "active",
    }
