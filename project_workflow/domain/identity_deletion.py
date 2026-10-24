"""Strict Base identity owner protocol v1, never a grant of human authority."""

from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator


class CentralIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: StrictStr = Field(min_length=1, max_length=2048)
    subject: StrictStr = Field(min_length=1, max_length=64)

    @field_validator("subject")
    @classmethod
    def valid_subject(cls, value: str) -> str:
        parsed = UUID(value)
        if not parsed.int:
            raise ValueError("Non-nil identity required")
        return str(parsed)


class DeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1]
    operation_id: UUID
    identity: CentralIdentity
    inventory_revision: UUID

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Exact protocol version required")
        return value

    @field_validator("operation_id", "inventory_revision")
    @classmethod
    def non_nil(cls, value: UUID) -> UUID:
        if not value.int:
            raise ValueError("Non-nil operation required")
        return value


class ReferenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: DeletionRequest
    owner: Literal["project-workflow"] = "project-workflow"
    revision: StrictInt = Field(gt=0)
    reference_count: StrictInt = Field(ge=0)
    fencing_supported: Literal[True] = True


class FreezeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: DeletionRequest
    owner: Literal["project-workflow"] = "project-workflow"
    fence: UUID
    revision: StrictInt = Field(gt=0)
    reference_count: StrictInt = Field(ge=0)


class ReleaseReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request: DeletionRequest
    owner: Literal["project-workflow"] = "project-workflow"
    cancelled: Literal[True] = True


def validate_issuer(value: str) -> str:
    """Validate the configured identity string without normalizing its meaning."""
    url = urlsplit(value)
    if (not value or len(value) > 2048 or value != value.strip()
            or any(char.isspace() or ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
            or url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password
            or url.query or url.fragment or "\\" in value):
        raise ValueError("Invalid trusted identity issuer")
    _ = url.port
    return value
