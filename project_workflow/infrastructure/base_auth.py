"""Registered Base read principals using only issuer-supported service scopes."""

import json
from dataclasses import dataclass

from project_workflow import config
from project_workflow.domain.namespace_ownership import canonical_uuid
from project_workflow.domain.runtime_assignment import MANAGED_ROLE_MODE_SCOPES
from project_workflow.infrastructure import namespace_auth


@dataclass(frozen=True)
class BaseReader:
    subject: str
    role_key: str

    @property
    def kind(self) -> str:
        return "catalog" if self.role_key == "catalog" else "registered-reader"


def authorize_read(authorization: str | None) -> BaseReader:
    """No browser, privileged-human, email, local role-token or wildcard fallback."""
    if not authorization or not authorization.startswith("Bearer sdlc_pat_"):
        raise namespace_auth.NamespaceAuthError(401)
    raw = config.get_settings().PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON
    try:
        if not raw or len(raw.encode("utf-8")) > 8192:
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
    principal, scopes = namespace_auth.introspect(authorization)
    if scopes != ["project-workflow:read"] or principal.subject not in subjects:
        raise namespace_auth.NamespaceAuthError(403)
    return BaseReader(subject=principal.subject, role_key=subjects[principal.subject])
