"""Pydantic request/response schemas for UI API endpoints."""

from __future__ import annotations

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictRequest(BaseModel):
    """Reject stale or misspelled API fields instead of silently ignoring them."""

    model_config = ConfigDict(extra="forbid")


class StrictUpdateRequest(StrictRequest):
    """Give omitted and explicit null distinct, declared meanings."""

    non_nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="before")
    @classmethod
    def _reject_explicit_nulls(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        invalid = sorted(field for field in cls.non_nullable_fields if field in value and value[field] is None)
        if invalid:
            raise ValueError(f"Fields cannot be null: {', '.join(invalid)}")
        return value


def _strip_nonblank(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _normalize_string_list(value: Any, field_name: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings or null")
    normalized = [_strip_nonblank(item, field_name) for item in value]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} must contain unique values")
    return normalized


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
    phase_id: int = Field(gt=0, strict=True)
    phase_order: int = Field(gt=0, strict=True)
    workflow_id: int | None = Field(default=None, gt=0, strict=True)


class PhaseCreate(StrictRequest, OptionalIntMixin):
    workflow_id: int = Field(gt=0, strict=True, description="Parent workflow id")
    phase_order: int | None = Field(default=None, gt=0, strict=True, description="1-based insertion position")
    insert_after: int | None = Field(default=None, ge=0, strict=True, description="Insert after this 0-based index")
    name: str = Field(default="Новая фаза")
    description: str = Field(default="")
    execution_type: Literal["sync", "parallel"] = Field(default="sync")
    agent_id: int | None = Field(default=None, gt=0, strict=True)
    code: str | None = Field(default=None)
    parallel_with: str | None = Field(default=None)
    rollback_target: str | None = Field(default=None)
    next_recommendation: str | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "name")

    @field_validator("code")
    @classmethod
    def _code_not_blank(cls, value: str | None) -> str | None:
        return _strip_nonblank(value, "code") if value is not None else None

    @field_validator("parallel_with", "rollback_target")
    @classmethod
    def _links_not_blank(cls, value: str | None, info: Any) -> str | None:
        return _strip_nonblank(value, info.field_name) if value is not None else None

    @model_validator(mode="after")
    def _resolve_insert_after(self) -> PhaseCreate:
        if self.insert_after is None and self.phase_order is None:
            raise ValueError("phase_order or insert_after is required")
        if self.insert_after is None:
            return self
        resolved_order = self.insert_after + 1
        if self.phase_order is not None and self.phase_order != resolved_order:
            raise ValueError("phase_order conflicts with insert_after")
        self.phase_order = resolved_order
        return self


class PhaseInstructionItem(StrictRequest):
    description: str
    execution_type: Literal["sync", "parallel"] = "sync"
    skills: list[str] | None = None

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "description")

    @field_validator("skills", mode="before")
    @classmethod
    def _validate_skills(cls, value: Any) -> list[str] | None:
        return _normalize_string_list(value, "skills")


class PhaseTextItem(StrictRequest):
    description: str

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "description")


class PhaseUpdate(StrictUpdateRequest, OptionalIntMixin):
    non_nullable_fields = frozenset({"name", "execution_type", "instructions", "checks", "evidence"})

    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    parallel_with: str | None = Field(default=None)
    rollback_target: str | None = Field(default=None)
    next_recommendation: str | None = Field(default=None)
    agent_id: int | None = Field(default=None, gt=0, strict=True)
    execution_type: Literal["sync", "parallel"] | None = Field(default=None)
    instructions: list[PhaseInstructionItem] | None = Field(default=None)
    checks: list[PhaseTextItem] | None = Field(default=None)
    evidence: list[PhaseTextItem] | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return _strip_nonblank(value, "name") if value is not None else None

    @field_validator("parallel_with", "rollback_target")
    @classmethod
    def _links_not_blank(cls, value: str | None, info: Any) -> str | None:
        return _strip_nonblank(value, info.field_name) if value is not None else None

    @model_validator(mode="after")
    def _descriptions_must_be_unique(self) -> PhaseUpdate:
        for field_name in ("checks", "evidence"):
            items = getattr(self, field_name)
            if items is None:
                continue
            normalized = [item.description.casefold() for item in items]
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"{field_name} descriptions must be unique")
        return self


