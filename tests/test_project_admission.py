"""Real SQLAlchemy resource boundaries, source TTL and independent native role ceilings."""

import time
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from project_workflow.domain.project_admission import (
    HumanProjectScope,
    ProjectAccessV2,
    SpaceAccessDenied,
    human_scope,
)
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.session import get_session
from tests._retained_pm_history import PROJECT_REF, retained_pm


@pytest.fixture
def pm(monkeypatch):
    yield from retained_pm(monkeypatch)


def scope(projects=(), *, writable=None, role="member", seconds=30):
    now = int(time.time())
    proof = ProjectAccessV2(
        schema_version=2, identity={"issuer": "https://auth.test", "subject": "ordinary-user"},
        tracker_instance_id="tracker:one", canonical_tracker_instance_id=uuid4(), policy_revision=1,
        validity={"observed_at": now, "valid_until": now + 30},
        readable_spaces=(), writable_spaces=(),
        project_ids=tuple(projects), writable_project_ids=tuple(projects if writable is None else writable),
    )
    return HumanProjectScope(proof, time.monotonic() + seconds, role)


def test_exact_project_binding_filters_direct_rows_counts_and_related_history(pm):
    with get_session() as session:
        owned = session.scalar(select(m.PMExecution))
        assert owned is not None
        task_id = owned.task_id
        total = session.scalar(select(func.count()).select_from(m.Task))
        assert total >= 1
    for projects, visible in [((PROJECT_REF,), True), ((str(uuid4()),), False), ((), False)]:
        token = human_scope.set(scope(projects))
        try:
            with get_session() as session:
                rows = session.scalars(select(m.Task)).all()
                assert [row.id for row in rows] == ([task_id] if visible else [])
                assert session.scalar(select(func.count()).select_from(m.Task)) == (1 if visible else 0)
                assert (session.get(m.Task, task_id) is not None) is visible
                assert (session.scalar(select(m.PMExecution)) is not None) is visible
                assert all(row.task_id == task_id for row in session.scalars(select(m.TaskRuntimeAssignment)))
                if not visible:
                    assert not session.scalars(select(m.TaskStepHistoryEntry)).all()
                    assert not session.scalars(select(m.PMRun)).all()
        finally:
            human_scope.reset(token)


def test_membership_does_not_grant_native_mutation_and_expiry_is_not_reset():
    ordinary = scope((PROJECT_REF,))
    ordinary.require_project("tracker:one", PROJECT_REF)
    with pytest.raises(SpaceAccessDenied):
        ordinary.require_project("tracker:one", PROJECT_REF, write=True)
    operator = scope((PROJECT_REF,), role="operator")
    operator.require_project("tracker:one", PROJECT_REF, write=True)
    archived = scope((PROJECT_REF,), writable=(), role="admin")
    with pytest.raises(SpaceAccessDenied):
        archived.require_project("tracker:one", PROJECT_REF, write=True)
    with pytest.raises(SpaceAccessDenied):
        operator.require_project("another-instance", PROJECT_REF)
    token = human_scope.set(scope((PROJECT_REF,), role="admin", seconds=-1))
    try:
        with get_session() as session, pytest.raises(SpaceAccessDenied):
            session.scalar(select(func.count()).select_from(m.Task))
    finally:
        human_scope.reset(token)


def test_global_user_work_still_requires_exact_writable_project_admission():
    worker = scope((PROJECT_REF,), role="user")
    worker.require_project("tracker:one", PROJECT_REF, write=True)
    for denied in [scope((PROJECT_REF,), writable=(), role="user"),
                   scope((), role="user"), scope((PROJECT_REF,), role="user", seconds=-1)]:
        with pytest.raises(SpaceAccessDenied):
            denied.require_project("tracker:one", PROJECT_REF, write=True)
    with pytest.raises(SpaceAccessDenied):
        worker.require_project("other-instance", PROJECT_REF, write=True)


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"schema_version": 1}, {"schema_version": 2.0}, {"schema_version": "2"},
    {"policy_revision": True},
    {"project_ids": [str(UUID(int=0))]}, {"project_ids": [PROJECT_REF, PROJECT_REF]},
    {"project_ids": [], "writable_project_ids": [PROJECT_REF]},
    {"validity": {"observed_at": 1, "valid_until": 62}}, {"unknown": True},
])
def test_invalid_project_proof_cannot_become_scope(change):
    value = scope((PROJECT_REF,)).proof.model_dump(mode="json")
    value.update(change)
    with pytest.raises(ValidationError):
        ProjectAccessV2.model_validate(value)


