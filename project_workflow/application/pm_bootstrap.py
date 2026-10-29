"""Read-only decoding of retained bootstrap authority; no retry executor."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from project_workflow.domain.base_admission import Sha256
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.namespace_ownership import UUIDRef
from project_workflow.domain.pm_execution import Key, RuntimeObservation, Version
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.domain.single_task_runtime import SingleTaskContext
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
    canonical_assignment_operation_key: Key
    canonical_assignment_revision: Version
    workflow_assignment_revision: Version
    bootstrap_attempt_ref: UUIDRef
    proof_sha256: Sha256


def canonical_assignment(uow: SAUnitOfWork, assignment: dict) -> tuple[str, int]:
    """Resolve authority only through the retained, hash-bound predecessor chain."""
    mappings = []
    seen = set()
    while True:
        if (assignment["operation_key"] in seen
            or payload_sha256(assignment["payload"]) != assignment["payload_sha256"]):
            raise ConflictError("Bootstrap assignment history differs")
        seen.add(assignment["operation_key"])
        mapping = assignment["payload"].get("pm_bootstrap_context")
        if mapping is None:
            break
        value = BootstrapMapping.model_validate(mapping)
        previous = uow.tasks.get_assignment_by_operation_key(value.predecessor_operation_key)
        if previous is None:
            raise ConflictError("Bootstrap predecessor is missing")
        old = previous.to_dict()
        if (old["task_id"] != assignment["task_id"] or old["project_id"] != assignment["project_id"]
            or old["assignment_ref"] != assignment["assignment_ref"]
            or old["payload_sha256"] != value.predecessor_payload_sha256
            or old["assignment_revision"] != value.predecessor_assignment_revision
            or assignment["assignment_revision"] != value.workflow_assignment_revision
            or assignment["assignment_revision"] != old["assignment_revision"] + 1
            or assignment["attempt_number"] != old["attempt_number"] + 1):
            raise ConflictError("Bootstrap canonical/local assignment mapping differs")
        frozen = (
            "workflow_id", "workflow_key", "mode_id", "role_key", "execution_scope", "stage_key",
            "cycle_number", "business_task_ref", "root_task_ref", "work_item_ref", "work_item_revision",
            "queue_item_ref", "task_workspace_ref", "workspace_revision", "decomposition_revision_ref",
            "stage_revision", "exact_input_refs",
        )
        candidate = {**assignment["payload"], "mode_id": old["mode_id"]}
        if any(old.get(key) != candidate.get(key) for key in frozen):
            raise ConflictError("Retained bootstrap changed frozen assignment fields")
        mappings.append(value)
        assignment = old
    authority = (assignment["operation_key"], assignment["assignment_revision"])
    if mappings and (authority[0] != f"pm-draft:{assignment['assignment_ref']}" or any(
        (value.canonical_assignment_operation_key, value.canonical_assignment_revision) != authority
        for value in mappings
    )):
        raise ConflictError("Bootstrap canonical assignment differs from retained root")
    return authority
