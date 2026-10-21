"""Pre-enrollment bootstrap recovery; internal types, not public wire DTOs."""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text

from project_workflow.application.single_task_runtime import current_binding, installed_context
from project_workflow.application.task import TaskService
from project_workflow.domain.base_admission import Sha256
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.namespace_ownership import UUIDRef
from project_workflow.domain.pm_execution import Key, RuntimeObservation, Version
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.domain.single_task_runtime import SingleTaskContext
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork


class BootstrapRetry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    predecessor_operation_key: Key
    predecessor_sha256: Sha256
    operation_key: Key
    bootstrap_attempt_ref: UUIDRef
    proof_sha256: Sha256


class BootstrapProof(BaseModel):
    """Returned only by the trusted Fleet composite/current-Tracker reader."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    predecessor_sha256: Sha256
    bootstrap_attempt_ref: UUIDRef
    native: RuntimeObservation
    current_context: SingleTaskContext
    assignment_ref: UUIDRef
    predecessor_owner_version: Version
    owner_version: Version
    original_operations: Literal["settled"]
    business_result: Literal["absent"]


class BootstrapMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    predecessor_operation_key: Key
    predecessor_payload_sha256: Sha256
    predecessor_assignment_revision: Version
    canonical_assignment_revision: Version
    workflow_assignment_revision: Version
    bootstrap_attempt_ref: UUIDRef
    proof_sha256: Sha256


def canonical_revision(uow: SAUnitOfWork, assignment: dict) -> int:
    mapping = assignment["payload"].get("pm_bootstrap_context")
    if mapping is None:
        return assignment["assignment_revision"]
    value = BootstrapMapping.model_validate(mapping)
    previous = uow.tasks.get_assignment_by_operation_key(value.predecessor_operation_key)
    if previous is None:
        raise ConflictError("Bootstrap predecessor is missing")
    old = previous.to_dict()
    old_mapping = old["payload"].get("pm_bootstrap_context")
    old_revision = (BootstrapMapping.model_validate(old_mapping).canonical_assignment_revision
                    if old_mapping is not None else old["assignment_revision"])
    if (old["task_id"] != assignment["task_id"] or old["assignment_ref"] != assignment["assignment_ref"]
        or old["payload_sha256"] != value.predecessor_payload_sha256
        or payload_sha256(old["payload"]) != old["payload_sha256"]
        or old["assignment_revision"] != value.predecessor_assignment_revision
        or assignment["assignment_revision"] != value.workflow_assignment_revision
        or assignment["assignment_revision"] != old["assignment_revision"] + 1
        or assignment["attempt_number"] != old["attempt_number"] + 1
        or value.canonical_assignment_revision != old_revision):
        raise ConflictError("Bootstrap canonical/local assignment mapping differs")
    return value.canonical_assignment_revision


class PMBootstrapService:
    def __init__(self, uow: SAUnitOfWork):
        self.uow = uow

    def _locked(self, project_id: int, task: str, operation_key: str) -> tuple[m.Task, dict]:
        # Initial PM enrollment takes these same namespace -> task locks.
        if self.uow.session.get_bind().dialect.name == "postgresql":
            self.uow.session.execute(text("SET LOCAL lock_timeout = '3s'"))
            self.uow.session.execute(text("SET LOCAL statement_timeout = '10s'"))
        project = self.uow.projects.lock_pm_namespace(project_id)
        if project is None:
            raise NotFoundError("PM namespace missing")
        row = self.uow.session.scalar(select(m.Task).where(
            m.Task.project_id == project_id, m.Task.task_key == task,
        ).with_for_update().execution_options(populate_existing=True))
        if row is None:
            raise NotFoundError("PM task missing")
        record = self.uow.tasks.get_assignment_by_operation_key(operation_key)
        if record is None or record.task_id != row.id:
            raise ConflictError("Foreign bootstrap predecessor")
        return row, record.to_dict()

    def _snapshot(self, row: m.Task, record: dict) -> dict:
        if (row.assignment_operation_key != record["operation_key"]
            or row.assignment_revision != record["assignment_revision"]
            or row.workflow_id != record["workflow_id"] or row.mode_id != record["mode_id"]
            or row.cycle_number != record["cycle_number"]
            or record["role_key"] != "project_manager" or record["mode_key"] != "draft"
            or record["stage_key"] != "Draft" or record["execution_scope"] != "business"
            or record["business_task_ref"] != record["root_task_ref"]
            or record["payload"].get("pm_review_context") is not None):
            raise ConflictError("Bootstrap predecessor is not the current initial PM assignment")
        if record.get("single_task_binding") is not None:
            bound = current_binding(self.uow, record)
            context, binding = bound["context"], bound["request"]
        else:
            # An actually absent bind is readable, never a fallback from partial custody.
            if (any(record.get(k) is not None for k in (
                "binding_ref", "hermes_run_ref", "bind_operation_key", "bind_request_sha256", "concrete_agent_ref",
            )) or payload_sha256(record["payload"]) != record["payload_sha256"]
                or any(record.get(k) != record["payload"].get(k) for k in (
                    *TaskService._RETRY_FROZEN_FIELDS, "operation_key", "assignment_ref", "attempt_number",
                ) if k != "mode_id")):
                raise ConflictError("Partial or changed bootstrap binding")
            context = installed_context(self.uow, row.project_id, record["payload"].get("single_task_context", {}))
            binding = None
        owner = self.uow.projects.get_pm_ownership(row.project_id)
        if (owner is None or owner["tracker_instance_ref"] != context["tracker_instance_ref"]
            or owner["tracker_project_ref"] != context["tracker_project_ref"]):
            raise ConflictError("Bootstrap namespace owner differs")
        first = self.uow.session.scalar(select(m.Phase).where(
            m.Phase.mode_id == row.mode_id,
        ).order_by(m.Phase.phase_order))
        enrolled = bool(self.uow.session.scalar(select(m.PMExecution.execution_ref).where(
            (m.PMExecution.task_id == row.id) | (m.PMExecution.execution_ref == context["execution_ref"]),
        ).limit(1)))
        steps = bool(self.uow.session.scalar(select(m.TaskStepHistoryEntry.id).where(
            m.TaskStepHistoryEntry.task_id == row.id,
        ).limit(1)))
        progressed = bool(self.uow.session.scalar(select(m.TaskPhaseEvent.id).where(
            m.TaskPhaseEvent.task_id == row.id,
            (m.TaskPhaseEvent.event_type != "entered") | (m.TaskPhaseEvent.phase_id != row.current_phase_id)
            | m.TaskPhaseEvent.step_history_id.is_not(None),
        ).limit(1)))
        return {
            "task": row.task_key, "task_id": row.id, "project_id": row.project_id,
            "assignment_operation_key": record["operation_key"],
            "assignment_revision": record["assignment_revision"], "attempt_number": record["attempt_number"],
            "assignment_ref": record["assignment_ref"], "payload_sha256": record["payload_sha256"],
            "canonical_assignment_revision": canonical_revision(self.uow, record),
            "context": context, "task_ref": record["business_task_ref"], "root_ref": record["root_task_ref"],
            "binding": binding, "status": row.status, "cycle_number": row.cycle_number,
            "current_phase_id": row.current_phase_id, "pm_enrolled": enrolled,
            "step_state": "recorded" if steps or progressed else "absent",
            "initial_phase": first is not None and row.current_phase_id == first.id,
        }

    def predecessor(self, project_id: int, task: str, operation_key: str, revision: int) -> dict:
        row, record = self._locked(project_id, task, operation_key)
        if record["assignment_revision"] != revision:
            raise ConflictError("Bootstrap predecessor revision differs")
        result = self._snapshot(row, record)
        return {**result, "sha256": payload_sha256(result)}

    def retry(
        self, project_id: int, task: str, request: BootstrapRetry,
        read_current: Callable[[BootstrapRetry], BootstrapProof],
    ) -> dict:
        service = TaskService(self.uow)

        def replayed(record):
            payload = record.to_dict()["payload"]
            if (record.project_id != project_id or payload.get("task_key") != task
                or payload.get("pm_bootstrap_request") != request.model_dump()):
                raise ConflictError("Bootstrap operation key/body conflict")
            return service._reconcile_assignment(record.to_dict(), payload)

        replay = self.uow.tasks.get_assignment_by_operation_key(request.operation_key)
        if replay is not None:
            return replayed(replay)
        # Fleet may query the predecessor reader while constructing its composite.
        # Do not hold our task lock during that remote call; recheck the digest below.
        proof = read_current(request)
        if (not isinstance(proof, BootstrapProof) or proof.predecessor_sha256 != request.predecessor_sha256
            or proof.bootstrap_attempt_ref != request.bootstrap_attempt_ref
            or payload_sha256(proof.model_dump()) != request.proof_sha256):
            raise ConflictError("Validated Fleet/Tracker bootstrap proof required")
        actual = pm_readback.observe_run(proof.native.session_run_id)
        if (actual.model_dump(exclude={"observation_ref"}) != proof.native.model_dump(exclude={"observation_ref"})
            or actual.status not in {"completed", "failed", "cancelled", "stopped"}
            or actual.checkpoint_ref is not None or actual.fence != 1):
            raise ConflictError("Exact terminal initial native custody required")
        row, previous = self._locked(project_id, task, request.predecessor_operation_key)
        replay = self.uow.tasks.get_assignment_by_operation_key(request.operation_key)
        if replay is not None:
            return replayed(replay)
        context = installed_context(self.uow, project_id, proof.current_context.model_dump(mode="json"))
        payload = {**previous["payload"], "operation_key": request.operation_key,
                   "attempt_number": previous["attempt_number"] + 1, "single_task_context": context,
                   "expected_revision": previous["assignment_revision"], "expected_status": "active",
                   "expected_mode_key": "draft", "expected_cycle_number": row.cycle_number}
        mapping = BootstrapMapping(
            predecessor_operation_key=previous["operation_key"],
            predecessor_payload_sha256=previous["payload_sha256"],
            predecessor_assignment_revision=previous["assignment_revision"],
            canonical_assignment_revision=canonical_revision(self.uow, previous),
            workflow_assignment_revision=previous["assignment_revision"] + 1,
            bootstrap_attempt_ref=request.bootstrap_attempt_ref, proof_sha256=request.proof_sha256,
        )
        payload["pm_bootstrap_context"] = mapping.model_dump()
        payload["pm_bootstrap_request"] = request.model_dump()
        state = self._snapshot(row, previous)
        native = proof.native
        old_context = state["context"]
        if (payload_sha256(state) != request.predecessor_sha256 or state["pm_enrolled"]
            or state["step_state"] != "absent" or not state["initial_phase"] or state["status"] != "active"
            or state["cycle_number"] != 0 or state["binding"] is None
            or request.operation_key == previous["operation_key"]
            or proof.owner_version != proof.predecessor_owner_version
            or proof.assignment_ref != previous["assignment_ref"]
            or any(context[k] != old_context[k] for k in (
                "instruction_profile", "instruction_manifest_sha256", "tracker_instance_ref", "tracker_project_ref",
                "execution_ref", "concrete_agent_ref",
            ))
            or any(getattr(native, k) != v for k, v in {
                "task": row.task_key, "assignment_operation_key": previous["operation_key"],
                "assignment_ref": previous["assignment_ref"],
                "assignment_revision": mapping.canonical_assignment_revision,
                "execution_ref": old_context["execution_ref"],
                "tracker_instance_ref": old_context["tracker_instance_ref"],
                "tracker_project_ref": old_context["tracker_project_ref"], "task_ref": state["task_ref"],
                "root_ref": state["root_ref"], "agent_ref": old_context["concrete_agent_ref"],
                **{k: state["binding"][k] for k in ("binding_ref", "hermes_run_ref", "session_run_id")},
            }.items())):
            raise ConflictError("Bootstrap predecessor, authority or no-enrollment fence differs")
        service._validate_retry_assignment(previous=previous, payload=payload,
                                           mode_id=previous["mode_id"], attempt_number=payload["attempt_number"])
        self.uow.tasks.create_assignment(service._assignment_record(
            payload, operation_key=request.operation_key, task_id=row.id, project_id=project_id,
            workflow_id=row.workflow_id, mode_id=row.mode_id, cycle_number=row.cycle_number,
            assignment_revision=mapping.workflow_assignment_revision,
        ))
        self.uow.tasks.update(row.id, {"assignment_operation_key": request.operation_key,
                                      "assignment_revision": mapping.workflow_assignment_revision})
        self.uow.commit()
        saved = self.uow.tasks.get_assignment_by_operation_key(request.operation_key)
        current = self.uow.tasks.get_by_id(row.id)
        if saved is None or current is None:
            raise RuntimeError("Bootstrap successor readback missing")
        return service._assignment_result(current.to_dict(), saved.to_dict())