@pytest.mark.parametrize("application_policy", [False, True])
def test_http_sso_uses_current_project_proof_without_promotion_or_cache_fallback(monkeypatch, pm, application_policy):
    import httpx
    import jwt
    from fastapi.testclient import TestClient

    from project_workflow.interfaces.ui import sso
    from project_workflow.interfaces.ui.app import create_app
    from tests.test_sso import _app

    _, settings = _app(monkeypatch, AUTH_APPLICATION_ACCESS_REQUIRED=application_policy)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true")
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__TRACKER_URL", "http://tracker.test")
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__TRACKER_INSTANCE_ID", "tracker:one")
    current = {"projects": [PROJECT_REF], "role": "member", "unavailable": False,
               "foreign": False, "apps": ["project-workflow"]}
    original_client = httpx.AsyncClient

    def upstream(request):
        if request.url.path == "/auth/me":
            identity = {"id": "ordinary-user", "status": "active", "role": current["role"]}
            if application_policy:
                from datetime import datetime, timedelta, timezone

                now = datetime.now(timezone.utc)
                identity["role"] = "admin"  # A profile hint cannot bypass the authoritative user proof.
                identity["application_access"] = {
                    "schema_version": 1, "issuer": settings.AUTH_ISSUER, "subject": "ordinary-user",
                    "role": "user", "applications": current["apps"], "revision": 3, "enforced": True,
                    "observed_at": now.isoformat(), "expires_at": (now + timedelta(seconds=15)).isoformat(),
                }
            return httpx.Response(200, json=identity)
        assert request.url.path == "/api/v2/sdlc/project-access"
        if current["unavailable"]:
            return httpx.Response(503)
        proof = scope(current["projects"]).proof.model_dump(mode="json")
        proof["identity"]["issuer"] = settings.AUTH_ISSUER
        if current["foreign"]:
            proof["identity"]["subject"] = "another-user"
        return httpx.Response(200, json=proof)

    monkeypatch.setattr(sso.httpx, "AsyncClient",
                        lambda **kwargs: original_client(transport=httpx.MockTransport(upstream), **kwargs))
    bearer = jwt.encode({"exp": int(time.time()) + 3600},
                        "synthetic-test-key-with-at-least-32-bytes", algorithm="HS256")
    headers = {"Authorization": "Bearer " + bearer}
    with TestClient(create_app(), follow_redirects=False) as client:
        opened = client.get("/api/tasks", headers=headers)
        assert opened.status_code == 200, opened.text
        assert "PM-1" in opened.text
        assert opened.headers["cache-control"] == "private, no-store"
        window = client.get("/api/v1/space-admission", headers=headers)
        assert window.status_code == 200, window.text
        ceiling = 15_000 if application_policy else 30_000
        assert window.json()["enforced"] is True and 0 < window.json()["remaining_millis"] <= ceiling
        assert window.headers["cache-control"] == "private, no-store"
        # Ordinary member cannot acquire write through another login or broad session scopes.
        for _ in range(2):
            assert client.post("/api/workflows", headers=headers, json={}).status_code == 403
        current["projects"] = []
        closed = client.get("/api/tasks", headers=headers)
        assert closed.status_code == 200 and "PM-1" not in closed.text
        assert client.get("/task/PM-1", headers=headers).status_code == 404
        current["projects"] = [PROJECT_REF]
        assert "PM-1" in client.get("/api/tasks", headers=headers).text
        current["foreign"] = True
        assert client.get("/api/tasks", headers=headers).status_code == 503
        current["foreign"] = False
        current["unavailable"] = True
        assert client.get("/api/tasks", headers=headers).status_code == 503
        if application_policy:
            current["unavailable"] = False
            current["apps"] = []
            denied = client.get("/api/tasks", headers=headers)
            assert denied.status_code == 403 and "location" not in denied.headers
            current["apps"] = ["project-workflow"]
            assert client.get("/api/tasks", headers=headers).status_code == 200


