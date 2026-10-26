"""Fileless, business-assignment-scoped PM interaction; never a native run proof."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from project_workflow.domain.base_admission import Sha256
from project_workflow.domain.namespace_ownership import UUIDRef
from project_workflow.domain.runtime_assignment import FleetAgentRef, payload_sha256
from project_workflow.domain.single_task_runtime import WorkflowArtifactReceipt

PROTOCOL: Literal["configured-cli-v1"] = "configured-cli-v1"


class ConfiguredAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interaction_protocol: Literal["configured-cli-v1"]
    task: str = Field(min_length=1, max_length=128)
    namespace_id: int = Field(gt=0, strict=True)
    workflow_key: Literal["single-task-v1:project_manager"]
    mode_key: Literal["draft"]
    role_key: Literal["project_manager"] = "project_manager"
    operation_key: str = Field(min_length=1, max_length=128)
    assignment_ref: UUIDRef
    tracker_execution_id: UUIDRef
    assignment_version: int = Field(gt=0, strict=True)
    business_task_ref: UUIDRef
    machine_subject: UUIDRef
    concrete_agent_ref: FleetAgentRef
    tracker_task_id: UUIDRef
    owner_subject: UUIDRef
    expected_version: Literal[0]

    @model_validator(mode="after")
    def business_identity(self) -> ConfiguredAssignment:
        if self.business_task_ref != self.tracker_task_id:
            raise ValueError("business_task_ref must be the canonical Tracker task UUID")
        return self

    @field_validator("expected_version", mode="before")
    @classmethod
    def zero_version(cls, value: Any) -> int:
        if type(value) is not int or value != 0:
            raise ValueError("New enrollment requires integer expected_version=0")
        return value

    @field_validator("task", "operation_key", "assignment_ref", "business_task_ref")
    @classmethod
    def bounded_text(cls, value: str) -> str:
        if value != value.strip() or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Nonempty canonical text required")
        return value


class ConfiguredStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interaction_protocol: Literal["configured-cli-v1"]
    task: str = Field(min_length=1, max_length=128)
    namespace_id: int = Field(gt=0, strict=True)
    operation_key: str | None = Field(default=None, min_length=1, max_length=128)
    expected_version: int | None = Field(default=None, ge=1, strict=True)
    report: str | None = Field(default=None, min_length=1, max_length=32_000)
    requirements_revision: int | None = Field(default=None, ge=1, strict=True)
    requirements_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def write_fence(self) -> ConfiguredStep:
        for value in (self.task, self.operation_key):
            if value is not None and (value != value.strip() or any(ord(c) < 32 for c in value)):
                raise ValueError("Canonical task/key required")
        if self.report is not None:
            if not self.report.strip() or self.operation_key is None or self.expected_version is None:
                raise ValueError("Report requires operation_key and expected_version")
        elif any(value is not None for value in (self.operation_key, self.expected_version,
                                                self.requirements_revision, self.requirements_sha256)):
            raise ValueError("Instruction reads do not carry a write operation")
        if (self.requirements_revision is None) != (self.requirements_sha256 is None):
            raise ValueError("Requirements revision and hash must be supplied together")
        return self


class ConfiguredTerminalReadback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interaction_protocol: Literal["configured-cli-v1"]
    task: str = Field(min_length=1, max_length=128)
    namespace_id: int = Field(gt=0, strict=True)
    execution_ref: UUIDRef
    operation_key: str = Field(min_length=1, max_length=128)
    concrete_agent_ref: FleetAgentRef
    assignment_ref: UUIDRef
    requirements_revision: int = Field(ge=1, strict=True)
    requirements_sha256: Sha256
    result_version: int = Field(ge=2, strict=True)


class ConfiguredTerminalReceipt(ConfiguredTerminalReadback):
    tracker_task_id: UUIDRef
    request_sha256: Sha256
    owner_subject: UUIDRef
    confirmation_id: UUIDRef
    history_id: int = Field(gt=0, strict=True)
    status: Literal["done"]


class ConfiguredTerminalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: Literal[True]
    complete: Literal[True]
    workflow_receipt: WorkflowArtifactReceipt
    receipt: ConfiguredTerminalReceipt


@dataclass(frozen=True)
class ConfiguredCliFence:
    """Internal capability constructed only after fresh Auth and assignment checks."""

    task_id: int
    namespace_id: int
    workflow_id: int
    mode_id: int
    cycle_number: int
    assignment_revision: int
    assignment_operation_key: str
    assignment_sha256: str
    expected_phase_id: int
    expected_status: str
    version: int
    request: ConfiguredStep
    enrollment: dict[str, Any]
    authorization: str = field(repr=False, compare=False)
    confirmation: dict[str, Any] | None = None

    def assert_task(self, task: dict[str, Any] | None) -> None:
        expected = {
            "id": self.task_id, "project_id": self.namespace_id, "workflow_id": self.workflow_id,
            "mode_id": self.mode_id, "cycle_number": self.cycle_number,
            "assignment_revision": self.assignment_revision,
            "assignment_operation_key": self.assignment_operation_key,
            "current_phase_id": self.expected_phase_id, "status": self.expected_status,
        }
        if task is None or any(task.get(k) != v for k, v in expected.items()):
            raise ValueError("Configured CLI assignment/cursor changed")

    @property
    def request_sha256(self) -> str:
        return payload_sha256(self.request.model_dump(mode="json"))

    @property
    def operation_fingerprint(self) -> str:
        return payload_sha256({"protocol": PROTOCOL, "assignment": self.assignment_operation_key,
                               "operation_key": self.request.operation_key})
