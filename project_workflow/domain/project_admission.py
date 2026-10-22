"""Server-derived human project proof. Profession IDs never establish ownership."""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator


class SpaceAccessDenied(PermissionError):
    """A current human project admission or a separate product role is missing."""


class CentralIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: StrictStr = Field(min_length=1)
    subject: StrictStr = Field(min_length=1)


class AdmissionValidity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observed_at: StrictInt
    valid_until: StrictInt

    @model_validator(mode="after")
    def bounded(self):
        if self.observed_at <= 0 or not 0 < self.valid_until - self.observed_at <= 60:
            raise ValueError("Invalid admission window")
        return self


class SpaceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    registry_instance_id: UUID
    space_id: UUID

    @model_validator(mode="after")
    def non_nil(self):
        if not self.registry_instance_id.int or not self.space_id.int:
            raise ValueError("Nil space reference")
        return self


class ProjectAccessV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[2]
    identity: CentralIdentity
    tracker_instance_id: StrictStr = Field(min_length=1, max_length=128)
    canonical_tracker_instance_id: UUID
    policy_revision: StrictInt = Field(gt=0)
    validity: AdmissionValidity
    readable_spaces: tuple[SpaceRef, ...] = Field(max_length=10000)
    writable_spaces: tuple[SpaceRef, ...] = Field(max_length=10000)
    project_ids: tuple[UUID, ...] = Field(max_length=10000)
    writable_project_ids: tuple[UUID, ...] = Field(max_length=10000)

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_schema_version(cls, value):
        if type(value) is not int or value != 2:
            raise ValueError("Exact schema version required")
        return value

    @model_validator(mode="after")
    def distinct_projects(self):
        read, write = set(self.project_ids), set(self.writable_project_ids)
        if not self.canonical_tracker_instance_id.int:
            raise ValueError("Canonical Tracker identity required")
        if UUID(int=0) in read or len(read) != len(self.project_ids) or len(write) != len(self.writable_project_ids):
            raise ValueError("Invalid project IDs")
        spaces, active = set(self.readable_spaces), set(self.writable_spaces)
        if (len(spaces) != len(self.readable_spaces) or len(active) != len(self.writable_spaces)
                or not active <= spaces):
            raise ValueError("Invalid space subset")
        if not write <= read:
            raise ValueError("Write scope must be a subset of read scope")
        return self


@dataclass(frozen=True)
class HumanProjectScope:
    proof: ProjectAccessV2
    deadline: float
    product_role: str

    def require_current(self) -> None:
        if (time.monotonic() >= self.deadline or time.time() >= self.proof.validity.valid_until
                or time.time() < self.proof.validity.observed_at - 1):
            raise SpaceAccessDenied("Original project admission expired")

    def require_operator(self) -> None:
        self.require_current()
        if self.product_role not in {"admin", "platform_admin", "operator", "platform_operator"}:
            raise SpaceAccessDenied("Confirmed Workflow operator role required")

    def require_project(self, instance: str, project: str | UUID, *, write: bool = False) -> None:
        self.require_current()
        ids = self.proof.writable_project_ids if write else self.proof.project_ids
        instances = {self.proof.tracker_instance_id, str(self.proof.canonical_tracker_instance_id)}
        if instance not in instances or str(project) not in {str(p) for p in ids}:
            raise SpaceAccessDenied("Project access denied")
        if write:
            self.require_operator()


human_scope: ContextVar[HumanProjectScope | None] = ContextVar("workflow_human_project_scope", default=None)
