"""Real rendered views retain working navigation while exposing configuration only to admin."""

import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.config import Settings
from project_workflow.infrastructure.platform_auth import human_access
from project_workflow.interfaces.ui import sso
from project_workflow.interfaces.ui.routes import pages


@pytest.fixture(autouse=True)
def platform_mode(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.fixture.invalid")
    config.get_settings.cache_clear()


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
    settings = Settings(PROJECT_WORKFLOW_MODE="platform", AUTH_ISSUER="https://auth.fixture.invalid")
    monkeypatch.setattr(sso, "get_settings", lambda: settings)
    now = datetime.now(timezone.utc)
    identity = {"role": role, "application_access": {"role": "admin"}}
    access = human_access(identity, issuer=settings.AUTH_ISSUER, subject="fixture-human",
                          started=time.monotonic(), wall_started=now, expires_at=now + timedelta(seconds=60))
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
        assert any(
            tag == "button" and "phase-add-btn" in attrs.get("class", "").split()
            for tag, attrs in elements.items
        ) == administrative
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

    monkeypatch.setattr(sso, "get_settings", lambda: Settings(
        PROJECT_WORKFLOW_MODE="platform", AUTH_ISSUER="https://auth.fixture.invalid"))
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    assert not sso.can_administer(request)
    request.state.central_access = HumanAccess("https://auth.fixture.invalid", "fixture-human", "admin",
                                               datetime.now(timezone.utc), time.monotonic() - 1)
    assert not sso.can_administer(request)


def current_access_request(*, role="user", issuer="https://auth.fixture.invalid", subject="fixture-human",
                           seconds=20, application_access=None):
    from starlette.requests import Request

    now = datetime.now(timezone.utc)
    value = {"role": role, "application_access": application_access}
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    request.state.central_access = human_access(
        value, issuer=issuer, subject=subject,
        started=time.monotonic(), wall_started=now, expires_at=now + timedelta(seconds=seconds))
    return request


def test_identity_display_window_does_not_hash_clock_or_application_grants(monkeypatch):
    from dataclasses import replace

    from project_workflow.domain.project_admission import SpaceAccessDenied
    from project_workflow.interfaces.ui.project_admission import display_window

    monkeypatch.delenv("PROJECT_WORKFLOW_SPACES__ENABLED", raising=False)
    request = current_access_request()
    first = display_window(request)
    assert first["enforced"] and 0 < first["remaining_millis"] <= 20_000
    assert len(first["scope_revision"]) == 64
    assert display_window(current_access_request(seconds=30))["scope_revision"] == first["scope_revision"]
    for ignored in ({"applications": [], "role": "admin"}, {"enforced": False}, "malformed"):
        assert display_window(current_access_request(application_access=ignored))["scope_revision"] == first[
            "scope_revision"]
    for changed in (current_access_request(subject="another-human"), current_access_request(role="admin"),
                    current_access_request(issuer="https://other-auth.fixture.invalid")):
        assert display_window(changed)["scope_revision"] != first["scope_revision"]
    request.state.central_access = replace(request.state.central_access, _deadline=time.monotonic() - 1)
    with pytest.raises(SpaceAccessDenied):
        display_window(request)


def test_application_and_space_display_window_use_the_earliest_original_clock(monkeypatch):
    from project_workflow.domain.project_admission import human_scope
    from project_workflow.interfaces.ui.project_admission import display_window
    from tests.test_project_admission import scope

    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true")
    token = human_scope.set(scope(seconds=3))
    try:
        request = current_access_request(seconds=20)
        assert 0 < display_window(request)["remaining_millis"] <= 3_000
        human_scope.set(scope(seconds=30))
        request = current_access_request(seconds=2)
        assert 0 < display_window(request)["remaining_millis"] <= 2_000
    finally:
        human_scope.reset(token)


@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("application_access", [None, {"applications": []}, {"applications": ["wiki"]}])
def test_catalog_uses_current_identity_not_application_grants_or_shared_cache_mutation(
        monkeypatch, role, application_access):
    from dataclasses import replace

    monkeypatch.setattr(sso, "get_settings", lambda: Settings(
        PROJECT_WORKFLOW_MODE="platform", AUTH_ISSUER="https://auth.fixture.invalid"))
    catalog = [{"key": key, "label": key, "url": "https://fixture.invalid/" + key}
               for key in ("project-workflow", "wiki", "future-app")]
    request = current_access_request(role=role, application_access=application_access)
    assert sso.visible_services(request, catalog) == catalog
    assert len(catalog) == 3
    request.state.central_access = replace(request.state.central_access, _deadline=time.monotonic() - 1)
    assert sso.visible_services(request, catalog) == []


def test_missing_application_authority_is_closed_in_central_mode_and_standalone_remains_explicit(monkeypatch):
    from starlette.requests import Request

    from project_workflow.domain.project_admission import SpaceAccessDenied
    from project_workflow.interfaces.ui import project_admission

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    settings = Settings(PROJECT_WORKFLOW_MODE="platform", AUTH_ISSUER="https://auth.fixture.invalid")
    monkeypatch.setattr(sso, "get_settings", lambda: settings)
    monkeypatch.setattr(config.get_settings(), "AUTH_ISSUER", settings.AUTH_ISSUER)
    monkeypatch.delenv("PROJECT_WORKFLOW_SPACES__ENABLED", raising=False)
    assert sso.visible_services(request, [{"key": "wiki"}]) == []
    with pytest.raises(SpaceAccessDenied):
        project_admission.display_window(request)
    settings.AUTH_ISSUER = ""
    settings.PROJECT_WORKFLOW_MODE = "standalone"
    monkeypatch.setattr(config.get_settings(), "AUTH_ISSUER", "")
    monkeypatch.setattr(config.get_settings(), "PROJECT_WORKFLOW_MODE", "standalone")
    assert sso.visible_services(request, [{"key": "wiki"}]) == [{"key": "wiki"}]
    assert project_admission.display_window(request)["enforced"] is False
