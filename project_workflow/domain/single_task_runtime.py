"""Single-task assignment context; not native-runtime or lease-liveness proof."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from project_workflow.domain.base_admission import Sha256
from project_workflow.domain.namespace_ownership import InstanceRef, UUIDRef, canonical_uuid
from project_workflow.domain.runtime_assignment import FleetAgentRef
from project_workflow.domain.single_task_profile import MANIFEST_SHA256, ROLE_MODES


def validate_assignment_identity(
    *, workflow_key: str, role_key: str, mode_key: str, execution_scope: str, stage_key: str,
    business_task_ref: str, root_task_ref: str, assignment_ref: str,
) -> None:
    if (workflow_key != f"single-task-v1:{role_key}" or business_task_ref != root_task_ref
        or execution_scope not in ROLE_MODES.get(role_key, {}).get(mode_key, [])):
        raise ValueError("Single-task profile/task=root/mode mismatch")
    canonical_uuid(business_task_ref)
    canonical_uuid(assignment_ref)
    stages = {"draft": "Draft", "analysis": "Analysis", "decomposition": "Architecture",
              "initial": "Development", "rework": "Rework"}
    stage = stages.get(mode_key, {"reviewer": "Review", "tester": "Testing", "devops": "Deployment"}.get(role_key))
    if stage != stage_key:
        raise ValueError("Single-task role/mode/stage mismatch")


class SingleTaskContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruction_profile: Literal["single-task-v1"]
    instruction_manifest_sha256: Sha256
    tracker_instance_ref: InstanceRef
    tracker_project_ref: UUIDRef
    execution_ref: UUIDRef
    concrete_agent_ref: FleetAgentRef
    task_revision: int = Field(strict=True, gt=0)
    lease_ref: UUIDRef
    lease_version: int = Field(strict=True, gt=0)
    fencing_token: int = Field(strict=True, gt=0)

    @model_validator(mode="after")
    def exact_manifest(self) -> "SingleTaskContext":
        if self.instruction_manifest_sha256 != MANIFEST_SHA256:
            raise ValueError("Single-task manifest mismatch")
        return self


class WorkflowArtifactReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(strict=True, min_length=1, max_length=512)
    sha256: Sha256


class SingleTaskTerminalReadback(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={
        "oneOf": [
            {"required": ["step_operation_key"], "properties": {
                "step_operation_key": {"type": "string"}, "receipt_reference": {"type": "null"},
                "current_run": {"const": False},
            }},
            {"required": ["receipt_reference", "receipt_sha256"], "properties": {
                "receipt_reference": {"type": "string"}, "receipt_sha256": {"type": "string"},
                "step_operation_key": {"type": "null"},
                "current_run": {"const": False},
            }},
            {"required": ["current_run"], "properties": {
                "current_run": {"const": True}, "step_operation_key": {"type": "null"},
                "receipt_reference": {"type": "null"},
            }},
        ],
    })
    task: str = Field(strict=True, min_length=1, max_length=128)
    step_operation_key: str | None = Field(default=None, strict=True, min_length=1, max_length=128)
    receipt_reference: str | None = Field(default=None, strict=True, min_length=1, max_length=512)
    current_run: bool = Field(default=False, strict=True)
    instruction_profile: Literal["single-task-v1"]
    instruction_manifest_sha256: Sha256
    session_run_id: UUIDRef
    single_task_context_sha256: Sha256
    receipt_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def exact_selector(self) -> "SingleTaskTerminalReadback":
        if sum((self.step_operation_key is not None, self.receipt_reference is not None, self.current_run)) != 1:
            raise ValueError("Exactly one terminal step key, receipt reference or current-run selector required")
        if self.receipt_reference is not None and self.receipt_sha256 is None:
            raise ValueError("Receipt reference lookup requires receipt_sha256")
        return self


class SingleTaskTerminalReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_schema: Literal["single-task-sdlc/workflow-terminal-receipt/v1"] = Field(alias="schema")
    reference: str = Field(strict=True, min_length=1, max_length=512)
    complete: Literal[True]
    binding: dict[str, Any]
    single_task_context_sha256: Sha256
    assignment_sha256: Sha256
    cursor: dict[str, int | str]
    step: dict[str, str]
    result: dict[str, Any]
    accepted_response_sha256: Sha256


class SingleTaskTerminalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[True]
    complete: Literal[True]
    workflow_receipt: WorkflowArtifactReceipt
    receipt: SingleTaskTerminalReceipt
