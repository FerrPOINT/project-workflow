"""Read-only retained PM execution and receipt decoding; no native commands."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from sqlalchemy import select

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.pm_execution import (
    PMIdentity,
    PMReviewAdmissionContext,
)
from project_workflow.domain.runtime_assignment import (
    RuntimeStepFence,
    canonical_json,
    payload_sha256,
    validate_concrete_agent_ref,
)
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork


class PMExecutionService:
    def __init__(self, uow: SAUnitOfWork):
        self.uow = uow
        self.session = uow.session

    def concrete_agent_ref(self, assignment: m.TaskRuntimeAssignment) -> str:
        try:
            agent_ref = validate_concrete_agent_ref(assignment.concrete_agent_ref)
        except ValueError as exc:
            raise ConflictError("PM assignment has no canonical concrete Fleet agent mapping") from exc
        if (
            not assignment.binding_ref or not assignment.hermes_run_ref
            or not assignment.bind_operation_key or not assignment.bind_request_sha256
        ):
            raise ConflictError("PM concrete agent mapping requires a finalized runtime binding")
        if json.loads(assignment.payload).get("single_task_context") is not None:
            from project_workflow.application.single_task_runtime import current_binding

            record = self.uow.tasks.get_assignment_by_operation_key(assignment.operation_key)
            if record is None:
                raise ConflictError("Single-task PM assignment missing")
            current_binding(self.uow, record.to_dict())
            return agent_ref
        task = self.session.get(m.Task, assignment.task_id)
        if task is None:
            raise ConflictError("PM mapping no longer belongs to a task")
        request = {
            "project_id": assignment.project_id, "task_key": task.task_key,
            **{key: getattr(assignment, key) for key in (
                "role_key", "bind_operation_key", "assignment_revision", "assignment_ref",
                "binding_ref", "hermes_run_ref", "cycle_number", "attempt_number", "concrete_agent_ref",
            )},
            "assignment_operation_key": assignment.operation_key, "mode_key": assignment.mode.key,
        }
        # Legacy adoption and first binding are the two authorized CAS origins.
        if assignment.bind_request_sha256 not in {
            payload_sha256({**request, "expected_binding_state": state})
            for state in ("unbound", "legacy_bound")
        }:
            raise ConflictError("PM concrete mapping does not match persisted bind provenance")
        return agent_ref

    def _lock_identity(self, identity: PMIdentity, project_id: int) -> tuple[m.Task, m.TaskRuntimeAssignment]:
        task = self.session.execute(
            select(m.Task).where(m.Task.project_id == project_id, m.Task.task_key == identity.task)
            .with_for_update().execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if task is None:
            raise NotFoundError("PM task not found in authorized namespace")
        assignment = self.session.execute(select(m.TaskRuntimeAssignment).where(
            m.TaskRuntimeAssignment.operation_key == task.assignment_operation_key,
            m.TaskRuntimeAssignment.task_id == task.id,
        ).execution_options(populate_existing=True)).scalar_one_or_none()
        if assignment is None:
            raise ConflictError("Stale or foreign PM assignment identity")
        payload = json.loads(assignment.payload)
        if (assignment.payload_sha256 != payload_sha256(payload)
            or payload.get("task_key") != task.task_key
            or payload.get("mode_key") != assignment.mode.key
            or any(payload.get(key) != getattr(assignment, key) for key in (
                "project_id", "workflow_id", "mode_id", "workflow_key", "role_key", "execution_scope",
                "stage_key", "operation_key", "assignment_ref", "business_task_ref", "root_task_ref",
                "cycle_number", "attempt_number",
            ))):
            raise ConflictError("Retained PM assignment hash or custody differs from its payload")
        review = None
        if "pm_review_context" in payload:
            try:
                review = PMReviewAdmissionContext.model_validate(payload["pm_review_context"])
            except ValueError as exc:
                raise ConflictError("Malformed saved PM review authority") from exc
            if (payload.get("single_task_context") is None or assignment.mode.key != "draft"
                or assignment.stage_key != "Draft" or assignment.execution_scope != "business"
                or assignment.operation_key != f"pm-draft:{assignment.assignment_ref}"
                or payload.get("pm_draft_context") is not None):
                raise ConflictError("Saved PM review differs from single-task Draft admission")
        authority_revision = (
            review.tracker_assignment_revision if review is not None else assignment.assignment_revision
        )
        authority_operation_key = assignment.operation_key
        if payload.get("pm_bootstrap_context") is not None:
            from project_workflow.application.pm_bootstrap import canonical_assignment

            if review is not None or payload.get("single_task_context") is None:
                raise ConflictError("Bootstrap mapping is only for initial single-task PM")
            record = self.uow.tasks.get_assignment_by_operation_key(assignment.operation_key)
            if record is None:
                raise ConflictError("Bootstrap assignment is missing")
            authority_operation_key, authority_revision = canonical_assignment(self.uow, record.to_dict())
        if (
            authority_operation_key != identity.assignment_operation_key
            or task.assignment_revision != assignment.assignment_revision
            or authority_revision != identity.assignment_revision
            or assignment.assignment_ref != identity.assignment_ref
            or assignment.role_key != "project_manager" or assignment.mode.role_key != assignment.role_key
            or assignment.business_task_ref != identity.task_ref
            or assignment.root_task_ref != identity.root_ref
            or assignment.mode_id != task.mode_id
            or assignment.cycle_number != task.cycle_number
        ):
            raise ConflictError("Stale or foreign PM assignment identity")
        single_context = json.loads(assignment.payload).get("single_task_context")
        if single_context is not None:
            from project_workflow.application.single_task_runtime import retained_context

            context = retained_context(single_context)
            if (identity.task_ref != identity.root_ref
                or any(context[k] != getattr(identity, k) for k in (
                    "execution_ref", "tracker_instance_ref", "tracker_project_ref",
                ))):
                raise ConflictError("Single-task PM differs from assignment identity")
        else:
            from project_workflow.build_provenance import BuildProvenanceError, validate_runtime_compatibility

            try:
                saved_descriptor = validate_runtime_compatibility(payload.get("runtime_compatibility"))
            except BuildProvenanceError:
                raise ConflictError("Retained PM assignment descriptor is invalid") from None
            if assignment.mode.catalog_version != 2 or saved_descriptor["catalogVersion"] != 2:
                raise ConflictError("Retained PM assignment catalog family is unsupported")
        draft_context = json.loads(assignment.payload).get("pm_draft_context")
        if draft_context is not None and {
            key: draft_context.get(key) for key in PMIdentity.model_fields
        } != identity.model_dump():
            raise ConflictError("PM execution differs from its original Draft reservation")
        if self.concrete_agent_ref(assignment) != identity.agent_ref:
            raise ConflictError("PM identity does not match the persisted concrete Fleet agent")
        return task, assignment

    def execution(self, identity: PMIdentity, project_id: int) -> tuple[m.PMExecution, m.Task]:
        task, assignment = self._lock_identity(identity, project_id)
        execution = self.session.execute(select(m.PMExecution).where(
            m.PMExecution.execution_ref == identity.execution_ref,
            m.PMExecution.task_id == task.id,
        ).execution_options(populate_existing=True)).scalar_one_or_none()
        if execution is None:
            raise NotFoundError("PM execution not found")
        if (
            execution.identity_json != canonical_json(identity.model_dump())
            or execution.assignment_id != assignment.id or execution.agent_ref != identity.agent_ref
        ):
            raise ConflictError("Execution identity is immutable")
        return execution, task

    def run(self, execution: m.PMExecution) -> m.PMRun:
        run = self.session.get(m.PMRun, execution.session_run_id, populate_existing=True)
        if run is None or run.execution_ref != execution.execution_ref:
            raise ConflictError("Execution run binding is incomplete")
        return run



    @staticmethod
    def identity(command: PMIdentity) -> PMIdentity:
        return PMIdentity.model_validate(command.model_dump(include=set(PMIdentity.model_fields)))


    def snapshot(self, execution: m.PMExecution) -> dict[str, Any]:
        task = self.session.get(m.Task, execution.task_id)
        if task is None:
            raise ConflictError("PM task no longer exists")
        self.execution(PMIdentity.model_validate_json(execution.identity_json), task.project_id)
        run = self.run(execution)
        checkpoint = json.loads(execution.checkpoint_json) if execution.checkpoint_json else None
        resume_input = checkpoint.pop("resume_input", None) if checkpoint else None
        snapshot = {
            "contract_version": 1, "identity": json.loads(execution.identity_json),
            "state": execution.state, "version": execution.version, "fence": execution.fence,
            "binding_ref": run.binding_ref, "hermes_run_ref": run.run_ref,
            "session_run_id": run.session_run_id,
            "checkpoint": checkpoint,
            "resume_operation_key": execution.resume_operation_key,
            "resume_session_run_id": execution.resume_session_run_id,
            "terminal_readback": json.loads(run.terminal_json) if run.terminal_json else None,
            "workflow_step_allowed": False,
            "resume_delivered": execution.state == "active" and execution.resume_operation_key is not None,
        }
        assignment = self.session.get(m.TaskRuntimeAssignment, execution.assignment_id)
        context = json.loads(assignment.payload).get("single_task_context") if assignment else None
        if context is not None and assignment is not None:
            from project_workflow.application.single_task_runtime import context_hash

            record = self.uow.tasks.get_assignment_by_operation_key(assignment.operation_key)
            if record is None:
                raise ConflictError("Single-task PM assignment missing")
            snapshot.update({"instruction_profile": context["instruction_profile"],
                             "instruction_manifest_sha256": context["instruction_manifest_sha256"],
                             "single_task_context_sha256": context_hash(self.uow, record.to_dict())})
            if resume_input is not None:
                snapshot["resume_input"] = resume_input
        return snapshot










    def readback(self, identity: PMIdentity, project_id: int, operation_key: str | None) -> dict[str, Any]:
        execution, _ = self.execution(identity, project_id)
        result = self.snapshot(execution)
        result["operation"] = None
        if operation_key is not None:
            operation = self.session.get(m.PMOperation, operation_key)
            if operation is not None:
                if operation.execution_ref != execution.execution_ref:
                    raise ConflictError("Foreign command key")
                result["operation"] = {
                    "operation_key": operation_key, "kind": operation.kind,
                    "request_sha256": operation.request_sha256, "result": json.loads(operation.result_json),
                }
        return result

    @staticmethod
    def scoped_token(snapshot: dict[str, Any], secret: str) -> str:
        scope = {key: snapshot[key] for key in (
            "identity", "session_run_id", "hermes_run_ref", "binding_ref", "fence",
        )}
        return hmac.new(secret.encode(), ("pm-v1:" + canonical_json(scope)).encode(), hashlib.sha256).hexdigest()

    def supervisor_binding(self, task_id: int, fence: RuntimeStepFence | None = None) -> m.PMExecution | None:
        execution = self.session.scalar(select(m.PMExecution).where(
            m.PMExecution.task_id == task_id,
        ).execution_options(populate_existing=True))
        if execution is not None:
            task = self.session.get(m.Task, task_id, populate_existing=True)
            assignment = self.session.get(m.TaskRuntimeAssignment, execution.assignment_id)
            if (
                execution.state != "active" or task is None or assignment is None
                or task.assignment_revision != assignment.assignment_revision
                or task.assignment_operation_key != assignment.operation_key
            ):
                raise ConflictError("PM execution is waiting, pending or assigned elsewhere")
            self.execution(PMIdentity.model_validate_json(execution.identity_json), task.project_id)
            if fence is not None:
                run = self.run(execution)
                if (
                    fence.pm_version != execution.version or fence.pm_fence != execution.fence
                    or fence.hermes_run_ref != run.run_ref or fence.binding_ref != run.binding_ref
                ):
                    raise ConflictError("Supervisor step belongs to a stale PM execution/run")
        else:
            task = self.session.get(m.Task, task_id, populate_existing=True)
            if task is not None and task.assignment_operation_key is not None:
                assignment = self.session.scalar(select(m.TaskRuntimeAssignment).where(
                    m.TaskRuntimeAssignment.operation_key == task.assignment_operation_key,
                    m.TaskRuntimeAssignment.task_id == task.id,
                ).execution_options(populate_existing=True))
                if assignment is not None and assignment.role_key == "project_manager":
                    if json.loads(assignment.payload).get("single_task_context") is not None:
                        raise ConflictError("Single-task PM requires existing PM execution enrollment")
                    if json.loads(assignment.payload).get("pm_draft_context") is not None:
                        raise ConflictError("PM Draft requires verified execution enrollment before a step")
                    self.concrete_agent_ref(assignment)
        return execution
