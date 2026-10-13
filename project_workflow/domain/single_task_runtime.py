"""Single-task assignment context; not native-runtime or lease-liveness proof."""

from typing import Literal

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
