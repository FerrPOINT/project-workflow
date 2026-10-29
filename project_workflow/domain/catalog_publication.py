"""Explicit text-only publication commands; editor saves are not activation."""

from pydantic import BaseModel, ConfigDict, Field

from project_workflow.domain.base_admission import Sha256


class CatalogDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=1)
    expected_sha256: Sha256
    # Validated against the installed mode/phase structure by the application.
    modes: list[dict] = Field(min_length=1, max_length=2)


class CatalogPublish(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_version: int = Field(ge=1)
    expected_sha256: Sha256
    draft_sha256: Sha256
    operation_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
