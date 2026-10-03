"""Versioned PM machine wire types. Human assertions are never runtime proof."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

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
    checkpoint: PMCheckpointData | None
    resume_operation_key: Key | None
    resume_session_run_id: FleetRunId | None
    terminal_readback: RuntimeObservation | None
    workflow_step_allowed: bool
    resume_delivered: bool


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
