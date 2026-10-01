"""PM continuation ledger sharing the existing task lock and Supervisor cursor."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from sqlalchemy import select

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.pm_execution import (
    PMBind,
    PMCheckpoint,
    PMCommand,
    PMIdentity,
    PMRebind,
    PMResume,
    RuntimeObservation,
)
from project_workflow.domain.runtime_assignment import (
    RuntimeStepFence,
    canonical_json,
    payload_sha256,
    validate_concrete_agent_ref,
)
from project_workflow.infrastructure import pm_readback
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
            m.TaskRuntimeAssignment.operation_key == identity.assignment_operation_key,
            m.TaskRuntimeAssignment.task_id == task.id,
        ).execution_options(populate_existing=True)).scalar_one_or_none()
        if assignment is None or (
            task.assignment_operation_key != identity.assignment_operation_key
            or task.assignment_revision != identity.assignment_revision
            or assignment.assignment_revision != identity.assignment_revision
            or assignment.assignment_ref != identity.assignment_ref
            or assignment.role_key != "project_manager"
            or assignment.business_task_ref != identity.task_ref
            or assignment.root_task_ref != identity.root_ref
            or assignment.mode_id != task.mode_id
            or assignment.cycle_number != task.cycle_number
        ):
            raise ConflictError("Stale or foreign PM assignment identity")
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

    def _replay(self, command: PMBind | PMCommand, kind: str) -> dict[str, Any] | None:
        operation = self.session.get(m.PMOperation, command.operation_key)
        if operation is None:
            return None
        if (
            operation.execution_ref != command.execution_ref or operation.kind != kind
            or operation.request_sha256 != payload_sha256(command.model_dump())
        ):
            raise ConflictError("Idempotency key was used with another command or payload")
        return json.loads(operation.result_json)

    def snapshot(self, execution: m.PMExecution) -> dict[str, Any]:
        task = self.session.get(m.Task, execution.task_id)
        if task is None:
            raise ConflictError("PM task no longer exists")
        self.execution(PMIdentity.model_validate_json(execution.identity_json), task.project_id)
        run = self.run(execution)
        return {
            "contract_version": 1, "identity": json.loads(execution.identity_json),
            "state": execution.state, "version": execution.version, "fence": execution.fence,
            "binding_ref": run.binding_ref, "hermes_run_ref": run.run_ref,
            "session_run_id": run.session_run_id,
            "checkpoint": json.loads(execution.checkpoint_json) if execution.checkpoint_json else None,
            "resume_operation_key": execution.resume_operation_key,
            "resume_session_run_id": execution.resume_session_run_id,
            "terminal_readback": json.loads(run.terminal_json) if run.terminal_json else None,
            "workflow_step_allowed": (
                execution.state == "active" and task.status in {"active", "blocked"}
            ),
            "resume_delivered": execution.state == "active" and execution.resume_operation_key is not None,
        }

    def _record(self, command: PMBind | PMCommand, kind: str, execution: m.PMExecution) -> dict[str, Any]:
        self.session.flush()
        result = self.snapshot(execution)
        self.session.add(m.PMOperation(
            operation_key=command.operation_key, execution_ref=execution.execution_ref, kind=kind,
            request_sha256=payload_sha256(command.model_dump()), result_json=canonical_json(result),
        ))
        self.session.flush()
        return result

    @staticmethod
    def _proof(
        identity: PMIdentity, run_ref: str, binding_ref: str, fence: int,
        dispatch_key: str, checkpoint_ref: str | None, session_run_id: str,
    ) -> RuntimeObservation:
        proof = pm_readback.observe_run(session_run_id)
        if (
            PMExecutionService.identity(proof) != identity or proof.hermes_run_ref != run_ref
            or proof.binding_ref != binding_ref or proof.fence != fence
            or proof.dispatch_operation_key != dispatch_key or proof.checkpoint_ref != checkpoint_ref
            or proof.session_run_id != session_run_id
        ):
            raise ConflictError("Trusted runtime readback does not match the scoped execution/run")
        return proof

    def bind(self, command: PMBind, project_id: int) -> dict[str, Any]:
        identity = self.identity(command)
        task, assignment = self._lock_identity(identity, project_id)
        replay = self._replay(command, "bind")
        if replay is not None:
            return replay
        if self.session.get(m.PMExecution, command.execution_ref) is not None:
            raise ConflictError("Execution already bound; use command readback")
        phase = self.session.get(m.Phase, task.current_phase_id)
        agent = self.session.get(m.Agent, phase.agent_id) if phase and phase.agent_id else None
        if (
            agent is None or agent.name != assignment.role_key or task.status != "active"
            or assignment.binding_ref != command.binding_ref or assignment.hermes_run_ref != command.hermes_run_ref
            or not assignment.bind_operation_key or not assignment.bind_request_sha256
        ):
            raise ConflictError("PM bind requires the current concrete agent and finalized runtime binding")
        proof = self._proof(
            identity, command.hermes_run_ref, command.binding_ref, 1, command.operation_key, None,
            command.session_run_id,
        )
        if proof.status != "running":
            raise ConflictError("Initial PM run is not running")
        execution = m.PMExecution(
            execution_ref=command.execution_ref, task_id=task.id, assignment_id=assignment.id,
            agent_id=agent.id, tracker_instance_ref=identity.tracker_instance_ref,
            tracker_project_ref=identity.tracker_project_ref, task_ref=identity.task_ref,
            root_ref=identity.root_ref, agent_ref=identity.agent_ref,
            identity_json=canonical_json(identity.model_dump()),
            state="active", version=1, fence=1, session_run_id=command.session_run_id, phase_id=task.current_phase_id,
        )
        self.session.add(execution)
        self.session.flush()
        self.session.add(m.PMRun(
            session_run_id=command.session_run_id, run_ref=command.hermes_run_ref,
            execution_ref=command.execution_ref, binding_ref=command.binding_ref,
            fence=1, observation_json=proof.model_dump_json(),
        ))
        return self._record(command, "bind", execution)

    def _validate(self, command: PMCommand, execution: m.PMExecution, task: m.Task, state: str) -> m.PMRun:
        run = self.run(execution)
        if (
            execution.version != command.expected_version or execution.fence != command.expected_fence
            or execution.state != state or run.run_ref != command.hermes_run_ref
            or run.binding_ref != command.binding_ref or task.status not in {"active", "blocked"}
            or run.session_run_id != command.session_run_id
            or (state != "active" and execution.phase_id != task.current_phase_id)
        ):
            raise ConflictError("Stale execution version, fence, checkpoint cursor or run")
        return run

    def checkpoint(self, command: PMCheckpoint, project_id: int) -> dict[str, Any]:
        execution, task = self.execution(self.identity(command), project_id)
        replay = self._replay(command, "checkpoint")
        if replay is not None:
            return replay
        self._validate(command, execution, task, "active")
        phase = self.session.get(m.Phase, task.current_phase_id)
        if phase is None or phase.agent_id != execution.agent_id:
            raise ConflictError("Checkpoint no longer belongs to the bound catalog agent")
        checkpoint = command.model_dump(include={
            "checkpoint_ref", "clarification_request_ref", "clarification_version", "requirements_revision",
        })
        # Checkpoint references cannot be reused for a later clarification wait.
        for stored in self.session.scalars(select(m.PMOperation).where(
            m.PMOperation.execution_ref == execution.execution_ref, m.PMOperation.kind == "checkpoint",
        )):
            if json.loads(stored.result_json)["checkpoint"]["checkpoint_ref"] == command.checkpoint_ref:
                raise ConflictError("Checkpoint reference already used")
        execution.checkpoint_json = canonical_json(checkpoint)
        execution.phase_id = task.current_phase_id
        execution.state = "waiting"
        execution.resume_operation_key = None
        execution.resume_session_run_id = None
        execution.version += 1
        return self._record(command, "checkpoint", execution)

    def resume(self, command: PMResume, project_id: int) -> dict[str, Any]:
        execution, task = self.execution(self.identity(command), project_id)
        replay = self._replay(command, "resume")
        if replay is not None:
            return replay
        run = self._validate(command, execution, task, "waiting")
        if (
            command.new_session_run_id == run.session_run_id
            or self.session.get(m.PMRun, command.new_session_run_id) is not None
            or self.session.scalar(select(m.PMExecution).where(
                m.PMExecution.resume_session_run_id == command.new_session_run_id,
                m.PMExecution.state == "resume_pending",
            )) is not None
        ):
            raise ConflictError("Resume requires an unused Fleet session-run UUID")
        checkpoint = json.loads(execution.checkpoint_json or "{}")
        if any(command.model_dump()[key] != value for key, value in checkpoint.items()):
            raise ConflictError("Late answer: clarification/checkpoint/revision does not match")
        observed = RuntimeObservation.model_validate_json(run.observation_json)
        proof = self._proof(
            self.identity(command), run.run_ref, run.binding_ref, run.fence,
            observed.dispatch_operation_key, observed.checkpoint_ref,
            run.session_run_id,
        )
        if proof.status not in {"completed", "failed", "cancelled", "stopped"}:
            raise ConflictError("Old run is not terminal; runtime stop/readback is required")
        run.terminal_json = proof.model_dump_json()
        execution.state = "resume_pending"
        execution.version += 1
        execution.fence += 1
        execution.resume_operation_key = command.operation_key
        execution.resume_session_run_id = command.new_session_run_id
        return self._record(command, "resume", execution)

    def rebind(self, command: PMRebind, project_id: int) -> dict[str, Any]:
        execution, task = self.execution(self.identity(command), project_id)
        replay = self._replay(command, "rebind")
        if replay is not None:
            return replay
        run = self._validate(command, execution, task, "resume_pending")
        checkpoint = json.loads(execution.checkpoint_json or "{}")
        if (
            not run.terminal_json or command.checkpoint_ref != checkpoint.get("checkpoint_ref")
            or command.resume_operation_key != execution.resume_operation_key
            or command.new_session_run_id != execution.resume_session_run_id
            or command.new_session_run_id == run.session_run_id
            or self.session.get(m.PMRun, command.new_session_run_id) is not None
        ):
            raise ConflictError("Rebind requires terminal proof and the reserved new run/checkpoint")
        proof = self._proof(
            self.identity(command), command.new_hermes_run_ref, command.new_binding_ref,
            execution.fence, command.resume_operation_key, command.checkpoint_ref,
            command.new_session_run_id,
        )
        if proof.status != "running":
            raise ConflictError("Resumed run is not running; keep reservation and read back")
        self.session.add(m.PMRun(
            session_run_id=command.new_session_run_id, run_ref=command.new_hermes_run_ref,
            execution_ref=execution.execution_ref,
            binding_ref=command.new_binding_ref, fence=execution.fence, observation_json=proof.model_dump_json(),
        ))
        execution.session_run_id = command.new_session_run_id
        execution.state = "active"
        execution.version += 1
        return self._record(command, "rebind", execution)

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
                    self.concrete_agent_ref(assignment)
        return execution
