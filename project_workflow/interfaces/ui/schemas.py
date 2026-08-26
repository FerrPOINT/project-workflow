"""Pydantic request/response schemas for UI API endpoints."""

from __future__ import annotations

import re
from typing import Annotated, Any, ClassVar, Literal

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
    def _descriptions_must_be_unique(self) -> PhaseUpdate:
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


class ProjectCreate(StrictRequest):
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
            raise ValueError("key_prefixes должен быть массивом строк")
        return [_strip_nonblank(item, "key_prefixes").upper() for item in value]

    @field_validator("key_prefixes", mode="after")
    @classmethod
    def _ensure_prefixes_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("Нужен хотя бы один префикс ключа задачи")
        if len(value) != len(set(value)):
            raise ValueError("Префиксы ключей задач должны быть уникальными")
        return value

    @model_validator(mode="after")
    def _require_key_prefixes(self) -> ProjectCreate:
        if not self.key_prefixes:
            raise ValueError("Нужен хотя бы один префикс ключа задачи")
        return self

    @field_validator("key_prefixes", mode="after")
    @classmethod
    def _validate_prefix_format(cls, value: list[str]) -> list[str]:
        for prefix in value:
            if not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
                raise ValueError(
                    f"Недопустимый префикс '{prefix}': используйте только заглавные латинские буквы и цифры"
                )
            if len(prefix) < 2:
                raise ValueError(f"Префикс '{prefix}' слишком короткий: нужно не менее 2 символов")
        return value


class ProjectUpdate(StrictUpdateRequest):
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
            raise ValueError("key_prefixes должен быть массивом строк")
        return [_strip_nonblank(item, "key_prefixes").upper() for item in value]

    @field_validator("key_prefixes", mode="after")
    @classmethod
    def _validate_prefix_format(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("Нужен хотя бы один префикс ключа задачи")
        if len(value) != len(set(value)):
            raise ValueError("Префиксы ключей задач должны быть уникальными")
        for prefix in value:
            if not re.fullmatch(r"[A-Z][A-Z0-9]*", prefix):
                raise ValueError(
                    f"Недопустимый префикс '{prefix}': используйте только заглавные латинские буквы и цифры"
                )
            if len(prefix) < 2:
                raise ValueError(f"Префикс '{prefix}' слишком короткий: нужно не менее 2 символов")
        return value


class AgentCreate(StrictRequest):
    name: str = Field(..., min_length=1)
    description: str = Field(default="")
    hermes_profile: str | None = Field(default=None, max_length=251, strict=True)

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
            raise ValueError("Профиль Hermes не может быть пустым; для очистки используйте null")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", profile):
            raise ValueError("Профиль Hermes должен соответствовать [a-z0-9][a-z0-9_-]*")
        return profile


class AgentUpdate(StrictUpdateRequest):
    non_nullable_fields = frozenset({"name", "description"})

    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    hermes_profile: str | None = Field(default=None, max_length=251, strict=True)

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
            raise ValueError("Профиль Hermes не может быть пустым; для очистки используйте null")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", profile):
            raise ValueError("Профиль Hermes должен соответствовать [a-z0-9][a-z0-9_-]*")
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