def test_retained_context_does_not_open_a_different_space_of_the_same_project(monkeypatch):
    import asyncio

    from project_workflow.application import resource_context as service
    from project_workflow.domain.exceptions import NotFoundError
    from project_workflow.domain.resource_context import CreateExecutionContext
    from tests.test_resource_context import context

    registry, a, b, instance = uuid4(), uuid4(), uuid4(), uuid4()
    with get_session() as session:
        mode = session.scalar(select(m.WorkflowMode).limit(1))
        assert mode is not None
        profile = dict(workflow_id=mode.workflow_id, catalog_version=mode.catalog_version, mode_key=mode.key)

    async def owner(owner, path, context, *, client):
        return {"namespace": context.namespace.model_dump(mode="json"), "task_id": str(context.task.task_id),
                "tracker_instance_id": str(context.task.tracker_instance_id), "project_id": PROJECT_REF,
                "generation": 1, "state": "active"}

    monkeypatch.setattr(service, "read_owner", owner)
    stored = []
    for space in [a, b]:
        value = context().model_dump(mode="json")
        value["namespace"] = {"registry_instance_id": str(registry), "namespace_id": str(space)}
        value["task"]["tracker_instance_id"] = str(instance)
        request = CreateExecutionContext(context=value, **profile)
        stored.append(asyncio.run(service.create_context(uuid4(), "same-creator", request)))
    value = scope((PROJECT_REF,)).proof.model_dump(mode="json")
    value.update(canonical_tracker_instance_id=str(instance),
                 readable_spaces=[{"registry_instance_id": str(registry), "space_id": str(a)}])
    proof = ProjectAccessV2.model_validate(value)
    token = human_scope.set(HumanProjectScope(proof, time.monotonic() + 30, "member"))
    try:
        assert service.get_context(stored[0].id) == stored[0]
        with pytest.raises(NotFoundError):
            service.get_context(stored[1].id)
        with get_session() as session:
            assert session.scalar(select(func.count()).select_from(m.ResourceExecutionContext)) == 1
    finally:
        human_scope.reset(token)


def test_display_window_retains_original_clock_and_hashes_effective_rights(monkeypatch):
    from project_workflow.interfaces.ui.project_admission import display_window
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true")
    original = scope((PROJECT_REF,))
    token = human_scope.set(original)
    try:
        first = display_window()
        assert set(first) == {"schema_version", "enforced", "remaining_millis", "scope_revision"}
        assert first["enforced"] is True and 0 < first["remaining_millis"] <= 30_000
        assert len(first["scope_revision"]) == 64
        renewed = original.proof.model_copy(update={
            "validity": original.proof.validity.model_copy(
                update={"valid_until": original.proof.validity.valid_until + 1})})
        human_scope.set(HumanProjectScope(renewed, original.deadline, original.product_role))
        assert display_window()["scope_revision"] == first["scope_revision"]
        human_scope.set(HumanProjectScope(renewed, original.deadline, "operator"))
        assert display_window()["scope_revision"] != first["scope_revision"]
        human_scope.set(HumanProjectScope(renewed.model_copy(update={"project_ids": (), "writable_project_ids": ()}),
                                          original.deadline, "member"))
        assert display_window()["scope_revision"] != first["scope_revision"]
        human_scope.set(HumanProjectScope(original.proof, time.monotonic() - 1, "member"))
        with pytest.raises(SpaceAccessDenied):
            display_window()
    finally:
        human_scope.reset(token)


def test_wall_clock_forward_cannot_keep_an_original_scope_current(monkeypatch):
    original = scope((PROJECT_REF,))
    monkeypatch.setattr(time, "time", lambda: original.proof.validity.valid_until)
    with pytest.raises(SpaceAccessDenied):
        original.require_current()


def test_display_window_policy_off_is_explicit_and_missing_proof_fails_closed(monkeypatch):
    from project_workflow.interfaces.ui.project_admission import display_window
    monkeypatch.delenv("PROJECT_WORKFLOW_SPACES__ENABLED", raising=False)
    assert display_window() == {"schema_version": 1, "enforced": False,
                                "remaining_millis": None, "scope_revision": None}
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true")
    with pytest.raises(SpaceAccessDenied):
        display_window()


