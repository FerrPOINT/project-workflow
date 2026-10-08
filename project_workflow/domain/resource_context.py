"""PDLC context v2, independent from legacy CLI namespaces and global profiles."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def non_nil_ids(self):
        if any(isinstance(value, UUID) and value.int == 0 for value in self.__dict__.values()):
            raise ValueError("Nil resource identity")
        return self


class NamespaceRef(ReferenceModel):
    registry_instance_id: UUID
    namespace_id: UUID


class TaskRef(ReferenceModel):
    tracker_instance_id: UUID
    task_id: UUID


class RepositoryRef(ReferenceModel):
    forge_instance_id: UUID
    repository_id: UUID


class ExecutionContextV2(ReferenceModel):
    schema_version: Literal[2]
    operation_id: UUID
    namespace: NamespaceRef
    task: TaskRef
    repositories: list[RepositoryRef] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_repositories(self):
        refs = [(item.forge_instance_id, item.repository_id) for item in self.repositories]
        if len(refs) != len(set(refs)):
            raise ValueError("Duplicate repository identity")
        return self


class CreateExecutionContext(ReferenceModel):
    context: ExecutionContextV2
    workflow_id: int = Field(gt=0, strict=True)
    catalog_version: int = Field(gt=0, strict=True)
    mode_key: str = Field(min_length=1, max_length=128)


class ExecutionContextReadback(ReferenceModel):
    id: UUID
    request: CreateExecutionContext
    tracker_project_id: UUID
    binding_generation: int = Field(gt=0, strict=True)
    runtime_ready: Literal[False] = False
    dispatch_allowed: Literal[False] = False
    adapter_version: Literal["namespace-context-v2/foundation-v1-disabled"] = (
        "namespace-context-v2/foundation-v1-disabled"
    )
