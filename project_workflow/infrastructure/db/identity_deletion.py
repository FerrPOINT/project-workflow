"""PostgreSQL-only durable owner effects with one guarded lock order."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from project_workflow.domain.identity_deletion import (
    DeletionRequest,
    FreezeReceipt,
    ReferenceSummary,
    ReleaseReceipt,
    validate_issuer,
)
from project_workflow.infrastructure.db.session import DatabaseUnavailable, get_engine

if TYPE_CHECKING:
    from project_workflow.infrastructure.identity_deletion_auth import Authority


class OwnerError(RuntimeError):
    def __init__(self, code: str, status: int = 503):
        self.code, self.status = code, status
        super().__init__(code)


def _current(authority: Authority) -> None:
    # Local import avoids an import cycle with the HTTP adapter's static errors.
    from project_workflow.infrastructure.identity_deletion_auth import Authority
    if not isinstance(authority, Authority) or not authority.current():
        raise OwnerError("identity_deletion_authority_expired", 401)


def _authorize_transaction(connection: Connection, authority: Authority) -> None:
    _current(authority)
    anchor = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
    _current(authority)
    # Sample the remaining original clocks AFTER the DB anchor response. Even
    # network time and a later lock wait can only shorten this fixed DB deadline.
    until = min(anchor + timedelta(seconds=authority.remaining()),
                datetime.fromtimestamp(authority.expires_at, timezone.utc))
    authorization = str(uuid4())
    connection.execute(text("INSERT INTO identity_owner_command_authorizations(authorization_id,valid_until) "
                            "VALUES(:id,:until)"), {"id": authorization, "until": until})
    # PostgreSQL retains the deferred AFTER INSERT event's NEW even after this
    # delete. The COMMIT guard remains queued without accumulating audit/PII rows.
    connection.execute(text("DELETE FROM identity_owner_command_authorizations WHERE authorization_id=:id"),
                       {"id": authorization})
    _current(authority)


def _lock(connection: Connection, authority: Authority) -> None:
    if connection.dialect.name != "postgresql":
        raise OwnerError("identity_deletion_storage_unavailable")
    connection.execute(text("SET LOCAL lock_timeout='8s'"))
    connection.execute(text("SET LOCAL statement_timeout='8s'"))
    _authorize_transaction(connection, authority)
    connection.execute(text("SELECT pg_advisory_xact_lock(714402216003::bigint)"))
    result = connection.execute(text("UPDATE identity_fence_epoch SET revision=revision+1 WHERE singleton=1"))
    if result.rowcount != 1:
        raise OwnerError("identity_fence_epoch_missing")


def _bind(connection: Connection, issuer: str) -> None:
    try:
        validate_issuer(issuer)
    except ValueError:
        raise OwnerError("invalid_identity_legacy_issuer", 422) from None
    old = connection.execute(text("SELECT issuer FROM identity_legacy_issuer WHERE singleton=1")).scalar_one_or_none()
    if old is None:
        connection.execute(text("INSERT INTO identity_legacy_issuer(singleton,issuer) VALUES(1,:issuer)"),
                           {"issuer": issuer})
    elif old != issuer:
        raise OwnerError("identity_legacy_issuer_conflict", 409)


def _count(connection: Connection, request: DeletionRequest) -> int:
    count = 0
    for source in ("pm_namespace_ownership", "resource_execution_contexts"):
        unresolved = connection.execute(text(
            f"SELECT EXISTS(SELECT 1 FROM {source} source, "
            "LATERAL workflow_identity_refs(:source,to_jsonb(source)) r "
            "WHERE NULLIF(btrim(r.issuer),'') IS NULL OR NULLIF(btrim(r.subject),'') IS NULL)"
        ), {"source": source}).scalar_one()
        if unresolved:
            raise OwnerError("identity_legacy_reference_unresolved")
        count += connection.execute(text(
            f"SELECT count(*) FROM {source} source WHERE EXISTS("
            "SELECT 1 FROM workflow_identity_refs(:source,to_jsonb(source)) r "
            "WHERE r.issuer=:issuer AND r.subject=:subject)"
        ), {"source": source, **request.identity.model_dump()}).scalar_one()
    return count


def execute(action: str, request: DeletionRequest, authority: Authority):
    """Commit before ACK; timeout/unknown storage never becomes a zero receipt."""
    from project_workflow.config import get_settings
    settings = get_settings()
    bound = settings.PROJECT_WORKFLOW_IDENTITY_LEGACY_ISSUER
    if not bound or bound != settings.AUTH_ISSUER:
        raise OwnerError("identity_legacy_issuer_unbound")
    _current(authority)
    if authority.issuer != bound:
        raise OwnerError("identity_deletion_access_denied", 403)
    try:
        with get_engine().begin() as connection:
            _lock(connection, authority)
            _current(authority)
            _bind(connection, bound)
            if request.identity.issuer != bound:
                raise OwnerError("identity_legacy_issuer_unbound")
            operation = connection.execute(text(
                "SELECT request,state,fence,revision,reference_count FROM identity_deletion_operations "
                "WHERE operation_id=:id"
            ), {"id": str(request.operation_id)}).mappings().one_or_none()
            wire = request.model_dump(mode="json")
            if operation and operation["request"] != wire:
                raise OwnerError("identity_deletion_operation_conflict", 409)
            result: ReleaseReceipt | FreezeReceipt | ReferenceSummary
            if action == "release":
                if operation is None:
                    connection.execute(text(
                        "INSERT INTO identity_deletion_operations(operation_id,issuer,subject,inventory_revision,"
                        "request,state,revision,reference_count) VALUES(:id,:issuer,:subject,:inventory,"
                        "CAST(:request AS json),'released',nextval('identity_reference_revision'),0)"
                    ), {"id": str(request.operation_id), **request.identity.model_dump(),
                        "inventory": str(request.inventory_revision), "request": json.dumps(wire)})
                else:
                    connection.execute(text("UPDATE identity_deletion_operations SET state='released',fence=NULL "
                                            "WHERE operation_id=:id"), {"id": str(request.operation_id)})
                result = ReleaseReceipt(request=request)
            elif action == "freeze" and operation:
                if operation["state"] != "frozen":
                    raise OwnerError("identity_deletion_operation_conflict", 409)
                result = FreezeReceipt(request=request, fence=operation["fence"], revision=operation["revision"],
                                       reference_count=operation["reference_count"])
            elif action in {"check", "freeze"}:
                count = _count(connection, request)
                revision = connection.execute(text("SELECT nextval('identity_reference_revision')")).scalar_one()
                if action == "check":
                    result = ReferenceSummary(request=request, revision=revision, reference_count=count)
                else:
                    active = connection.execute(text("SELECT 1 FROM identity_deletion_operations "
                        "WHERE issuer=:issuer AND subject=:subject AND state='frozen'"),
                        request.identity.model_dump()).first()
                    if active:
                        raise OwnerError("identity_deletion_operation_conflict", 409)
                    fence = uuid4()
                    connection.execute(text(
                        "INSERT INTO identity_deletion_operations(operation_id,issuer,subject,inventory_revision,"
                        "request,state,fence,revision,reference_count) VALUES(:id,:issuer,:subject,:inventory,"
                        "CAST(:request AS json),'frozen',:fence,:revision,:count)"
                    ), {"id": str(request.operation_id), **request.identity.model_dump(),
                        "inventory": str(request.inventory_revision), "request": json.dumps(wire),
                        "fence": str(fence), "revision": revision, "count": count})
                    result = FreezeReceipt(request=request, fence=fence, revision=revision, reference_count=count)
            else:
                raise OwnerError("invalid_identity_deletion_request", 422)
            _current(authority)
        _current(authority)
        return result
    except (SQLAlchemyError, DatabaseUnavailable):
        raise OwnerError("identity_deletion_storage_unavailable") from None
