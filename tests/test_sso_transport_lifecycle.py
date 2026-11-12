"""The shared Auth connection pool never shares identity or cookie authority."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest
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


def test_cancelling_one_caller_keeps_the_pool_and_other_identity_alive(monkeypatch):
    original_client = httpx.AsyncClient
    tokens = {name: human_token(name) for name in ("alice", "bob")}
    requests = []

    async def exercise():
        entered = asyncio.Event()

        async def owner(request):
            requests.append(request)
            if request.headers["authorization"] == f"Bearer {tokens['alice']}":
                entered.set()
                await asyncio.Future()
            return httpx.Response(200, json=human_identity("bob"),
                                  headers={"set-cookie": "owner_session=must-not-propagate; Path=/"})

        monkeypatch.setattr(sso.httpx, "AsyncClient", lambda **kwargs: original_client(
            transport=httpx.MockTransport(owner), **kwargs))
        app, _ = _app(monkeypatch)

        @app.get("/api/verified")
        def verified(request: Request):
            return {"subject": request.state.central_subject}

        async with app.router.lifespan_context(app):
            pool = app.state.central_auth_http
            async with original_client(transport=httpx.ASGITransport(app=app),
                                       base_url="http://localhost:8812") as client:
                pending = asyncio.create_task(client.get(
                    "/api/verified", headers={"Authorization": f"Bearer {tokens['alice']}"}))
                try:
                    await asyncio.wait_for(entered.wait(), timeout=2)
                    response = await asyncio.wait_for(client.get(
                        "/api/verified", headers={"Authorization": f"Bearer {tokens['bob']}"}), timeout=2)
                    assert response.status_code == 200
                    assert response.json() == {"subject": "bob"}
                finally:
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                response = await client.get("/api/verified", headers={"Authorization": f"Bearer {tokens['bob']}"})
                assert response.status_code == 200
                assert response.json() == {"subject": "bob"}
                assert not pool.is_closed
                assert len(pool.cookies) == 0
        assert pool.is_closed
        assert not hasattr(app.state, "central_auth_http")
        assert len(requests) == 3
        assert all("cookie" not in request.headers for request in requests)

    asyncio.run(exercise())


def test_standalone_does_not_allocate_a_central_auth_client(monkeypatch):
    def unexpected_client(**kwargs):
        raise AssertionError("standalone must not create a Central Auth transport")

    monkeypatch.setattr(sso.httpx, "AsyncClient", unexpected_client)
    app, _ = _app(monkeypatch, PROJECT_WORKFLOW_MODE="standalone")
    with TestClient(app) as browser:
        assert browser.get("/api/tasks").status_code == 200
        assert not hasattr(app.state, "central_auth_http")
