"""Focused v2 contract/persistence checks; end-to-end acceptance uses real owner APIs."""

import asyncio
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from project_workflow.application import resource_context as service
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.resource_context import CreateExecutionContext, ExecutionContextV2
from project_workflow.infrastructure.db.models import ResourceExecutionContext, WorkflowMode
from project_workflow.infrastructure.db.session import get_session


def context(namespace=None):
    return ExecutionContextV2(
        schema_version=2,
        operation_id=uuid4(),
        namespace={"registry_instance_id": uuid4(), "namespace_id": namespace or uuid4()},
        task={"tracker_instance_id": uuid4(), "task_id": uuid4()},
        repositories=[],
    )


def test_refs_reject_nil_duplicate_and_unknown_v1_fields():
    item = context().model_dump()
    item["namespace"]["namespace_id"] = UUID(int=0)
    with pytest.raises(ValidationError):
        ExecutionContextV2.model_validate(item)
    item = context().model_dump()
    item["runtime_ready"] = True
    with pytest.raises(ValidationError):
        ExecutionContextV2.model_validate(item)
    item = context().model_dump()
    repository = {"forge_instance_id": uuid4(), "repository_id": uuid4()}
    item["repositories"] = [repository, repository]
    with pytest.raises(ValidationError):
        ExecutionContextV2.model_validate(item)


def test_two_namespaces_share_profile_with_durable_replay_and_closed_dispatch(monkeypatch):
    with get_session() as session:
        mode = session.scalar(select(WorkflowMode).limit(1))
        assert mode is not None
        profile = dict(workflow_id=mode.workflow_id, catalog_version=mode.catalog_version, mode_key=mode.key)
    calls = []

    async def owner_read(owner, path, context, *, client):
        calls.append((owner, path))
        return {
            "namespace": context.namespace.model_dump(mode="json"),
            "tracker_instance_id": str(context.task.tracker_instance_id),
            "task_id": str(context.task.task_id),
            "project_id": str(uuid4()),
            "generation": 7,
            "state": "active",
        }

    monkeypatch.setattr(service, "read_owner", owner_read)
    first = CreateExecutionContext(context=context(), **profile)
    second = CreateExecutionContext(context=context(), **profile)
    identity = uuid4()
    saved = asyncio.run(service.create_context(identity, "human", first))
    other = asyncio.run(service.create_context(uuid4(), "human", second))
    assert saved.request.workflow_id == other.request.workflow_id
    assert saved.request.context.namespace != other.request.context.namespace
    assert saved.runtime_ready is False and saved.dispatch_allowed is False
    assert service.get_context(identity) == saved
    count = len(calls)
    assert asyncio.run(service.create_context(identity, "human", first)) == saved
    assert len(calls) == count

    # Persisted readback is independently verified and cannot open dispatch.
    with get_session() as session, session.begin():
        row = session.get(ResourceExecutionContext, str(identity))
        assert row is not None
        projection = dict(row.verified_projection)
        projection["id"] = str(uuid4())
        row.verified_projection = projection
    with pytest.raises(service.OwnerUnavailable):
        service.get_context(identity)
    with pytest.raises(service.OwnerUnavailable):
        asyncio.run(service.create_context(identity, "human", first))
    with pytest.raises(ConflictError):
        asyncio.run(service.create_context(identity, "other-human", first))
    with pytest.raises(ConflictError):
        asyncio.run(service.create_context(identity, "human", second))
    assert len(calls) == count


def test_foreign_task_projection_cannot_be_persisted(monkeypatch):
    async def foreign(owner, path, context, *, client):
        return {
            "namespace": {"registry_instance_id": str(uuid4()), "namespace_id": str(uuid4())},
            "task_id": str(context.task.task_id),
            "tracker_instance_id": str(context.task.tracker_instance_id),
            "state": "active",
        }

    monkeypatch.setattr(service, "read_owner", foreign)
    request = CreateExecutionContext(context=context(), workflow_id=1, catalog_version=1, mode_key="default")
    with pytest.raises(ConflictError):
        asyncio.run(service.create_context(uuid4(), "human", request))
