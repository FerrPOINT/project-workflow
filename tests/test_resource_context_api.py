"""HTTP/persistence boundary checks. Installed acceptance uses actual owner services."""

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from project_workflow.application import resource_context as service
from project_workflow.domain.resource_context import CreateExecutionContext
from project_workflow.infrastructure.db.models import ResourceExecutionContext, WorkflowMode
from project_workflow.infrastructure.db.session import get_session
from project_workflow.interfaces.ui.routes import resource_context as routes
from tests.test_resource_context import context


def profile_request():
    with get_session() as session:
        mode = session.scalar(select(WorkflowMode).limit(1))
        return CreateExecutionContext(
            context=context(), workflow_id=mode.workflow_id, catalog_version=mode.catalog_version, mode_key=mode.key
        )


@pytest.mark.parametrize("operation", ["read", "replay", "persist"])
def test_context_storage_does_not_hold_the_http_event_loop(monkeypatch, operation):
    from threading import Event

    import httpx
    from sqlalchemy.orm import Session

    from project_workflow.infrastructure.db.models import Workflow

    request = profile_request()
    identity = uuid4()
    project_id = uuid4()

    async def reader(owner, path, value, *, client):
        return {"namespace": value.namespace.model_dump(mode="json"),
                "task_id": str(value.task.task_id), "tracker_instance_id": str(value.task.tracker_instance_id),
                "project_id": str(project_id), "generation": 1, "state": "active"}

    monkeypatch.setattr(service, "read_owner", reader)
    if operation != "persist":
        asyncio.run(service.create_context(identity, "human", request))
    entered, release, expired = Event(), Event(), Event()
    original_get = Session.get

    def held_get(self, entity, *args, **kwargs):
        held_entity = Workflow if operation == "persist" else ResourceExecutionContext
        if entity is held_entity:
            entered.set()
            if not release.wait(2):
                expired.set()
        return original_get(self, entity, *args, **kwargs)

    monkeypatch.setattr(Session, "get", held_get)
    app = FastAPI()

    @app.middleware("http")
    async def verified_actor(http_request, call_next):
        http_request.state.central_subject = "human"
        return await call_next(http_request)

    app.get("/contexts/{identity}")(routes.read)
    app.put("/contexts/{identity}")(routes.bind)

    @app.get("/probe")
    async def probe():
        return {"ok": True}

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            path = f"/contexts/{identity}"
            pending = asyncio.create_task(client.get(path) if operation == "read" else
                                          client.put(path, json=request.model_dump(mode="json")))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                assert not expired.is_set(), "Synchronous storage held the HTTP event loop"
                assert (await asyncio.wait_for(client.get("/probe"), 1)).status_code == 200
            finally:
                release.set()
                response = await pending
            assert response.status_code == 200, response.text

    asyncio.run(exercise())


@pytest.mark.parametrize("delay, succeeds", [(0.01, True), (0.08, False)])
def test_owner_verification_shares_command_deadline_and_closes_its_pool(monkeypatch, delay, succeeds):
    monkeypatch.setattr(service, "CONTEXT_TIMEOUT_SECONDS", 0.16)
    request = profile_request()
    repositories = [
        {"forge_instance_id": uuid4(), "repository_id": uuid4()},
        {"forge_instance_id": uuid4(), "repository_id": uuid4()},
    ]
    request = CreateExecutionContext.model_validate(
        {**request.model_dump(), "context": {**request.context.model_dump(), "repositories": repositories}}
    )
    clients = []

    async def reader(owner, path, value, *, client):
        clients.append(client)
        await asyncio.sleep(delay)
        common = {"namespace": value.namespace.model_dump(mode="json")}
        if owner == "TRACKER":
            return {**common, "task_id": str(value.task.task_id),
                    "tracker_instance_id": str(value.task.tracker_instance_id),
                    "project_id": str(uuid4()), "generation": 1, "state": "active"}
        repository = next(item for item in value.repositories if path.endswith(str(item.repository_id)))
        return {**common, "repository_id": str(repository.repository_id),
                "forge_instance_id": str(repository.forge_instance_id)}

    monkeypatch.setattr(service, "read_owner", reader)
    identity = uuid4()
    if succeeds:
        result = asyncio.run(service.create_context(identity, "verified-human", request))
        assert result.id == identity and result.dispatch_allowed is False
        assert len(clients) == 3
    else:
        with pytest.raises(service.OwnerUnavailable, match="deadline"):
            asyncio.run(service.create_context(identity, "verified-human", request))
        from project_workflow.domain.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            service.get_context(identity)
    assert len({id(client) for client in clients}) == 1
    assert all(client.is_closed for client in clients)


