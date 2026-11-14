"""Fleet-owned research execution, independent of Tracker and standalone mode."""
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .namespace_ownership import UUIDRef
from .runtime_assignment import payload_sha256


class BackgroundConclusion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    status: Literal["complete", "incomplete"]
    summary: str = Field(min_length=1)
    coverage: list[str] = Field(min_length=1)
    limitations: list[str]

    @model_validator(mode="after")
    def meaningful(self) -> "BackgroundConclusion":
        if any(not value.strip() for value in [self.summary, *self.coverage, *self.limitations]):
            raise ValueError("Research conclusion cannot contain empty statements")
        return self


class BackgroundStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    interaction_protocol: Literal["configured-cli-v1"]
    execution_mode: Literal["background"]
    run_id: UUIDRef
    namespace_id: int = Field(gt=0)
    report: str | None = Field(default=None, min_length=1)
    operation_key: str | None = Field(default=None, min_length=1, max_length=128)
    expected_version: int | None = Field(default=None, ge=1)
    research_result: BackgroundConclusion | None = None

    @model_validator(mode="after")
    def operation(self) -> "BackgroundStep":
        if self.report is None:
            if self.operation_key is not None or self.expected_version is not None or self.research_result is not None:
                raise ValueError("Instruction read cannot carry a write operation")
        elif not self.report.strip() or self.operation_key is None or self.expected_version is None:
            raise ValueError("Report requires operation_key and expected_version")
        if self.operation_key is not None and (
                self.operation_key != self.operation_key.strip() or any(ord(c) < 32 for c in self.operation_key)):
            raise ValueError("Canonical operation key required")
        return self


@dataclass(frozen=True)
class BackgroundFence:
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
    request: BackgroundStep
    authority_check: Callable[[], None] = field(repr=False, compare=False)

    def assert_task(self, task: dict[str, Any] | None) -> None:
        expected = {"id": self.task_id, "project_id": self.namespace_id,
                    "workflow_id": self.workflow_id, "mode_id": self.mode_id,
                    "cycle_number": self.cycle_number, "assignment_revision": self.assignment_revision,
                    "assignment_operation_key": self.assignment_operation_key,
                    "current_phase_id": self.expected_phase_id, "status": self.expected_status}
        if task is None or any(task.get(key) != value for key, value in expected.items()):
            raise ValueError("Background execution changed during evaluation")

    @property
    def request_sha256(self) -> str:
        return payload_sha256(self.request.model_dump(mode="json"))

    @property
    def operation_fingerprint(self) -> str:
        return payload_sha256({"mode": "background", "run_id": self.request.run_id,
                               "operation_key": self.request.operation_key})
