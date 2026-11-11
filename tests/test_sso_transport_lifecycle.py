"""The shared Auth connection pool never shares identity or cookie authority."""

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from project_workflow.interfaces.ui import sso
from tests._human_access_helpers import human_identity, human_token
from tests.test_sso import _app


def test_pool_is_reused_but_each_request_confirms_its_own_identity(monkeypatch):
    original_client = httpx.AsyncClient
    clients = []
    requests = []
    tokens = {name: human_token(name) for name in ("alice", "bob")}

    def owner(request):
        requests.append(request)
        if len(requests) == 3:
            return httpx.Response(401)
        if len(requests) == 4:
            raise httpx.ConnectError("isolated Auth outage", request=request)
        token = request.headers["authorization"].removeprefix("Bearer ")
        subject = next(name for name, value in tokens.items() if value == token)
        return httpx.Response(200, json=human_identity(subject),
                              headers={"set-cookie": "owner_session=must-not-propagate; Path=/"})

    def client(**kwargs):
        value = original_client(transport=httpx.MockTransport(owner), **kwargs)
        clients.append(value)
        return value

    monkeypatch.setattr(sso.httpx, "AsyncClient", client)
    app, _ = _app(monkeypatch)
    with TestClient(app, follow_redirects=False) as browser:
        assert browser.get("/api/tasks", headers={"Authorization": f"Bearer {tokens['alice']}"}).status_code == 200
        assert browser.get("/api/tasks", headers={"Authorization": f"Bearer {tokens['bob']}"}).status_code == 200
        assert browser.get("/api/tasks", headers={"Authorization": f"Bearer {tokens['alice']}"}).status_code == 401
        assert browser.get("/api/tasks", headers={"Authorization": f"Bearer {tokens['bob']}"}).status_code == 503
        assert len(clients) == 1
        assert not clients[0].is_closed
        assert len(clients[0].cookies) == 0
    assert clients[0].is_closed
    assert not hasattr(app.state, "central_auth_http")
    assert [r.headers["authorization"] for r in requests] == [
        f"Bearer {tokens[name]}" for name in ("alice", "bob", "alice", "bob")
    ]
    assert all("cookie" not in r.headers for r in requests)


def test_auth_resources_preserve_existing_lifespan_state_and_cleanup(monkeypatch):
    _, settings = _app(monkeypatch)
    events = []

    @asynccontextmanager
    async def existing_lifespan(app):
        events.append("start")
        yield {"original_resource": "still-present"}
        events.append("stop")
        assert not hasattr(app.state, "central_auth_http")

    app = FastAPI(lifespan=existing_lifespan)
    sso.install_sso(app, settings)

    @app.get("/health")
    def health(request: Request):
        return {"resource": request.state.original_resource}

    with TestClient(app) as browser:
        assert browser.get("/health").json() == {"resource": "still-present"}
        assert events == ["start"]
    assert events == ["start", "stop"]


def test_standalone_does_not_allocate_a_central_auth_client(monkeypatch):
    def unexpected_client(**kwargs):
        raise AssertionError("standalone must not create a Central Auth transport")

    monkeypatch.setattr(sso.httpx, "AsyncClient", unexpected_client)
    app, _ = _app(monkeypatch, PROJECT_WORKFLOW_MODE="standalone")
    with TestClient(app) as browser:
        assert browser.get("/api/tasks").status_code == 200
        assert not hasattr(app.state, "central_auth_http")