def test_context_http_statuses_original_readback_and_foreign_actor(monkeypatch):
    app = FastAPI()
    actor = {"subject": "human"}

    @app.middleware("http")
    async def verified_test_actor(request, call_next):
        if actor["subject"]:
            request.state.central_subject = actor["subject"]
        return await call_next(request)

    app.get("/contexts/{identity}")(routes.read)
    app.put("/contexts/{identity}")(routes.bind)
    state = {"kind": "valid"}

    async def reader(owner, path, item, *, client):
        if state["kind"] == "outage":
            raise service.OwnerUnavailable()
        if state["kind"] == "foreign":
            raise ValueError("Foreign context")
        return {
            "namespace": item.namespace.model_dump(mode="json"),
            "tracker_instance_id": str(item.task.tracker_instance_id),
            "task_id": str(item.task.task_id),
            "project_id": str(uuid4()),
            "generation": 7 if state["kind"] != "corrupt" else "7",
            "state": "active",
        }

    monkeypatch.setattr(service, "read_owner", reader)
    item = profile_request()
    identity = uuid4()
    path = f"/contexts/{identity}"
    body = item.model_dump(mode="json")
    with TestClient(app) as client:
        assert client.get(path).status_code == 404
        actor["subject"] = ""
        assert client.get(path).status_code == 401
        assert client.put(path, json=body).status_code == 401
        actor["subject"] = "human"
        for kind, expected in [("outage", 503), ("foreign", 409), ("corrupt", 503)]:
            state["kind"] = kind
            assert client.put(path, json=body).status_code == expected
        state["kind"] = "valid"
        assert client.put(f"/contexts/{UUID(int=0)}", json=body).status_code == 409
        response = client.put(path, json=body)
        assert response.status_code == 200
        saved = response.json()
        assert saved["runtime_ready"] is False and saved["dispatch_allowed"] is False
        state["kind"] = "outage"
        assert client.put(path, json=body).json() == saved
        assert client.get(path).json() == saved
        actor["subject"] = "another-human"
        assert client.get(path).json() == saved  # Shared trusted catalog, no new project ACL.
        assert client.put(path, json=body).status_code == 409
        with get_session() as session, session.begin():
            row = session.get(ResourceExecutionContext, str(identity))
            projection = dict(row.verified_projection)
            projection["binding_generation"] = "7"
            row.verified_projection = projection
        assert client.get(path).status_code == 503


def test_repository_verification_profile_version_and_operation_uniqueness(monkeypatch):
    item = profile_request()
    calls = []
    mode = {"foreign": False}
    repository = {"forge_instance_id": uuid4(), "repository_id": uuid4()}
    item = CreateExecutionContext.model_validate(
        {**item.model_dump(), "context": {**item.context.model_dump(), "repositories": [repository]}}
    )

    async def reader(owner, path, value, *, client):
        calls.append(owner)
        if owner == "FORGE":
            return {
                "namespace": value.namespace.model_dump(mode="json"),
                "repository_id": str(uuid4() if mode["foreign"] else repository["repository_id"]),
                "forge_instance_id": str(repository["forge_instance_id"]),
            }
        return {
            "namespace": value.namespace.model_dump(mode="json"),
            "tracker_instance_id": str(value.task.tracker_instance_id),
            "task_id": str(value.task.task_id),
            "project_id": str(uuid4()),
            "generation": 1,
            "state": "active",
        }

    monkeypatch.setattr(service, "read_owner", reader)
    import asyncio

    import pytest

    from project_workflow.domain.exceptions import ConflictError

    mode["foreign"] = True
    with pytest.raises(ConflictError):
        asyncio.run(service.create_context(uuid4(), "human", item))
    mode["foreign"] = False
    wrong = CreateExecutionContext.model_validate({**item.model_dump(), "catalog_version": 999})
    with pytest.raises(ConflictError):
        asyncio.run(service.create_context(uuid4(), "human", wrong))
    saved = asyncio.run(service.create_context(uuid4(), "human", item))
    assert calls.count("FORGE") == 3
    with pytest.raises(ConflictError, match="operation already used"):
        asyncio.run(service.create_context(uuid4(), "human", item))
    assert service.get_context(saved.id) == saved
