"""Fresh coordinator PAT proof, retaining its original wall and monotonic lifetime."""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from project_workflow.config import get_settings
from project_workflow.domain.identity_deletion import validate_issuer
from project_workflow.infrastructure.db.identity_deletion import OwnerError
from project_workflow.infrastructure.namespace_auth import _root, unique_object
from project_workflow.infrastructure.platform_auth import confirm_access
from project_workflow.infrastructure.platform_namespace import is_personal_token


class _Introspection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sub: StrictStr
    email: StrictStr
    display_name: StrictStr
    scopes: list[StrictStr] = Field(max_length=100)
    observed_at: datetime
    expires_at: datetime
    # Current Auth always emits role; include_lifetime also emits subject_role.
    # Neither an absent kind nor a contradictory pair establishes authority.
    role: Literal["user", "admin", "service_account"]
    subject_role: Literal["user", "admin", "service_account"]
    application_access: dict[StrictStr, object] | None = None


@dataclass(frozen=True)
class Authority:
    issuer: str
    deadline: float
    observed_at: float
    expires_at: float

    def current(self) -> bool:
        now = time.time()
        return time.monotonic() < self.deadline and self.observed_at - 1 <= now < self.expires_at

    def remaining(self) -> float:
        """Intersect the original clocks; querying the DB never renews this permit."""
        return max(0.0, min(self.deadline - time.monotonic(), self.expires_at - time.time()))


async def authorize(authorization: str | None, overall_deadline: float) -> Authority:
    import json
    settings = get_settings()
    try:
        root = _root(settings.AUTH_INTERNAL_BASE_URL)
        issuer = validate_issuer(settings.AUTH_ISSUER)
        registered = {str(UUID(item.strip())) for item in
                      settings.PROJECT_WORKFLOW_IDENTITY_DELETION_COORDINATOR_SUBJECTS.split(",") if item.strip()}
    except ValueError:
        raise OwnerError("identity_deletion_authorization_unavailable") from None
    if not authorization or not authorization.startswith("Bearer "):
        raise OwnerError("identity_deletion_access_denied", 401)
    token = authorization[7:]
    if (not is_personal_token(token) or len(token) > 4096
            or any(not 33 <= ord(char) <= 126 for char in token)):
        raise OwnerError("identity_deletion_access_denied", 403)
    started = time.monotonic()
    wall_started = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
            async with client.stream("GET", root + "/auth/tokens/introspect?include_lifetime=true", headers={
                "Authorization": authorization, "Accept-Encoding": "identity", "Cache-Control": "no-store",
            }) as response:
                if response.status_code == 401:
                    raise OwnerError("identity_deletion_access_denied", 401)
                if response.status_code != 200 or response.headers.get("Content-Encoding", "identity") != "identity":
                    raise OwnerError("identity_deletion_authorization_unavailable")
                body = bytearray()
                async for chunk in response.aiter_bytes(1024):
                    body.extend(chunk)
                    if len(body) > 16384 or time.monotonic() - started > 5:
                        raise OwnerError("identity_deletion_authorization_unavailable")
                proof = _Introspection.model_validate(json.loads(body, object_pairs_hook=unique_object))
        if proof.role != proof.subject_role:
            raise ValueError("Inconsistent canonical principal kind")
        if proof.application_access is not None:
            application = confirm_access(proof.application_access, issuer=issuer, subject=proof.sub,
                                         started=started, wall_started=wall_started)
            if application.role != proof.role:
                raise ValueError("Inconsistent canonical application principal")
        if (str(UUID(proof.sub)) not in registered or proof.subject_role != "service_account"
                or "project-workflow:identity-lifecycle" not in proof.scopes
                or proof.observed_at.tzinfo is None or proof.expires_at.tzinfo is None):
            raise OwnerError("identity_deletion_access_denied", 403)
        observed, expires = proof.observed_at.timestamp(), proof.expires_at.timestamp()
        authority = Authority(issuer, min(overall_deadline, started + expires - observed,
                                          started + 60), observed, expires)
        if not authority.current() or proof.observed_at > datetime.now(timezone.utc):
            raise OwnerError("identity_deletion_authority_expired", 401)
        return authority
    except (httpx.HTTPError, ValueError, ValidationError, TypeError):
        raise OwnerError("identity_deletion_authorization_unavailable") from None
