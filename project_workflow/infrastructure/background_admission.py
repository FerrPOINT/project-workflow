"""Read Fleet's saved launch through a dedicated server credential, without Tracker."""
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from project_workflow import config
from project_workflow.domain.base_admission import Sha256
from project_workflow.domain.namespace_ownership import UUIDRef
from project_workflow.infrastructure import namespace_auth


class BackgroundContext(BaseModel):
    # Fleet owns the other context fields (prompts, source grants, config snapshot).
    model_config = ConfigDict(extra="allow", strict=True)
    machine_subject: UUIDRef
    namespace_id: str = Field(pattern=r"^[1-9][0-9]*$")
    workflow_id: str = Field(pattern=r"^[1-9][0-9]*$")
    catalog_version: int = Field(gt=0)
    config_revision: int = Field(gt=0)
    profession: Literal["BUG_SEARCHER", "REFACTORER"]


class RunIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: UUIDRef
    project_id: UUIDRef
    process_id: UUIDRef
    session_id: UUIDRef
    agent_id: UUIDRef
    workflow_revision: Sha256
    context: BackgroundContext

    def identity(self) -> dict:
        return self.model_dump(mode="json", include=set(RunIdentity.model_fields))


class RunAdmission(RunIdentity):
    state: Literal["preparing", "queued", "running", "completed", "incomplete", "cancelled", "failed"]
    sources: list[dict]


def read(run_id: str, authorization: str | None, *, write: bool, namespace_id: int,
         active: bool = True) -> RunAdmission:
    principal, scopes = namespace_auth.introspect(authorization, require_service_account=True)
    required = "project-workflow:background:write" if write else "project-workflow:background:read"
    if (required not in scopes or len(scopes) != len(set(scopes))
            or not set(scopes) <= {"project-workflow:background:read", "project-workflow:background:write"}):
        raise namespace_auth.NamespaceAuthError(403)
    settings = config.get_settings()
    try:
        root = namespace_auth._root(settings.PROJECT_WORKFLOW_BACKGROUND_FLEET_URL)
        token = settings.PROJECT_WORKFLOW_BACKGROUND_READER_TOKEN
        if not token or any(character.isspace() for character in token):
            raise ValueError("Missing background reader credential")
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
            response = client.get(f"{root}/internal/background/v1/runs/{run_id}",
                                  headers={"Authorization": f"Bearer {token}", "Cache-Control": "no-cache, no-store"})
        if response.status_code in {401, 403, 404}:
            raise namespace_auth.NamespaceAuthError(403)
        if response.status_code != 200:
            raise ValueError("Fleet admission unavailable")
        admission = RunAdmission.model_validate(response.json())
    except (httpx.HTTPError, ValueError, TypeError):
        raise namespace_auth.NamespaceAuthError(503) from None
    if (admission.run_id != run_id or admission.context.machine_subject != principal.subject
            or admission.context.namespace_id != str(namespace_id)
            or active and admission.state not in {"queued", "running"}):
        raise namespace_auth.NamespaceAuthError(403)
    return admission
