"""Explicit local execution inputs; no external identities or assignment claims."""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .runtime_assignment import payload_sha256


class StandaloneStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    interaction_protocol: Literal["configured-cli-v1"]
    task: str = Field(min_length=1, max_length=128)
    namespace_id: int = Field(gt=0)
    start: bool = False
    workflow_id: int | None = Field(default=None, gt=0)
    mode_key: str | None = Field(default=None, min_length=1, max_length=128)
    operation_key: str | None = Field(default=None, min_length=1, max_length=128)
    expected_version: int | None = Field(default=None, ge=1)
    report: str | None = Field(default=None, min_length=1, max_length=32_000)

    @model_validator(mode="after")
    def validate_operation(self) -> "StandaloneStep":
        for value in (self.task, self.operation_key, self.mode_key):
            if value is not None and (value != value.strip() or any(ord(c) < 32 for c in value)):
                raise ValueError("Canonical task, mode and operation key required")
        if self.start:
            if self.workflow_id is None or self.mode_key is None or self.operation_key is None:
                raise ValueError("Start requires workflow_id, mode_key and operation_key")
            if self.report is not None or self.expected_version is not None:
                raise ValueError("Start cannot submit a report or reset a version")
        elif self.workflow_id is not None or self.mode_key is not None:
            raise ValueError("Workflow and mode selection belongs to explicit start")
        elif self.report is not None:
            if self.operation_key is None or self.expected_version is None:
                raise ValueError("Report requires operation_key and expected_version")
        elif self.operation_key is not None or self.expected_version is not None:
            raise ValueError("Instruction read cannot carry a write operation")
        return self


@dataclass(frozen=True)
class StandaloneFence:
    task_id: int
    namespace_id: int
    workflow_id: int
    mode_id: int
    cycle_number: int
    assignment_revision: int
    assignment_operation_key: str
    expected_phase_id: int
    expected_status: str
    version: int
    request: StandaloneStep

    def assert_task(self, task: dict[str, Any] | None) -> None:
        expected = {"id": self.task_id, "project_id": self.namespace_id,
                    "workflow_id": self.workflow_id, "mode_id": self.mode_id,
                    "cycle_number": self.cycle_number, "assignment_revision": self.assignment_revision,
                    "assignment_operation_key": self.assignment_operation_key,
                    "current_phase_id": self.expected_phase_id, "status": self.expected_status}
        if task is None or any(task.get(key) != value for key, value in expected.items()):
            raise ValueError("Standalone execution changed during evaluation")

    @property
    def request_sha256(self) -> str:
        return payload_sha256(self.request.model_dump(mode="json"))

    @property
    def operation_fingerprint(self) -> str:
        return payload_sha256({"mode": "standalone", "start": self.assignment_operation_key,
                               "operation_key": self.request.operation_key})
