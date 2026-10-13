"""Fixed, operator-configured runtime readback; no request-supplied URLs or proof."""

from urllib.parse import quote, urlsplit

import requests
from pydantic import ValidationError

from project_workflow import config
from project_workflow.domain.pm_execution import RuntimeObservation


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
