"""Registered Base read principals using only issuer-supported service scopes."""

import json
from dataclasses import dataclass

from project_workflow import config
from project_workflow.domain.namespace_ownership import canonical_uuid
from project_workflow.domain.runtime_assignment import MANAGED_ROLE_MODE_SCOPES
from project_workflow.infrastructure import namespace_auth
from project_workflow.infrastructure.platform_namespace import is_personal_token


@dataclass(frozen=True)
class BaseReader:
    subject: str
    role_key: str

    @property
    def kind(self) -> str:
        return "catalog" if self.role_key == "catalog" else "registered-reader"


def registered_subjects() -> dict[str, str]:
    """Deployment registers subjects, never bearer-token values or display names."""
    raw = config.get_settings().PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON
    if not raw:
        return {}
    try:
        if len(raw.encode("utf-8")) > 8192:
            raise ValueError("Reader registry unavailable")
        subjects = json.loads(raw, object_pairs_hook=namespace_auth.unique_object)
        if not isinstance(subjects, dict) or not subjects or any(
            not isinstance(subject, str) or canonical_uuid(subject) != subject
            or not isinstance(role, str) or role not in {*MANAGED_ROLE_MODE_SCOPES, "catalog"}
            for subject, role in subjects.items()
        ):
            raise ValueError("Invalid reader registry")
    except (ValueError, TypeError):
        raise namespace_auth.NamespaceAuthError(503) from None
    return subjects


def authorize_read(authorization: str | None) -> BaseReader:
    """No browser, privileged-human, email, local role-token or wildcard fallback."""
    if not authorization or not (authorization.startswith("Bearer ") and is_personal_token(authorization[7:])):
        raise namespace_auth.NamespaceAuthError(401)
    # Validate configuration before making the issuer request, as before.
    subjects = registered_subjects()
    if not subjects:
        raise namespace_auth.NamespaceAuthError(503)
    principal, scopes = namespace_auth.introspect(authorization)
    role = subjects.get(principal.subject)
    if scopes != ["project-workflow:read"] or role is None:
        raise namespace_auth.NamespaceAuthError(403)
    return BaseReader(subject=principal.subject, role_key=role)
