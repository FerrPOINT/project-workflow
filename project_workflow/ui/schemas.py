"""Pydantic request/response schemas for UI API endpoints."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from project_workflow import config


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


class _PhaseOrderItem(BaseModel):
    phase_id: int | str
    phase_order: int
    workflow_id: int | None = Field(default=None)


class PhaseCreate(BaseModel, OptionalIntMixin):
    workflow_id: int | str | None = Field(default=None, description="Parent workflow id or code")
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

    @field_validator("phase_order", "insert_after", mode="before")
    @classmethod
    def _validate_phase_order(cls, value: Any) -> int | None:
        return cls._coerce_optional_int(value)

    @model_validator(mode="after")
    def _resolve_insert_after(self) -> PhaseCreate:
        if self.insert_after is not None and self.phase_order is None:
            self.phase_order = self.insert_after + 1
        return self


class PhaseUpdate(BaseModel, OptionalIntMixin):
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    delegate_agent: str | None = Field(default=None)
    delegate_timeout: int | str | None = Field(default=None)
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


class WorkflowCreate(BaseModel):
    name: str | None = Field(default=None)
    description: str = Field(default="")
    code: str | None = Field(default=None)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    code: str | None = Field(default=None)


class ProjectCreate(BaseModel, OptionalIntMixin):
    code: str = Field(..., min_length=1)
    name: str | None = Field(default=None)
    description: str | None = Field(default="")
    workflow_id: int | None = Field(default=None)
    key_prefixes: list[str] | str = Field(default=[])

    @field_validator("workflow_id", mode="before")
    @classmethod
    def _validate_workflow_id(cls, value: Any) -> int | None:
        return cls._coerce_optional_int(value)

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
            return list(config.DEFAULT_TASK_KEY_PREFIXES)
        return value

    @field_validator("key_prefixes", mode="after")
    @classmethod
    def _validate_prefix_format(cls, value: list[str]) -> list[str]:
        for prefix in value:
            if not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
                raise ValueError(f"Invalid prefix '{prefix}': use uppercase letters/digits only")
            if len(prefix) < 2:
                raise ValueError(f"Prefix '{prefix}' too short (min 2 chars)")
        return value


class ProjectUpdate(BaseModel, OptionalIntMixin):
    code: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    workflow_id: int | None = Field(default=None)
    key_prefixes: list[str] | str | None = Field(default=None)

    @field_validator("workflow_id", mode="before")
    @classmethod
    def _validate_workflow_id(cls, value: Any) -> int | None:
        return cls._coerce_optional_int(value)

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
        for prefix in value:
            if not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
                raise ValueError(f"Invalid prefix '{prefix}': use uppercase letters/digits only")
            if len(prefix) < 2:
                raise ValueError(f"Prefix '{prefix}' too short (min 2 chars)")
        return value


class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = Field(default="")


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)


class PhaseOrderUpdate(BaseModel):
    orders: list[_PhaseOrderItem] = Field(default=[])


class InstructionCreate(BaseModel):
    phase_id: int = Field(...)
    description: str = Field(..., min_length=1)
    execution_type: Literal["sync", "parallel"] = Field(default="sync")
    skills: list[str] | None = Field(default=None)


class InstructionUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1)
    execution_type: Literal["sync", "parallel"] | None = Field(default=None)
    skills: list[str] | str | None = Field(default=None)
    step_num: int | None = Field(default=None)


class InstructionReorder(BaseModel):
    instruction_ids: list[int] = Field(...)
