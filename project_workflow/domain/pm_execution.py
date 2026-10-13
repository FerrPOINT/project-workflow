"""Versioned PM machine wire types. Human assertions are never runtime proof."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from project_workflow.domain.base_admission import Sha256
from project_workflow.domain.namespace_ownership import InstanceRef, UUIDRef
from project_workflow.domain.runtime_assignment import FleetAgentRef

Ref = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=512)]
Key = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=128)]
Version = Annotated[int, Field(strict=True, ge=1, le=(1 << 63) - 1)]
FleetRunId = Annotated[str, StringConstraints(
    strict=True, pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
)]


class PMIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: Key
    execution_ref: Ref
    tracker_instance_ref: Ref
    tracker_project_ref: Ref
    task_ref: Ref
    root_ref: Ref
    agent_ref: FleetAgentRef
    assignment_operation_key: Key
    assignment_ref: Ref
    assignment_revision: Version


class PMBind(PMIdentity):
    operation_key: Key
    expected_version: Annotated[int, Field(strict=True, ge=0, le=0)]
    binding_ref: Ref
    hermes_run_ref: Ref
    session_run_id: FleetRunId


class PMDraftAssignment(PMIdentity):
    """Initial Tracker reservation; later-stage resources do not exist for a Draft."""

    task: Annotated[str, StringConstraints(strict=True, pattern=r"^SDLC-[1-9][0-9]*$", max_length=128)]
    tracker_instance_ref: InstanceRef
    tracker_project_ref: UUIDRef
    task_ref: UUIDRef
    root_ref: UUIDRef
    execution_ref: UUIDRef
    assignment_ref: UUIDRef
    assignment_operation_key: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
    assignment_revision: Annotated[int, Field(strict=True, ge=1, le=1)]
    input_snapshot_ref: UUIDRef
    input_sha256: Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
    owner_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    runtime_compatibility: dict[str, object]

    @model_validator(mode="after")
    def initial_reservation(self) -> "PMDraftAssignment":
        if (
            self.assignment_revision != 1 or self.owner_version != 1 or self.root_ref != self.task_ref
            or int(self.task.removeprefix("SDLC-")) > (1 << 63) - 1
            or self.assignment_operation_key != f"pm-draft:{self.assignment_ref}"
        ):
            raise ValueError("Initial PM Draft reservation identity required")
        return self


class PMCommand(PMIdentity):
    operation_key: Key
    expected_version: Version
    expected_fence: Version
    binding_ref: Ref
    hermes_run_ref: Ref
    session_run_id: FleetRunId


class PMCheckpoint(PMCommand):
    checkpoint_ref: Ref
    clarification_request_ref: Ref
    clarification_version: Version
    requirements_revision: Version


class PMResume(PMCheckpoint):
    answer_event_ref: Ref
    new_session_run_id: FleetRunId


class PMRebind(PMCommand):
    checkpoint_ref: Ref
    resume_operation_key: Key
    new_binding_ref: Ref
    new_hermes_run_ref: Ref
    new_session_run_id: FleetRunId


class PMReadback(PMIdentity):
    operation_key: Key | None = None


class SingleTaskPMProfile(BaseModel):
    instruction_profile: Literal["single-task-v1"]
    instruction_manifest_sha256: Sha256


class SingleTaskPMBind(PMBind, SingleTaskPMProfile):
    session_run_id: UUIDRef


class SingleTaskPMCheckpoint(PMCommand, SingleTaskPMProfile):
    checkpoint_ref: Ref
    requirements_revision: Version | None
    requirements_sha256: Sha256 | None
    clarification_request_ref: Ref | None = None
    clarification_version: Version | None = None

    @model_validator(mode="after")
    def clarification_pair(self) -> "SingleTaskPMCheckpoint":
        if (self.clarification_request_ref is None) != (self.clarification_version is None):
            raise ValueError("Clarification reference/version must be a real pair or absent")
        if (self.requirements_revision is None) != (self.requirements_sha256 is None):
            raise ValueError("Requirements revision/hash must be a real pair or explicitly absent")
        if self.clarification_request_ref is not None and self.requirements_revision is None:
            raise ValueError("Clarification requires an existing requirements revision")
        return self


class PMInputReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: Ref
    sha256: Sha256


class PMTypedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_kind: Literal["answer", "feedback", "confirmation"]
    input_id: UUIDRef


class SingleTaskPMResume(SingleTaskPMCheckpoint):
    new_session_run_id: UUIDRef
    input: PMTypedInput
    input_receipt: PMInputReceipt

    @model_validator(mode="after")
    def actual_input(self) -> "SingleTaskPMResume":
        if (self.input.input_kind == "answer") != (self.clarification_request_ref is not None):
            raise ValueError("Only a real answer carries clarification references")
        if self.input.input_kind != "feedback" and self.requirements_revision is None:
            raise ValueError("Answer/confirmation requires an existing requirements revision")
        return self


class SingleTaskPMRebind(PMRebind, SingleTaskPMProfile):
    new_session_run_id: UUIDRef


class SingleTaskPMReadback(PMReadback, SingleTaskPMProfile):
    pass


class SingleTaskPMCheckpointData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_ref: Ref
    requirements_revision: Version | None
    requirements_sha256: Sha256 | None
    clarification_request_ref: Ref | None = None
    clarification_version: Version | None = None

    @model_validator(mode="after")
    def actual_references(self) -> "SingleTaskPMCheckpointData":
        if ((self.requirements_revision is None) != (self.requirements_sha256 is None)
            or (self.clarification_request_ref is None) != (self.clarification_version is None)
            or self.clarification_request_ref is not None and self.requirements_revision is None):
            raise ValueError("Checkpoint requires paired real revision and clarification references")
        return self


class PMResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: PMTypedInput
    input_receipt: PMInputReceipt


class RuntimeObservation(PMIdentity):
    """Response obtained directly from the trusted readback provider."""

    observation_ref: Ref
    binding_ref: Ref
    hermes_run_ref: Ref
    session_run_id: FleetRunId
    status: Literal["running", "completed", "failed", "cancelled", "stopped"]
    dispatch_operation_key: Key
    checkpoint_ref: Ref | None = None
    fence: Version


class PMCheckpointData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checkpoint_ref: Ref
    clarification_request_ref: Ref
    clarification_version: Version
    requirements_revision: Version


class PMExecutionSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal[1]
    identity: PMIdentity
    state: Literal["active", "waiting", "resume_pending"]
    version: Version
    fence: Version
    session_run_id: FleetRunId
    binding_ref: Ref
    hermes_run_ref: Ref
    checkpoint: PMCheckpointData | SingleTaskPMCheckpointData | None
    resume_operation_key: Key | None
    resume_session_run_id: FleetRunId | None
    terminal_readback: RuntimeObservation | None
    workflow_step_allowed: bool
    resume_delivered: bool
    instruction_profile: Literal["single-task-v1"] | None = Field(default=None, exclude_if=lambda v: v is None)
    instruction_manifest_sha256: Sha256 | None = Field(default=None, exclude_if=lambda v: v is None)
    resume_input: PMResumeInput | None = Field(default=None, exclude_if=lambda v: v is None)
    single_task_context_sha256: Sha256 | None = Field(default=None, exclude_if=lambda v: v is None)


class PMOperationResult(BaseModel):
    operation_key: Key
    kind: Literal["bind", "checkpoint", "resume", "rebind"]
    request_sha256: str
    result: PMExecutionSnapshot


class PMResult(PMExecutionSnapshot):
    operation: PMOperationResult | None = None


class PMResponse(BaseModel):
    ok: Literal[True]
    result: PMResult
    execution_token: str | None = None
