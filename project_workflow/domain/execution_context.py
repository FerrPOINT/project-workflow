"""Explicit project context v3; v2 and profession namespaces retain their old meanings."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from project_workflow.domain.resource_context import ReferenceModel, RepositoryRef, TaskRef


class SpaceRef(ReferenceModel):
    registry_instance_id: UUID
    space_id: UUID


class ProjectRef(ReferenceModel):
    tracker_instance_id: UUID
    project_id: UUID


class ExecutionContextV3(ReferenceModel):
    schema_version: Literal[3]
    operation_id: UUID
    project: ProjectRef
    space: SpaceRef | None = None
    task: TaskRef | None = None
    repositories: tuple[RepositoryRef, ...] = Field(max_length=100)

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int:
            raise ValueError("Execution context version must be an integer")
        return value

    @model_validator(mode="after")
    def resource_identities(self):
        if self.task is not None and self.task.tracker_instance_id != self.project.tracker_instance_id:
            raise ValueError("Task and project must belong to the same Tracker instance")
        refs = [(item.forge_instance_id, item.repository_id) for item in self.repositories]
        if len(refs) != len(set(refs)):
            raise ValueError("Duplicate repository identity")
        return self

    def require_wiki_space(self) -> SpaceRef:
        """Wiki operations must name their space; never derive one from a project."""
        if self.space is None:
            raise ValueError("Explicit Wiki space required")
        return self.space
