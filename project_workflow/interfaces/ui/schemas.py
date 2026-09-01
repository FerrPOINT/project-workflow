"""Pydantic request/response schemas for UI API endpoints."""

from __future__ import annotations

import re
from typing import Annotated, Any, ClassVar, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from project_workflow.domain.namespace import normalize_namespace_cli_command
from project_workflow.domain.project_theme import (
    DEFAULT_PROJECT_COLOR,
    DEFAULT_PROJECT_ICON,
    normalize_theme_color,
    normalize_theme_icon,
)


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
            raise ValueError(f"Поля не могут быть null: {', '.join(invalid)}")
        return value


def _strip_nonblank(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"Поле {field_name} не может быть пустым")
    return normalized


def _normalize_string_list(value: Any, field_name: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"Поле {field_name} должно быть массивом строк или null")
    normalized = [_strip_nonblank(item, field_name) for item in value]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"Поле {field_name} должно содержать уникальные значения")
    return normalized


class _PhaseOrderItem(StrictRequest):
    phase_id: int = Field(gt=0, strict=True)
    phase_order: int = Field(gt=0, strict=True)
    workflow_id: int | None = Field(default=None, gt=0, strict=True)


class PhaseCreate(StrictRequest):
    workflow_id: int = Field(gt=0, strict=True, description="Parent workflow id")
    phase_order: int | None = Field(default=None, gt=0, strict=True, description="1-based insertion position")
    insert_after: int | None = Field(default=None, ge=0, strict=True, description="Insert after this 0-based index")
    name: str = Field(default="Новая фаза")
    description: str = Field(default="")
    execution_type: Literal["sync", "parallel"] = Field(default="sync")
    agent_id: int | None = Field(default=None, gt=0, strict=True)
    code: str | None = Field(default=None)
    parallel_with_phase_id: int | None = Field(default=None, gt=0, strict=True)
    rollback_target_phase_id: int | None = Field(default=None, gt=0, strict=True)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "name")

    @field_validator("code")
    @classmethod
    def _code_not_blank(cls, value: str | None) -> str | None:
        return _strip_nonblank(value, "code") if value is not None else None

    @model_validator(mode="after")
    def _resolve_insert_after(self) -> PhaseCreate:
        if self.insert_after is None and self.phase_order is None:
            raise ValueError("Необходимо указать phase_order или insert_after")
        if self.insert_after is None:
            return self
        resolved_order = self.insert_after + 1
        if self.phase_order is not None and self.phase_order != resolved_order:
            raise ValueError("phase_order противоречит insert_after")
        self.phase_order = resolved_order
        return self


class PhaseInstructionItem(StrictRequest):
    id: int | None = Field(gt=0, strict=True)
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
    id: int | None = Field(gt=0, strict=True)
    description: str

    @field_validator("description")
    @classmethod
    def _description_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "description")


class PhaseUpdate(StrictUpdateRequest):
    non_nullable_fields = frozenset({"name", "execution_type", "instructions", "checks", "evidence"})

    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    parallel_with_phase_id: int | None = Field(default=None, gt=0, strict=True)
    rollback_target_phase_id: int | None = Field(default=None, gt=0, strict=True)
    agent_id: int | None = Field(default=None, gt=0, strict=True)
    execution_type: Literal["sync", "parallel"] | None = Field(default=None)
    instructions: list[PhaseInstructionItem] | None = Field(default=None)
    checks: list[PhaseTextItem] | None = Field(default=None)
    evidence: list[PhaseTextItem] | None = Field(default=None)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return _strip_nonblank(value, "name") if value is not None else None

    @model_validator(mode="after")
    def _nested_items_must_be_unique(self) -> PhaseUpdate:
        for field_name in ("instructions", "checks", "evidence"):
            items = getattr(self, field_name)
            if items is None:
                continue
            ids = [item.id for item in items if item.id is not None]
            if len(ids) != len(set(ids)):
                raise ValueError(f"Идентификаторы в поле {field_name} должны быть уникальными")
        for field_name in ("checks", "evidence"):
            items = getattr(self, field_name)
            if items is None:
                continue
            normalized = [item.description.casefold() for item in items]
            if len(normalized) != len(set(normalized)):
                raise ValueError(f"Описания в поле {field_name} должны быть уникальными")
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


