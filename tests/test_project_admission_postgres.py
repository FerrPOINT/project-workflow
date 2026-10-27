"""Actual PostgreSQL row wait, scope ownership and deferred commit boundaries."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from project_workflow.domain.project_admission import (
    HumanProjectScope,
    SpaceAccessDenied,
    human_scope,
)
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.session import get_engine, get_session
from tests import test_postgres_integration as pg_fixtures
from tests._retained_pm_history import PROJECT_REF
from tests.test_project_admission import scope

# Re-export the existing real database fixtures without a second fixture implementation.
pg_url = pg_fixtures.pg_url
pm_postgres = pg_fixtures.pm_postgres
pytestmark = pytest.mark.integration


@pytest.fixture
def owned(pm_postgres):
    assert pm_postgres[1]  # Direct sealed history fixture, no retired bind RPC.
    with get_session() as session:
        task = session.scalar(select(m.Task).join(m.PMExecution, m.Task.id == m.PMExecution.task_id))
        assert task is not None
        return task.id, task.title


def sql_denied(statement, params, proof):
    token = human_scope.set(proof)
    try:
        with get_session() as session:
            with pytest.raises(DBAPIError) as rejected:
                session.execute(text(statement), params)
                session.commit()
            assert rejected.value.orig.sqlstate == "42501"
            session.rollback()
    finally:
        human_scope.reset(token)


def test_real_owner_and_separate_native_role_are_enforced_on_resource_dml(owned):
    task_id, original_title = owned
    query = "UPDATE tasks SET title=:title WHERE id=:id"
    for proof in [scope((), role="operator"), scope((PROJECT_REF,), writable=(), role="operator"),
                  scope((PROJECT_REF,), role="member")]:
        sql_denied(query, {"id": task_id, "title": "denied"}, proof)
    with get_session() as session:
        assert session.get(m.Task, task_id).title == original_title
    token = human_scope.set(scope((PROJECT_REF,), role="operator"))
    try:
        with get_session() as session:
            session.execute(text(query), {"id": task_id, "title": "allowed"})
            session.commit()
    finally:
        human_scope.reset(token)
    with get_session() as session:
        assert session.get(m.Task, task_id).title == "allowed"
    sql_denied("UPDATE pm_executions SET version=version+1 WHERE task_id=:id",
               {"id": task_id}, scope((PROJECT_REF,), role="admin"))


def test_sql_wait_cannot_extend_original_human_permit(owned):
    task_id, original_title = owned
    engine = get_engine()
    entered = Event()

    def waiting_write():
        proof = scope((PROJECT_REF,), role="operator", seconds=0.6)
        token = human_scope.set(proof)
        try:
            with get_session() as session:
                entered.set()
                with pytest.raises(DBAPIError) as rejected:
                    session.execute(text(
                        "UPDATE tasks SET title='late row wait' WHERE id=:id /* original-proof-row-wait */"
                    ), {"id": task_id})
                    session.commit()
                assert rejected.value.orig.sqlstate == "42501"
                session.rollback()
        finally:
            human_scope.reset(token)

    with engine.connect() as locker:
        lock = locker.begin()
        locker.execute(text("SELECT id FROM tasks WHERE id=:id FOR UPDATE"), {"id": task_id})
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(waiting_write)
            try:
                assert entered.wait(5)
                with engine.connect() as observer:
                    for _ in range(100):
                        waiting = observer.scalar(text(
                            "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' "
                            "AND query LIKE '%original-proof-row-wait%' AND pid<>pg_backend_pid()"
                        ))
                        if waiting:
                            break
                        time.sleep(0.01)
                    assert waiting, "The regression must cross an actual PostgreSQL row lock"
                time.sleep(0.7)
            finally:
                lock.rollback()
            pending.result(timeout=10)
    with get_session() as session:
        assert session.get(m.Task, task_id).title == original_title


def test_deferred_database_commit_rejects_expiry_and_preserves_data(owned):
    task_id, original_title = owned
    token = human_scope.set(scope((PROJECT_REF,), role="operator", seconds=0.6))
    try:
        with get_session() as session:
            connection = session.connection()  # installs the real transaction-local original clock
            connection.execute(text("UPDATE tasks SET title='late commit' WHERE id=:id"), {"id": task_id})
            connection.execute(text("SELECT pg_sleep(0.7)"))
            with pytest.raises(DBAPIError) as rejected:
                connection.commit()
            assert rejected.value.orig.sqlstate == "42501"
            session.rollback()
    finally:
        human_scope.reset(token)
    with get_session() as session:
        assert session.get(m.Task, task_id).title == original_title
        assert session.scalar(text("SELECT current_setting('pdlc.workflow_human', true)")) in {None, ""}


def test_session_cannot_transfer_a_transaction_to_a_new_human_proof(owned):
    task_id, _ = owned
    token = human_scope.set(scope((PROJECT_REF,)))
    try:
        with get_session() as session:
            assert session.get(m.Task, task_id)
            human_scope.set(scope(()))
            with pytest.raises(SpaceAccessDenied, match="Session belongs"):
                session.scalars(select(m.Task)).all()
            session.rollback()
    finally:
        human_scope.reset(token)


def test_same_project_does_not_open_a_foreign_context_space(owned):
    from project_workflow.domain.resource_context import CreateExecutionContext
    from tests.test_resource_context import context

    registry, space_a, space_b = uuid4(), uuid4(), uuid4()
    proof = scope((PROJECT_REF,), role="operator")
    from project_workflow.domain.project_admission import ProjectAccessV2
    value = proof.proof.model_dump(mode="json")
    value.update(readable_spaces=[{"registry_instance_id": str(registry), "space_id": str(space_a)}],
                 writable_spaces=[{"registry_instance_id": str(registry), "space_id": str(space_a)}])
    proof = HumanProjectScope(ProjectAccessV2.model_validate(value), proof.deadline, proof.product_role)
    contexts = []
    with get_session() as session:
        mode = session.scalar(select(m.WorkflowMode).limit(1))
        for space in (space_a, space_b):
            resource = context(space).model_dump(mode="json")
            resource["namespace"]["registry_instance_id"] = str(registry)
            resource["task"]["tracker_instance_id"] = str(proof.proof.canonical_tracker_instance_id)
            request = CreateExecutionContext(context=resource, workflow_id=mode.workflow_id,
                                             catalog_version=mode.catalog_version, mode_key=mode.key)
            row = m.ResourceExecutionContext(
                id=str(uuid4()), operation_id=str(request.context.operation_id),
                request=request.model_dump(mode="json"),
                verified_projection={"tracker_project_id": str(PROJECT_REF)},
                workflow_id=mode.workflow_id, mode_id=mode.id, created_by_subject="native-fixture",
            )
            session.add(row)
            contexts.append((row.id, row.request))
        session.commit()
    token = human_scope.set(proof)
    try:
        with get_session() as session:
            assert [row.id for row in session.scalars(select(m.ResourceExecutionContext)).all()] == [contexts[0][0]]
            assert session.get(m.ResourceExecutionContext, contexts[1][0]) is None
    finally:
        human_scope.reset(token)
    sql_denied("UPDATE resource_execution_contexts SET created_by_subject='foreign' WHERE id=:id",
               {"id": contexts[1][0]}, proof)
    swapped = json.loads(json.dumps(contexts[0][1]))
    swapped["context"]["namespace"]["namespace_id"] = str(space_b)
    sql_denied("UPDATE resource_execution_contexts SET request=CAST(:value AS json) WHERE id=:id",
               {"id": contexts[0][0], "value": json.dumps(swapped)}, proof)
    token = human_scope.set(proof)
    try:
        with get_session() as session:
            session.execute(text(
                "UPDATE resource_execution_contexts SET created_by_subject=created_by_subject WHERE id=:id"
            ), {"id": contexts[0][0]})
            session.commit()
    finally:
        human_scope.reset(token)
    with get_session() as session:
        assert session.get(m.ResourceExecutionContext, contexts[0][0]).created_by_subject == "native-fixture"
        assert session.get(m.ResourceExecutionContext, contexts[1][0]).created_by_subject == "native-fixture"
