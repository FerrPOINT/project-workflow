"""Private lifecycle transport bypasses human SSO, never machine authorization."""

import asyncio
import json
import time
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from project_workflow.domain.identity_deletion import DeletionRequest
from project_workflow.infrastructure.db.identity_deletion import OwnerError, execute
from project_workflow.infrastructure.identity_deletion_auth import authorize
from project_workflow.infrastructure.namespace_auth import unique_object


def _failure(error: OwnerError) -> JSONResponse:
    return JSONResponse({"error": {"code": error.code}}, status_code=error.status,
                        headers={"Cache-Control": "no-store"})


async def _execute(request: Request, operation_id: str, action: str, deadline: float) -> JSONResponse:
    if action not in {"check", "freeze", "release"}:
        raise OwnerError("invalid_identity_deletion_request", 422)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise OwnerError("identity_deletion_body_too_large", 413)
    try:
        command = DeletionRequest.model_validate(json.loads(body, object_pairs_hook=unique_object))
        if command.operation_id != UUID(operation_id):
            raise ValueError("Path/body mismatch")
    except (ValueError, ValidationError, TypeError):
        raise OwnerError("invalid_identity_deletion_request", 422) from None
    authority = await authorize(request.headers.get("authorization"), deadline)
    if authority.issuer != command.identity.issuer:
        raise OwnerError("identity_deletion_access_denied", 403)
    receipt = await asyncio.to_thread(execute, action, command, authority)
    if not authority.current():
        raise OwnerError("identity_deletion_authority_expired", 401)
    return JSONResponse(receipt.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


async def handle(request: Request, operation_id: str, action: str) -> JSONResponse:
    try:
        return await asyncio.wait_for(_execute(request, operation_id, action, time.monotonic() + 9), 9)
    except OwnerError as error:
        return _failure(error)
    except asyncio.TimeoutError:
        return _failure(OwnerError("identity_deletion_storage_unavailable"))