class NamespaceCreate(StrictRequest):
    name: str
    description: str | None = Field(default="")
    workflow_id: int = Field(gt=0, strict=True)
    theme_icon: str = Field(default=DEFAULT_PROJECT_ICON)
    theme_color: str = Field(default=DEFAULT_PROJECT_COLOR)
    cli_command: str = Field(..., min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "name")

    @field_validator("theme_icon")
    @classmethod
    def _theme_icon_valid(cls, value: str) -> str:
        return normalize_theme_icon(value)

    @field_validator("theme_color")
    @classmethod
    def _theme_color_valid(cls, value: str) -> str:
        return normalize_theme_color(value)

    @field_validator("cli_command")
    @classmethod
    def _cli_command_valid(cls, value: str) -> str:
        return normalize_namespace_cli_command(value)


class NamespaceUpdate(StrictUpdateRequest):
    non_nullable_fields = frozenset({"name", "description", "workflow_id", "theme_icon", "theme_color", "cli_command"})

    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    workflow_id: int | None = Field(default=None, gt=0, strict=True)
    theme_icon: str | None = Field(default=None)
    theme_color: str | None = Field(default=None)
    cli_command: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return _strip_nonblank(value, "name") if value is not None else None

    @field_validator("theme_icon")
    @classmethod
    def _theme_icon_valid(cls, value: str | None) -> str | None:
        return normalize_theme_icon(value) if value is not None else None

    @field_validator("theme_color")
    @classmethod
    def _theme_color_valid(cls, value: str | None) -> str | None:
        return normalize_theme_color(value) if value is not None else None

    @field_validator("cli_command")
    @classmethod
    def _cli_command_valid(cls, value: str | None) -> str | None:
        return normalize_namespace_cli_command(value) if value is not None else None


class AgentCreate(StrictRequest):
    name: str = Field(..., min_length=1)
    description: str = Field(default="")
    hermes_profile: str | None = Field(
        default=None,
        max_length=251,
        strict=True,
        validation_alias=AliasChoices("hermes_profile", "launch_profile"),
    )

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "name")

    @field_validator("hermes_profile")
    @classmethod
    def _validate_hermes_profile(cls, value: str | None) -> str | None:
        if value is None:
            return None
        profile = value.strip()
        if not profile:
            raise ValueError("Ключ запуска не может быть пустым; для очистки используйте null")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", profile):
            raise ValueError("Ключ запуска должен соответствовать [a-z0-9][a-z0-9_-]*")
        return profile


class AgentUpdate(StrictUpdateRequest):
    non_nullable_fields = frozenset({"name", "description"})

    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    hermes_profile: str | None = Field(
        default=None,
        max_length=251,
        strict=True,
        validation_alias=AliasChoices("hermes_profile", "launch_profile"),
    )

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str | None) -> str | None:
        return _strip_nonblank(value, "name") if value is not None else None

    @field_validator("hermes_profile")
    @classmethod
    def _validate_hermes_profile(cls, value: str | None) -> str | None:
        if value is None:
            return None
        profile = value.strip()
        if not profile:
            raise ValueError("Ключ запуска не может быть пустым; для очистки используйте null")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", profile):
            raise ValueError("Ключ запуска должен соответствовать [a-z0-9][a-z0-9_-]*")
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
    instruction_ids: list[Annotated[int, Field(gt=0, strict=True)]] = Field(min_length=1)

    @field_validator("instruction_ids")
    @classmethod
    def _instruction_ids_unique(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("instruction_ids должен содержать уникальные значения")
        return value
