"""Real rendered views retain working navigation while exposing configuration only to admin."""

import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_workflow.config import Settings
from project_workflow.infrastructure.platform_auth import human_access
from project_workflow.interfaces.ui import sso
from project_workflow.interfaces.ui.routes import pages


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.items = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.items.append((tag, dict(attrs)))

    def has_id(self, value):
        return any(attrs.get("id") == value for _, attrs in self.items)

    def invokes(self, prefix):
        return any(attrs.get("onclick", "").startswith(prefix) for _, attrs in self.items)


@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("view", ["workflows", "namespaces", "phase"])
def test_rendered_configuration_controls_follow_current_central_role(monkeypatch, role, view):
    from project_workflow.infrastructure.db import schema
    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    uow = SAUnitOfWork()
    schema.ensure_phase_catalog(uow)
    uow.close()
    settings = Settings(AUTH_ISSUER="https://auth.fixture.invalid")
    monkeypatch.setattr(sso, "get_settings", lambda: settings)
    now = datetime.now(timezone.utc)
    identity = {"role": "admin", "application_access": {
        "schema_version": 1, "issuer": settings.AUTH_ISSUER, "subject": "fixture-human",
        "role": role, "applications": ["project-workflow"], "revision": 1, "enforced": True,
        "observed_at": now.isoformat(), "expires_at": (now + timedelta(seconds=60)).isoformat(),
    }}
    access = human_access(identity, issuer=settings.AUTH_ISSUER, subject="fixture-human",
                          started=time.monotonic(), wall_started=now, require_proof=True)
    app = FastAPI()

    @app.middleware("http")
    async def trusted_identity_fixture(request, call_next):
        request.state.central_access = access
        return await call_next(request)

    app.get("/workflows")(pages.workflows_page)
    app.get("/namespaces")(pages.namespace_page)
    app.get("/phase/{phase_id}")(pages.phase_detail)
    path = "/phase/1" if view == "phase" else "/" + view
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 200
    elements = Elements(response.text)
    administrative = role == "admin"
    if view == "workflows":
        assert elements.has_id("workflowForm") == administrative
        assert elements.has_id("newWorkflowButton") == administrative
        assert elements.invokes("addPhaseAfter(") == administrative
        assert elements.has_id("phasesTimeline")
        assert elements.invokes("selectWorkflow(")
    elif view == "namespaces":
        assert elements.has_id("namespaceForm") == administrative
        assert elements.has_id("namespaceCreateLink") == administrative
        assert elements.has_id("professionSummary") != administrative
        assert elements.invokes("selectNamespace(")
    else:
        assert elements.has_id("phaseSaveEditor") == administrative
        assert elements.invokes("addInstructionLast(") == administrative
        assert any("data-field" in attrs for _, attrs in elements.items) == administrative
        assert elements.has_id("phase-instructions")
        assert elements.has_id("phaseSectionSelect")
        assert "Инструкции" in response.text


def test_missing_or_expired_central_authority_cannot_render_administration(monkeypatch):
    from starlette.requests import Request

    from project_workflow.infrastructure.platform_auth import HumanAccess

    monkeypatch.setattr(sso, "get_settings", lambda: Settings(AUTH_ISSUER="https://auth.fixture.invalid"))
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    assert not sso.can_administer(request)
    request.state.central_access = HumanAccess("admin", None, time.monotonic() - 1)
    assert not sso.can_administer(request)
