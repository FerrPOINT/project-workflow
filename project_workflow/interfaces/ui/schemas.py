"""Pydantic request/response schemas for UI API endpoints."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictRequest(BaseModel):
    """Reject stale or misspelled API fields instead of silently ignoring them."""

    model_config = ConfigDict(extra="forbid")


class OptionalIntMixin:
    """Normalize optional integer fields coming from HTML/JSON forms."""

    @staticmethod
    def _coerce_optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None


class _PhaseOrderItem(StrictRequest):
    phase_id: int = Field(gt=0)
    phase_order: int = Field(gt=0)
    workflow_id: int | None = Field(default=None)


class PhaseCreate(StrictRequest, OptionalIntMixin):
    workflow_id: int | None = Field(default=None, gt=0, strict=True, description="Parent workflow id")
    phase_order: int | None = Field(default=None, description="1-based insertion position")
    insert_after: int | None = Field(default=None, description="Insert after this 0-based index")
    name: str = Field(default="Новая фаза")
    description: str = Field(default="")
    execution_type: Literal["sync", "parallel"] = Field(default="sync")
    agent_id: int | None = Field(default=None)
    code: str | None = Field(default=None)
    parallel_with: str | None = Field(default=None)
    rollback_target: str | None = Field(default=None)
    next_recommendation: str | None = Field(default=None)

    @field_validator("phase_order", mode="before")
    @classmethod
    def _validate_phase_order(cls, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("phase_order must be an integer") from exc
        if parsed <= 0:
            raise ValueError("phase_order must be positive")
        return parsed

    @field_validator("insert_after", mode="before")
    @classmethod
    def _validate_insert_after(cls, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError("insert_after must be an integer") from exc
        if parsed < 0:
            raise ValueError("insert_after must be zero or greater")
        return parsed

    @model_validator(mode="after")
    def _resolve_insert_after(self) -> PhaseCreate:
        if self.insert_after is None:
            return self
        resolved_order = self.insert_after + 1
        if self.phase_order is not None and self.phase_order != resolved_order:
            raise ValueError("phase_order conflicts with insert_after")
        self.phase_order = resolved_order
        return self


class PhaseUpdate(StrictRequest, OptionalIntMixin):
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    parallel_with: str | None = Field(default=None)
    rollback_target: str | None = Field(default=None)
    next_recommendation: str | None = Field(default=None)
    agent_id: int | None = Field(default=None)
    execution_type: Literal["sync", "parallel"] | None = Field(default=None)
    instructions: list[dict[str, Any]] | None = Field(default=None)
    checks: list[dict[str, Any]] | None = Field(default=None)
    evidence: list[dict[str, Any]] | None = Field(default=None)

    code: str | None = Field(default=None, exclude=True)
    phase_num: int | None = Field(default=None, exclude=True)
    phase_order: int | None = Field(default=None, exclude=True)


class WorkflowCreate(StrictRequest):
    name: str | None = Field(default=None)
    description: str = Field(default="")
    code: str | None = Field(default=None)


class WorkflowUpdate(StrictRequest):
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    code: str | None = Field(default=None)


class ProjectCreate(StrictRequest, OptionalIntMixin):
    code: str = Field(..., min_length=1)
    name: str | None = Field(default=None)
    description: str | None = Field(default="")
    workflow_id: int | None = Field(default=None)
    key_prefixes: list[str] | str = Field(default=[])

    @field_validator("workflow_id", mode="before")
    @classmethod
    def _validate_workflow_id(cls, value: Any) -> int | None:
        if value is None or value == "":
            return None
        parsed = cls._coerce_optional_int(value)
        if parsed is None:
            raise ValueError("workflow_id must be a positive integer")
        return parsed

    @field_validator("key_prefixes", mode="before")
    @classmethod
    def _validate_key_prefixes(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip().upper() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [line.strip().upper() for line in value.splitlines() if line.strip()]
        return []

    @field_validator("key_prefixes", mode="after")
    @classmethod
    def _ensure_prefixes_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("At least one task key prefix is required")
        if len(value) != len(set(value)):
            raise ValueError("Task key prefixes must be unique")
        return value

    @model_validator(mode="after")
    def _require_key_prefixes(self) -> ProjectCreate:
        if not self.key_prefixes:
            raise ValueError("At least one task key prefix is required")
        return self

    @field_validator("key_prefixes", mode="after")
    @classmethod
    def _validate_prefix_format(cls, value: list[str]) -> list[str]:
        for prefix in value:
            if not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
                raise ValueError(f"Invalid prefix '{prefix}': use uppercase letters/digits only")
            if len(prefix) < 2:
                raise ValueError(f"Prefix '{prefix}' too short (min 2 chars)")
        return value


class ProjectUpdate(StrictRequest, OptionalIntMixin):
    code: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    workflow_id: int | None = Field(default=None)
    key_prefixes: list[str] | str | None = Field(default=None)

    @field_validator("workflow_id", mode="before")
    @classmethod
    def _validate_workflow_id(cls, value: Any) -> int | None:
        if value is None or value == "":
            return None
        parsed = cls._coerce_optional_int(value)
        if parsed is None:
            raise ValueError("workflow_id must be a positive integer")
        return parsed

    @field_validator("key_prefixes", mode="before")
    @classmethod
    def _validate_key_prefixes(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [str(item).strip().upper() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [line.strip().upper() for line in value.splitlines() if line.strip()]
        return []

    @field_validator("key_prefixes", mode="after")
    @classmethod
    def _validate_prefix_format(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("At least one task key prefix is required")
        if len(value) != len(set(value)):
            raise ValueError("Task key prefixes must be unique")
        for prefix in value:
            if not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
                raise ValueError(f"Invalid prefix '{prefix}': use uppercase letters/digits only")
            if len(prefix) < 2:
                raise ValueError(f"Prefix '{prefix}' too short (min 2 chars)")
        return value


class AgentCreate(StrictRequest):
    name: str = Field(..., min_length=1)
    description: str = Field(default="")
    hermes_profile: str | None = Field(default=None, max_length=251)

    @field_validator("hermes_profile", mode="before")
    @classmethod
    def _validate_hermes_profile(cls, value: Any) -> str | None:
        profile = str(value or "").strip()
        if not profile:
            return None
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", profile):
            raise ValueError("Hermes profile must match [a-z0-9][a-z0-9_-]*")
        return profile


class AgentUpdate(StrictRequest):
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    hermes_profile: str | None = Field(default=None, max_length=251)

    @field_validator("hermes_profile", mode="before")
    @classmethod
    def _validate_hermes_profile(cls, value: Any) -> str | None:
        profile = str(value or "").strip()
        if not profile:
            return None
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", profile):
            raise ValueError("Hermes profile must match [a-z0-9][a-z0-9_-]*")
        return profile


class PhaseOrderUpdate(StrictRequest):
    orders: list[_PhaseOrderItem] = Field(default_factory=list)


class InstructionCreate(StrictRequest):
    phase_id: int = Field(...)
    description: str = Field(..., min_length=1)
    execution_type: Literal["sync", "parallel"] = Field(default="sync")
    skills: list[str] | None = Field(default=None)
    step_num: int | None = Field(default=None, gt=0, strict=True)


class InstructionUpdate(StrictRequest):
    description: str | None = Field(default=None, min_length=1)
    execution_type: Literal["sync", "parallel"] | None = Field(default=None)
    skills: list[str] | None = Field(default=None)


class InstructionReorder(StrictRequest):
    instruction_ids: list[int] = Field(...)
