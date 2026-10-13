"""Versioned human routes; private runtime credentials remain on their own bridge."""

from uuid import UUID

from fastapi import HTTPException, Request

from project_workflow.application.resource_context import create_context, get_context
from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.resource_context import CreateExecutionContext, ExecutionContextReadback
from project_workflow.infrastructure.resource_context_reader import OwnerUnavailable


def read(identity: UUID, request: Request) -> ExecutionContextReadback:
    _actor(request)
    try:
        return get_context(identity)
    except NotFoundError:
        raise HTTPException(404, "Execution context not found") from None
    except OwnerUnavailable:
        raise HTTPException(503, "Context projection unavailable") from None


def _actor(request: Request) -> str:
    subject = getattr(request.state, "central_subject", None)
    if not isinstance(subject, str) or not subject:
        raise HTTPException(401, "Verified central human identity required")
    return subject


async def bind(identity: UUID, request: Request, input: CreateExecutionContext) -> ExecutionContextReadback:
    try:
        return await create_context(identity, _actor(request), input)
    except (ConflictError, ValueError) as error:
        raise HTTPException(409, str(error)) from None
    except OwnerUnavailable:
        raise HTTPException(503, "Context owner reader unavailable") from None
