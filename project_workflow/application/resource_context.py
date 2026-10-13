"""Create verified context with immutable identity and original-command readback."""

import asyncio
from uuid import UUID

import httpx
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.resource_context import (
    CreateExecutionContext,
    ExecutionContextReadback,
    ExecutionContextV2,
)
from project_workflow.infrastructure.db.models import ResourceExecutionContext, Workflow, WorkflowMode
from project_workflow.infrastructure.db.session import get_session
from project_workflow.infrastructure.resource_context_reader import OwnerUnavailable, read_owner

CONTEXT_TIMEOUT_SECONDS = 10


def _readback(row: ResourceExecutionContext, identity: UUID) -> ExecutionContextReadback:
    try:
        result = ExecutionContextReadback.model_validate(row.verified_projection)
        if (
            result.id != identity
            or result.request.model_dump(mode="json") != row.request
            or str(result.request.context.operation_id) != row.operation_id
        ):
            raise ValueError("Projection identity mismatch")
        return result
    except (ValidationError, ValueError):
        raise OwnerUnavailable("Invalid execution context projection") from None


def get_context(identity: UUID) -> ExecutionContextReadback:
    with get_session() as session:
        row = session.get(ResourceExecutionContext, str(identity))
        if row is None:
            raise NotFoundError("Execution context not found")
        return _readback(row, identity)


def _replay(identity: UUID, actor: str, request: CreateExecutionContext) -> ExecutionContextReadback | None:
    with get_session() as session:
        row = session.get(ResourceExecutionContext, str(identity))
        if row is None:
            return None
        if row.request != request.model_dump(mode="json") or row.created_by_subject != actor:
            raise ConflictError("Execution context identity or payload conflict")
        return _readback(row, identity)


async def _verify_resources(context: ExecutionContextV2, client: httpx.AsyncClient) -> tuple[UUID, int]:
    task = await read_owner("TRACKER", f"api/v1/namespace-tasks/{context.task.task_id}", context, client=client)
    if (
        task.get("namespace") != context.namespace.model_dump(mode="json")
        or task.get("task_id") != str(context.task.task_id)
        or task.get("tracker_instance_id") != str(context.task.tracker_instance_id)
        or task.get("state") != "active"
    ):
        raise ConflictError("Invalid or archived task context")
    try:
        project = UUID(task["project_id"])
        generation = task["generation"]
        if project.int == 0 or type(generation) is not int or generation <= 0:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise OwnerUnavailable("Invalid Tracker readback") from None
    for repository in context.repositories:
        readback = await read_owner(
            "FORGE", f"api/v1/namespace-repositories/{repository.repository_id}", context, client=client
        )
        if (
            readback.get("namespace") != context.namespace.model_dump(mode="json")
            or readback.get("repository_id") != str(repository.repository_id)
            or readback.get("forge_instance_id") != str(repository.forge_instance_id)
        ):
            raise ConflictError("Invalid repository context")
    return project, generation


async def create_context(identity: UUID, actor: str, request: CreateExecutionContext) -> ExecutionContextReadback:
    if identity.int == 0:
        raise ValueError("Nil execution context identity")
    original = await asyncio.to_thread(_replay, identity, actor, request)
    if original:
        return original
    context = request.context
    try:
        # One command owns its pool; all owner checks share one bounded verification budget.
        async with httpx.AsyncClient(timeout=CONTEXT_TIMEOUT_SECONDS, follow_redirects=False) as client:
            project, generation = await asyncio.wait_for(
                _verify_resources(context, client), CONTEXT_TIMEOUT_SECONDS
            )
    except asyncio.TimeoutError:
        raise OwnerUnavailable("Execution context verification deadline exceeded") from None
    result = ExecutionContextReadback(
        id=identity, request=request, tracker_project_id=project, binding_generation=generation
    )
    return await asyncio.to_thread(_persist_context, identity, actor, request, result)


def _persist_context(
    identity: UUID, actor: str, request: CreateExecutionContext, result: ExecutionContextReadback,
) -> ExecutionContextReadback:
    try:
        with get_session() as session, session.begin():
            profile = session.get(Workflow, request.workflow_id, with_for_update=True)
            mode = session.scalar(
                select(WorkflowMode).where(
                    WorkflowMode.workflow_id == request.workflow_id,
                    WorkflowMode.key == request.mode_key,
                    WorkflowMode.catalog_version == request.catalog_version,
                )
            )
            if profile is None or mode is None or profile.active_catalog_version != request.catalog_version:
                raise ConflictError("Current workflow profile version required")
            session.add(
                ResourceExecutionContext(
                    id=str(identity),
                    operation_id=str(request.context.operation_id),
                    request=request.model_dump(mode="json"),
                    verified_projection=result.model_dump(mode="json"),
                    workflow_id=profile.id,
                    mode_id=mode.id,
                    created_by_subject=actor,
                )
            )
    except IntegrityError:
        original = _replay(identity, actor, request)
        if original:
            return original
        raise ConflictError("Execution context operation already used") from None
    return get_context(identity)
