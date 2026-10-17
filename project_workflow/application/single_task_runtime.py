"""Installed binding integrity on the existing bridge, without remote runtime probes."""

import hashlib
import hmac
import json
from typing import Any

from sqlalchemy import select

from project_workflow import config
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.domain.single_task_runtime import SingleTaskContext
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import observe_installation
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def installed_context(uow: Any, project_id: int, context: dict[str, Any]) -> dict[str, Any]:
    parsed = SingleTaskContext.model_validate(context).model_dump(mode="json")
    binding = next((b for b in observe_installation(uow).bindings if int(b.namespace_id) == project_id), None)
    if binding is None or binding.instruction_manifest_sha256 != parsed["instruction_manifest_sha256"]:
        raise ConflictError("Single-task installed manifest/namespace mismatch")
    return parsed


def current_binding(uow: SAUnitOfWork, record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload", {})
    context = installed_context(uow, record["project_id"], payload.get("single_task_context", {}))
    binding = record.get("single_task_binding")
    if not isinstance(binding, dict) or record.get("payload_sha256") != payload_sha256(payload):
        raise ConflictError("Single-task immutable assignment/binding integrity mismatch")
    request = binding.get("request", {})
    if (
        binding.get("context") != context or binding.get("assignment_sha256") != record["payload_sha256"]
        or binding.get("task_ref") != record["business_task_ref"]
        or binding.get("root_ref") != record["root_task_ref"]
        or record["business_task_ref"] != record["root_task_ref"]
        or any(record.get(k) != payload.get(k) for k in (
            "project_id", "workflow_id", "workflow_key", "mode_key", "role_key", "execution_scope", "stage_key",
            "business_task_ref", "root_task_ref", "assignment_ref", "cycle_number", "attempt_number",
            "operation_key", "work_item_ref", "work_item_revision", "queue_item_ref", "task_workspace_ref",
            "workspace_revision", "workspace_generation", "decomposition_revision_ref", "stage_revision",
            "lease_generation", "tech_execution_workspace_ref", "tech_execution_attempt_ref", "exact_input_refs",
        ))
        or request.get("assignment_operation_key") != record.get("operation_key")
        or record.get("concrete_agent_ref") != context["concrete_agent_ref"]
        or payload_sha256(request) != record.get("bind_request_sha256")
        or any(request.get(k) != record.get(k) for k in (
            "binding_ref", "hermes_run_ref", "assignment_ref", "assignment_revision", "role_key",
            "cycle_number", "attempt_number", "mode_key", "concrete_agent_ref", "bind_operation_key",
        ))
    ):
        raise ConflictError("Single-task saved binding differs from assignment")
    effective = dict(binding)
    execution = uow.session.scalar(select(m.PMExecution).where(m.PMExecution.assignment_id == record["id"]))
    if execution is not None:
        run = uow.session.get(m.PMRun, execution.session_run_id)
        if run is None or run.execution_ref != context["execution_ref"]:
            raise ConflictError("Single-task PM run binding mismatch")
        effective["pm_run"] = {"session_run_id": run.session_run_id, "binding_ref": run.binding_ref,
                               "hermes_run_ref": run.run_ref, "fence": execution.fence}
    return effective


def context_hash(uow: SAUnitOfWork, record: dict[str, Any]) -> str:
    return payload_sha256(current_binding(uow, record))


def execution_token(context_sha256: str) -> str:
    settings = config.get_settings()
    secret = settings.PROJECT_WORKFLOW_PM_SCOPE_SECRET
    shared = {settings.PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN, settings.PROJECT_WORKFLOW_PM_READBACK_TOKEN}
    for raw in (settings.PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON, settings.PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON):
        shared.update(json.loads(raw or "{}").values())
    if len(secret) < 32 or secret in shared:
        raise ConflictError("Existing bridge execution scope secret unavailable")
    return hmac.new(secret.encode(), ("single-task-v1:" + context_sha256).encode(), hashlib.sha256).hexdigest()


def authorize(
    uow: SAUnitOfWork, record: dict[str, Any], *, token: str | None, session_run_id: str | None,
    instruction_profile: str | None, instruction_manifest_sha256: str | None, declared_hash: str | None = None,
) -> str:
    binding = current_binding(uow, record)
    request = binding["request"]
    run = binding.get("pm_run", request)
    digest = payload_sha256(binding)
    if (instruction_profile != "single-task-v1"
        or instruction_manifest_sha256 != binding["context"]["instruction_manifest_sha256"]
        or session_run_id != run["session_run_id"] or declared_hash is not None and declared_hash != digest):
        raise ConflictError("Single-task current profile/session/integrity fence mismatch")
    # Enrolled PM uses the same PM scoped token and run ledger as legacy PM.
    expected = execution_token(digest)
    if "pm_run" in binding:
        from project_workflow.application.pm_execution import PMExecutionService

        execution = uow.session.scalar(select(m.PMExecution).where(m.PMExecution.assignment_id == record["id"]))
        if execution is None:
            raise ConflictError("Single-task PM execution missing")
        expected = PMExecutionService.scoped_token(PMExecutionService(uow).snapshot(execution),
                                                 config.get_settings().PROJECT_WORKFLOW_PM_SCOPE_SECRET)
    if not isinstance(token, str) or not hmac.compare_digest(token.encode(), expected.encode()):
        raise PermissionError("Current execution/run scoped credential required")
    return digest
