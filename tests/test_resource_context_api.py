"""HTTP/persistence boundary checks. Installed acceptance uses actual owner services."""

from uuid import UUID, uuid4

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

    async def reader(owner, path, item):
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

    async def reader(owner, path, value):
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
