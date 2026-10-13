"""Stable owner observation of an installed Base namespace, never execution proof."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from project_workflow.domain.base_admission import ExactRef, Sha256
from project_workflow.domain.base_catalog import BASE_CATALOG_SKILLS


def _bounded_database_id(value: str) -> str:
    if int(value) > 2**63 - 1:
        raise ValueError("Database ID exceeds the supported integer range")
    return value


DatabaseId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^[1-9][0-9]*$", max_length=19),
    AfterValidator(_bounded_database_id),
    Field(description="Canonical ASCII decimal database ID in 1..9223372036854775807"),
]


class BaseNamespaceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    binding_schema: Literal["base-sdlc/workflow-binding/v1"] = Field(alias="schema")
    namespace_id: DatabaseId
    namespace_name: ExactRef
    workflow_id: DatabaseId
    workflow_key: ExactRef
    role_key: ExactRef
    profile: ExactRef
    catalog_version: Literal[3, 4]
    catalog_sha256: Sha256
    skills_revision: Literal[
        "4b9b4c9297a13fb28a6ba2039af2f7cb719f2f58", "6e1d190ecd15b772b1066c472f864b8becb3f97a",
    ]
    runtime_ready: Literal[False]

    @model_validator(mode="after")
    def _source_generation(self) -> "BaseNamespaceBinding":
        if self.skills_revision != BASE_CATALOG_SKILLS[self.catalog_version]:
            raise ValueError("Base catalog version and skills revision differ")
        return self


class BaseNamespaceBindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ok: Literal[True]
    binding: BaseNamespaceBinding


class BaseNamespaceBindingError(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ok: Literal[False]
    error_code: Literal["machine-access-denied", "authorization-unavailable", "binding-conflict", "binding-unavailable"]
    error: str


class BaseBindingValidationDetail(BaseModel):
    field: str
    message: str


class BaseBindingInvalidRequest(BaseModel):
    """Existing application validation handler shape, not FastAPI's default body."""

    ok: Literal[False]
    error: str
    details: list[BaseBindingValidationDetail]
