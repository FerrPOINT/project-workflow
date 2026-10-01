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
from project_workflow.domain.runtime_assignment import MAX_WORK_ITEM_REVISION, normalize_role_key


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


class StepRequest(StrictRequest):
    """Legacy human step payload used by the two-command CLI surface."""

    task: str = Field(min_length=1, max_length=128)
    report: str | None = Field(default=None, max_length=32_000)

    @field_validator("task")
    @classmethod
    def _task_not_blank(cls, value: str) -> str:
        return _strip_nonblank(value, "task")

    @field_validator("report")
    @classmethod
    def _report_not_blank(cls, value: str | None) -> str | None:
        return _strip_nonblank(value, "report") if value is not None else None


class RuntimeStepRequest(StepRequest):
    """One private Supervisor step fenced to an immutable Business assignment."""

    step_operation_key: str = Field(min_length=1, max_length=128)
    assignment_revision: int = Field(gt=0, strict=True)
    assignment_ref: str = Field(min_length=1, max_length=512)
    binding_ref: str = Field(min_length=1, max_length=512)
    hermes_run_ref: str = Field(min_length=1, max_length=512)
    mode_key: str = Field(min_length=1, max_length=128)
    cycle_number: int = Field(ge=0, strict=True)
    attempt_number: int = Field(gt=0, strict=True)
    expected_phase_code: str = Field(min_length=1, max_length=128)
    expected_status: Literal["active", "blocked"]

    @field_validator(
        "assignment_ref",
        "binding_ref",
        "hermes_run_ref",
        "step_operation_key",
        "mode_key",
        "expected_phase_code",
    )
    @classmethod
    def _fence_text_not_blank(cls, value: str, info: Any) -> str:
        return _strip_nonblank(value, info.field_name)


class ExactInputRef(StrictRequest):
    """One immutable external input snapshot selected by Business."""

    kind: str = Field(min_length=1, max_length=128)
    ref: str = Field(min_length=1, max_length=1_024)
    revision: str | None = Field(default=None, min_length=1, max_length=256)
    hash: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("kind", "ref", "revision", "hash")
    @classmethod
    def _input_ref_text_not_blank(cls, value: str | None, info: Any) -> str | None:
        return _strip_nonblank(value, info.field_name) if value is not None else None


class RuntimeAssignmentRequest(StrictRequest):
    """Business-owned persisted assignment accepted only on the role-token bridge."""

    task: str = Field(min_length=1, max_length=128)
    role_key: str = Field(min_length=2, max_length=32)
    workflow_key: str = Field(min_length=1, max_length=128)
    mode_key: str = Field(min_length=1, max_length=128)
    execution_scope: Literal["business", "delivery", "aggregate"]
    stage_key: str = Field(min_length=1, max_length=64)
    cycle_number: int = Field(ge=0, strict=True)
    attempt_number: int = Field(gt=0, strict=True)
    operation_key: str = Field(min_length=1, max_length=128)
    business_task_ref: str = Field(min_length=1, max_length=512)
    root_task_ref: str = Field(min_length=1, max_length=512)
    work_item_ref: str = Field(min_length=1, max_length=512)
    work_item_revision: int = Field(ge=0, le=MAX_WORK_ITEM_REVISION, strict=True)
    queue_item_ref: str = Field(min_length=1, max_length=512)
    task_workspace_ref: str = Field(min_length=1, max_length=512)
    workspace_revision: int = Field(gt=0, strict=True)
    tech_execution_workspace_ref: str | None = Field(default=None, min_length=1, max_length=512)
    tech_execution_attempt_ref: str | None = Field(default=None, min_length=1, max_length=512)
    decomposition_revision_ref: str = Field(min_length=1, max_length=512)
    stage_revision: str = Field(min_length=1, max_length=128)
    assignment_ref: str = Field(min_length=1, max_length=512)
    workspace_generation: int = Field(ge=0, strict=True)
    lease_generation: int = Field(ge=0, strict=True)
    exact_input_refs: list[ExactInputRef] = Field(max_length=128)
    expected_revision: int = Field(ge=0, strict=True)
    expected_status: Literal["missing", "active", "done", "blocked"]
    expected_mode_key: str | None = Field(default=None, min_length=1, max_length=128)
    expected_cycle_number: int | None = Field(default=None, ge=0, strict=True)

    @field_validator(
        "task",
        "workflow_key",
        "mode_key",
        "stage_key",
        "operation_key",
        "business_task_ref",
        "root_task_ref",
        "work_item_ref",
        "queue_item_ref",
        "task_workspace_ref",
        "tech_execution_workspace_ref",
        "tech_execution_attempt_ref",
        "decomposition_revision_ref",
        "stage_revision",
        "assignment_ref",
        "expected_mode_key",
    )
    @classmethod
    def _assignment_text_not_blank(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _strip_nonblank(value, info.field_name)

    @field_validator("role_key")
    @classmethod
    def _assignment_role_key_valid(cls, value: str) -> str:
        return normalize_role_key(value)

    @field_validator("mode_key")
    @classmethod
    def _assignment_key_valid(cls, value: str) -> str:
        if re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value) is None:
            raise ValueError("mode_key должен соответствовать [a-z0-9][a-z0-9._-]*")
        return value

    @model_validator(mode="after")
    def _unique_input_refs(self) -> RuntimeAssignmentRequest:
        identities = [
            (item.kind, item.ref, item.revision or "", item.hash or "")
            for item in self.exact_input_refs
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("exact_input_refs не должен содержать дубликаты")
        return self


class RuntimeBindRequest(StrictRequest):
    """Attach the real Hermes run to one already accepted Business assignment."""

    task: str = Field(min_length=1, max_length=128)
    bind_operation_key: str = Field(min_length=1, max_length=128)
    assignment_operation_key: str = Field(min_length=1, max_length=128)
    assignment_revision: int = Field(gt=0, strict=True)
    assignment_ref: str = Field(min_length=1, max_length=512)
    binding_ref: str = Field(min_length=1, max_length=512)
    hermes_run_ref: str = Field(min_length=1, max_length=512)
    mode_key: str = Field(min_length=1, max_length=128)
    cycle_number: int = Field(ge=0, strict=True)
    attempt_number: int = Field(gt=0, strict=True)
    expected_binding_state: Literal["unbound", "legacy_bound"]

    @field_validator(
        "task",
        "bind_operation_key",
        "assignment_operation_key",
        "assignment_ref",
        "binding_ref",
        "hermes_run_ref",
        "mode_key",
    )
    @classmethod
    def _bind_text_not_blank(cls, value: str, info: Any) -> str:
        return _strip_nonblank(value, info.field_name)

    @field_validator("mode_key")
    @classmethod
    def _bind_mode_key_valid(cls, value: str) -> str:
        if re.fullmatch(r"[a-z0-9][a-z0-9._-]*", value) is None:
            raise ValueError("mode_key должен соответствовать [a-z0-9][a-z0-9._-]*")
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
    mode_id: int | None = Field(default=None, gt=0, strict=True, description="Parent workflow mode id")
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
