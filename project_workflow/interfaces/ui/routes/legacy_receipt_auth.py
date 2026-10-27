"""Read-only authentication of retained PM receipts, never an execution path."""

import hmac
from typing import Any

from project_workflow import config
from project_workflow.application.pm_execution import PMExecutionService


def scope_matches(
    identity: dict[str, Any], run_ref: str, binding_ref: str, fence: int,
    session_run_id: str, token: str | None,
) -> bool:
    secret = config.get_settings().PROJECT_WORKFLOW_PM_SCOPE_SECRET
    if len(secret) < 32 or not isinstance(token, str):
        return False
    expected = PMExecutionService.scoped_token({
        "identity": identity, "hermes_run_ref": run_ref, "binding_ref": binding_ref, "fence": fence,
        "session_run_id": session_run_id,
    }, secret)
    return hmac.compare_digest(token.encode(), expected.encode())
