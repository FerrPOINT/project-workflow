"""Strict PM namespace ownership wire, separate from execution admission."""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, WithJsonSchema, field_validator


def canonical_uuid(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value) is None or value == (
        "00000000-0000-0000-0000-000000000000"
    ):
        raise ValueError("Canonical non-nil UUID required")
    return value


def exact_instance(value: str) -> str:
    if any(character.isspace() or ord(character) < 32 or 127 <= ord(character) <= 159 for character in value):
        raise ValueError("Tracker instance must not contain whitespace or controls")
    return value


UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
UUIDRef = Annotated[str, StringConstraints(strict=True), AfterValidator(canonical_uuid), WithJsonSchema({
    "type": "string", "pattern": UUID_PATTERN, "not": {"const": "00000000-0000-0000-0000-000000000000"},
})]
InstanceRef = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=128), AfterValidator(exact_instance),
    WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 128,
                    "pattern": r"^[^\s\x00-\x1f\x7f-\x9f]+$"}),
]


class NamespaceOwnershipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1]
    tracker_instance_ref: InstanceRef
    tracker_project_ref: UUIDRef

    @field_validator("contract_version", mode="before")
    @classmethod
    def strict_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Integer contract version required")
        return value


class NamespaceOwnershipReadback(NamespaceOwnershipRequest):
    ownership_ref: UUIDRef
    namespace_id: Annotated[int, Field(strict=True, gt=0)]
    authority_issuer: str
    provisioner_subject: UUIDRef
    created_at: datetime


class NamespaceOwnershipResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: Literal[True]
    result: NamespaceOwnershipReadback
