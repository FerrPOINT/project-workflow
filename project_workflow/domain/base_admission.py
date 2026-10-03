"""Declared configuration pins for opt-in Base source validation, not execution proof."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from project_workflow.domain.runtime_assignment import FleetAgentRef

BASE_SKILLS_REVISION = "4b9b4c9297a13fb28a6ba2039af2f7cb719f2f58"
Sha256 = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]
ExactRef = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512, pattern=r"^\S(?:.*\S)?$")]


class BaseAdmission(BaseModel):
    """Source expectation; actual trusted frozen Fleet binding is still required."""

    model_config = ConfigDict(extra="forbid", strict=True)

    contract: Literal["base-sdlc-admission/v1"]
    config_ref: ExactRef
    config_sha256: Sha256
    concrete_agent_ref: FleetAgentRef
    namespace: ExactRef
    profile: ExactRef
    catalog_sha256: Sha256
    skills_revision: Literal["4b9b4c9297a13fb28a6ba2039af2f7cb719f2f58"]
    skills_manifest_sha256: Sha256
    role_instruction_sha256: Sha256
    physical_skills: list[str] = Field(min_length=1, max_length=14)


class BaseTerminalReadback(BaseModel):
    """Exact owner operation lookup; no model-authored success payload."""

    model_config = ConfigDict(extra="forbid", strict=True)

    task: ExactRef
    step_operation_key: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
    assignment_revision: int = Field(gt=0)
    assignment_ref: ExactRef
    binding_ref: ExactRef
    hermes_run_ref: ExactRef
    mode_key: ExactRef
    cycle_number: int = Field(ge=0)
    attempt_number: int = Field(gt=0)
    base_config_ref: ExactRef
    base_config_sha256: Sha256
    receipt_sha256: Sha256 | None = None
    session_run_id: str | None = Field(default=None, min_length=36, max_length=36)
