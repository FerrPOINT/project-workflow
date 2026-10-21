"""Fixed, operator-configured runtime readback; no request-supplied URLs or proof."""

from typing import TYPE_CHECKING
from urllib.parse import quote, urlsplit

import requests
from pydantic import ValidationError

from project_workflow import config
from project_workflow.domain.pm_execution import RuntimeObservation

if TYPE_CHECKING:
    from project_workflow.application.pm_bootstrap import BootstrapProof, BootstrapRetry


class ReadbackUnavailable(RuntimeError):
    pass


def readback_configured() -> bool:
    settings = config.get_settings()
    url = urlsplit(settings.PROJECT_WORKFLOW_PM_READBACK_URL)
    return bool(
        url.scheme in {"http", "https"} and url.netloc and not url.username and not url.password
        and not url.query and not url.fragment and len(settings.PROJECT_WORKFLOW_PM_READBACK_TOKEN) >= 32
    )


def observe_run(session_run_id: str) -> RuntimeObservation:
    if not readback_configured():
        raise ReadbackUnavailable("PM runtime readback capability is unavailable")
    settings = config.get_settings()
    try:
        with requests.Session() as client:
            client.trust_env = False
            response = client.get(
                settings.PROJECT_WORKFLOW_PM_READBACK_URL.rstrip("/") + "/" + quote(session_run_id, safe=""),
                headers={"Authorization": f"Bearer {settings.PROJECT_WORKFLOW_PM_READBACK_TOKEN}"},
                timeout=(3, 10), allow_redirects=False,
            )
        if response.status_code != 200:
            raise ReadbackUnavailable("Runtime acceptance is unknown; read back the same run before retry")
        return RuntimeObservation.model_validate(response.json())
    except (requests.RequestException, ValueError, ValidationError):
        raise ReadbackUnavailable("Runtime acceptance is unknown; read back the same run before retry") from None


def bootstrap_proof(request: "BootstrapRetry") -> "BootstrapProof":
    """Post-renew permit from Fleet's durable attempt, not the expired-run witness."""
    from project_workflow.application.pm_bootstrap import BootstrapProof

    if not readback_configured():
        raise ReadbackUnavailable("PM bootstrap readback capability is unavailable")
    settings = config.get_settings()
    url = urlsplit(settings.PROJECT_WORKFLOW_PM_READBACK_URL)._replace(
        path="/internal/runtime/v1/pm/bootstrap-retries/"
             + quote(request.bootstrap_attempt_ref, safe="") + "/workflow-proof",
        query="", fragment="",
    ).geturl()
    try:
        with requests.Session() as client:
            client.trust_env = False
            response = client.get(
                url, headers={"Authorization": f"Bearer {settings.PROJECT_WORKFLOW_PM_READBACK_TOKEN}"},
                timeout=(3, 10), allow_redirects=False,
            )
        if response.status_code != 200:
            raise ReadbackUnavailable("Post-renew bootstrap authority is unknown")
        return BootstrapProof.model_validate(response.json())
    except (requests.RequestException, ValueError, ValidationError):
        raise ReadbackUnavailable("Post-renew bootstrap authority is unknown") from None