class WorkflowCreate(StrictRequest):
    name: str
    description: str = Field(default="")

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "name")


class WorkflowUpdate(StrictUpdateRequest):
    non_nullable_fields = frozenset({"name", "description"})

    name: str | None = Field(default=None)
    description: str | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return _strip_nonblank(value, "name") if value is not None else None


class ProjectCreate(StrictRequest, OptionalIntMixin):
    code: str = Field(..., min_length=1)
    name: str | None = Field(default=None)
    description: str | None = Field(default="")
    workflow_id: int | None = Field(default=None, gt=0, strict=True)
    key_prefixes: list[str]

    @field_validator("code")
    @classmethod
    def _code_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "code")

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return _strip_nonblank(value, "name") if value is not None else None

    @field_validator("key_prefixes", mode="before")
    @classmethod
    def _validate_key_prefixes(cls, value: Any) -> list[str]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("key_prefixes must be a list of strings")
        return [_strip_nonblank(item, "key_prefixes").upper() for item in value]

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


class ProjectUpdate(StrictUpdateRequest, OptionalIntMixin):
    non_nullable_fields = frozenset({"code", "name", "description", "workflow_id", "key_prefixes"})

    code: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    workflow_id: int | None = Field(default=None, gt=0, strict=True)
    key_prefixes: list[str] | None = Field(default=None)

    @field_validator("code", "name")
    @classmethod
    def _identity_not_blank(cls, value: str | None, info: Any) -> str | None:
        return _strip_nonblank(value, info.field_name) if value is not None else None

    @field_validator("key_prefixes", mode="before")
    @classmethod
    def _validate_key_prefixes(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("key_prefixes must be a list of strings")
        return [_strip_nonblank(item, "key_prefixes").upper() for item in value]

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

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "name")

    @field_validator("hermes_profile", mode="before")
    @classmethod
    def _validate_hermes_profile(cls, value: Any) -> str | None:
        profile = str(value or "").strip()
        if not profile:
            return None
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", profile):
            raise ValueError("Hermes profile must match [a-z0-9][a-z0-9_-]*")
        return profile


class AgentUpdate(StrictUpdateRequest):
    non_nullable_fields = frozenset({"name", "description"})

    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    hermes_profile: str | None = Field(default=None, max_length=251)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return _strip_nonblank(value, "name") if value is not None else None

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
    orders: list[_PhaseOrderItem] = Field(min_length=1)


class InstructionCreate(StrictRequest):
    phase_id: int = Field(gt=0, strict=True)
    description: str = Field(..., min_length=1)
    execution_type: Literal["sync", "parallel"] = Field(default="sync")
    skills: list[str] | None = Field(default=None)
    step_num: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "description")

    @field_validator("skills", mode="before")
    @classmethod
    def _validate_skills(cls, value: Any) -> list[str] | None:
        return _normalize_string_list(value, "skills")


class InstructionUpdate(StrictUpdateRequest):
    non_nullable_fields = frozenset({"description", "execution_type"})

    description: str | None = Field(default=None, min_length=1)
    execution_type: Literal["sync", "parallel"] | None = Field(default=None)
    skills: list[str] | None = Field(default=None)

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str | None) -> str | None:
        return _strip_nonblank(value, "description") if value is not None else None

    @field_validator("skills", mode="before")
    @classmethod
    def _validate_skills(cls, value: Any) -> list[str] | None:
        return _normalize_string_list(value, "skills")


class InstructionReorder(StrictRequest):
    instruction_ids: list[int] = Field(...)