@pytest.mark.parametrize("project_policy", [False, True])
@pytest.mark.parametrize("remaining_seconds", [0.0005, 0.01])
def test_display_window_does_not_expose_a_zero_millisecond_human_window(
    monkeypatch, project_policy, remaining_seconds,
):
    from fastapi import Request

    from project_workflow.infrastructure.platform_auth import HumanAccess
    from project_workflow.interfaces.ui.project_admission import display_window

    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(time, "time", lambda: 2000.0)
    monkeypatch.setenv("PROJECT_WORKFLOW_SPACES__ENABLED", "true" if project_policy else "false")
    request = Request({"type": "http", "method": "GET", "path": "/"})
    request.state.central_subject = "ordinary-user"
    request.state.central_access = HumanAccess("user", None, 1000.0 + remaining_seconds)
    original = human_scope.set(scope((PROJECT_REF,)))
    try:
        if remaining_seconds < 0.001:
            with pytest.raises(SpaceAccessDenied, match="Original .* admission expired"):
                display_window(request)
        else:
            window = display_window(request)
            assert window["enforced"] is True
            assert 1 <= window["remaining_millis"] <= 10
            assert len(window["scope_revision"]) == 64
    finally:
        human_scope.reset(original)


@pytest.mark.parametrize("role,writable,allowed", [
    ("member", True, False), ("operator", False, False), ("operator", True, True),
])
def test_task_commit_requires_native_role_and_current_writable_owner(pm, role, writable, allowed):
    with get_session() as session:
        task = session.scalar(select(m.Task).where(m.Task.task_key == "PM-1"))
        task_id, before = task.id, task.description
    proof = scope((PROJECT_REF,), writable=(PROJECT_REF,) if writable else (), role=role)
    token = human_scope.set(proof)
    try:
        with get_session() as session:
            task = session.get(m.Task, task_id)
            assert task is not None
            task.description = "permitted ordinary edit"
            if allowed:
                session.commit()
            else:
                with pytest.raises(SpaceAccessDenied):
                    session.commit()
                session.rollback()
    finally:
        human_scope.reset(token)
    with get_session() as session:
        assert session.get(m.Task, task_id).description == ("permitted ordinary edit" if allowed else before)


def test_operator_cannot_forge_native_execution_evidence(pm):
    token = human_scope.set(scope((PROJECT_REF,), role="operator"))
    try:
        with get_session() as session:
            execution = session.scalar(select(m.PMExecution))
            assert execution is not None
            before = execution.version
            execution.version += 1
            with pytest.raises(SpaceAccessDenied, match="Native execution protocol required"):
                session.commit()
            session.rollback()
    finally:
        human_scope.reset(token)
    with get_session() as session:
        assert session.scalar(select(m.PMExecution)).version == before


@pytest.mark.parametrize("writable_owner", [True, False])
def test_context_insert_requires_its_own_writable_space(writable_owner):
    from project_workflow.domain.resource_context import CreateExecutionContext
    from tests.test_resource_context import context

    registry, owner, other = uuid4(), uuid4(), uuid4()
    current = scope((PROJECT_REF,), role="operator")
    value = current.proof.model_dump(mode="json")
    value.update(
        readable_spaces=[{"registry_instance_id": str(registry), "space_id": str(owner)}],
        writable_spaces=[{"registry_instance_id": str(registry), "space_id": str(owner)}],
    )
    current = HumanProjectScope(ProjectAccessV2.model_validate(value), current.deadline, current.product_role)
    resource = context(owner if writable_owner else other).model_dump(mode="json")
    resource["namespace"]["registry_instance_id"] = str(registry)
    resource["task"]["tracker_instance_id"] = str(current.proof.canonical_tracker_instance_id)
    with get_session() as session:
        mode = session.scalar(select(m.WorkflowMode).limit(1))
        request = CreateExecutionContext(context=resource, workflow_id=mode.workflow_id,
                                         catalog_version=mode.catalog_version, mode_key=mode.key)
        row = m.ResourceExecutionContext(
            id=str(uuid4()), operation_id=str(request.context.operation_id),
            request=request.model_dump(mode="json"),
            verified_projection={"tracker_project_id": PROJECT_REF},
            workflow_id=mode.workflow_id, mode_id=mode.id, created_by_subject="confirmed-operator",
        )
    token = human_scope.set(current)
    try:
        with get_session() as session:
            session.add(row)
            if writable_owner:
                session.commit()
            else:
                with pytest.raises(SpaceAccessDenied, match="Context owner space denied"):
                    session.commit()
                session.rollback()
    finally:
        human_scope.reset(token)
    with get_session() as session:
        assert (session.get(m.ResourceExecutionContext, row.id) is not None) is writable_owner
