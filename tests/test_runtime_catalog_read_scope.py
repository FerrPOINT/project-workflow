"""Transaction-local runtime validation, never a cross-request catalog cache."""
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import event, false, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from starlette.testclient import TestClient

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests import test_single_task_profile_compatibility as retained
from tests.test_catalog_batched_reads import installed as installed
from tests.test_single_task_profile_compatibility import retained_bridge as retained_bridge


def test_runtime_scope_validates_all_roles_once_and_returns_independent_values(installed):
    uow, expected = installed
    counts = []
    connection = uow.session.connection()

    def sql(*_args):
        counts.append(1)

    event.listen(connection, "before_cursor_execute", sql)
    try:
        with patch.object(uow, "refresh", wraps=uow.refresh) as refresh:
            with patch.object(uow, "lock_catalog_state", wraps=uow.lock_catalog_state) as lock:
                with catalog.runtime_catalog_read(uow):
                    first = catalog.observe_installation(uow)
                    reads = len(counts)
                    assert reads > 0 and len(first.bindings) == 7 and first == expected
                    for _ in range(4):
                        assert catalog.observe_installation(uow) == expected
                    assert len(counts) == reads
                    first.bindings.clear()
                    assert catalog.observe_installation(uow) == expected
                    refresh.assert_called_once_with()
                    lock.assert_called_once_with(shared=True)
    finally:
        event.remove(connection, "before_cursor_execute", sql)


@pytest.mark.parametrize("write", ["orm", "bulk", "connection", "driver"])
def test_catalog_writes_invalidate_in_same_uow_before_validation(installed, write):
    uow, expected = installed
    with catalog.runtime_catalog_read(uow):
        catalog.observe_installation(uow)
        phase = int(expected.bindings[0].modes[0].phase_ids[0])
        row = uow.phase_instructions.list(phase)[0]
        change = update(m.PhaseInstruction).where(m.PhaseInstruction.id == row["id"]).values(
            description="synthetic catalog drift",
        )
        if write == "orm":
            uow.session.get(m.PhaseInstruction, row["id"]).description = "synthetic catalog drift"
            uow.session.flush()
        elif write == "bulk":
            uow.session.execute(change)
        elif write == "connection":
            uow.session.connection().execute(change)
        else:
            uow.session.connection().exec_driver_sql(
                "UPDATE phase_instructions SET description=? WHERE id=?",
                ("synthetic catalog drift", row["id"]),
            )
        with pytest.raises(ValueError):
            catalog.observe_installation(uow)


def test_runtime_scope_does_not_reuse_across_commit_rollback_or_savepoint(installed):
    uow, expected = installed
    with patch.object(uow, "refresh", wraps=uow.refresh) as refresh:
        with catalog.runtime_catalog_read(uow):
            assert catalog.observe_installation(uow) == expected
            uow.commit()
            assert catalog.observe_installation(uow) == expected
            uow.rollback()
            assert catalog.observe_installation(uow) == expected
            with uow.session.begin_nested():
                assert catalog.observe_installation(uow) == expected
            assert catalog.observe_installation(uow) == expected
            assert refresh.call_count == 5


def test_runtime_scope_keeps_task_writes_but_never_reuses_for_another_uow(installed):
    uow, expected = installed
    with patch.object(uow, "refresh", wraps=uow.refresh) as refresh:
        with catalog.runtime_catalog_read(uow):
            catalog.observe_installation(uow)
            uow.session.execute(update(m.Task).where(false()).values(status="done"))
            assert catalog.observe_installation(uow) == expected
            refresh.assert_called_once_with()
            with SAUnitOfWork() as other:
                with patch.object(other, "refresh", wraps=other.refresh) as other_refresh:
                    assert catalog.observe_installation(other) == expected
                    other_refresh.assert_called_once_with()


@pytest.mark.parametrize("statement", [text("SELECT 1"), select(1).where(text("1=1"))])
def test_opaque_sql_conservatively_requires_fresh_catalog_validation(installed, statement):
    uow, expected = installed
    with patch.object(uow, "refresh", wraps=uow.refresh) as refresh:
        with catalog.runtime_catalog_read(uow):
            assert catalog.observe_installation(uow) == expected
            uow.session.execute(statement)
            assert catalog.observe_installation(uow) == expected
            assert refresh.call_count == 2


@pytest.mark.parametrize("shared", [False, True])
def test_catalog_lock_select_keeps_exact_schema_scoped_hash_and_lock_kind(shared):
    uow = SAUnitOfWork.__new__(SAUnitOfWork)
    uow._session = Mock()
    uow._session.get_bind.return_value.dialect.name = "postgresql"
    uow.lock_catalog_state(shared=shared)
    statement, parameters = uow._session.execute.call_args.args
    compiled = statement.compile(dialect=postgresql.dialect())
    assert statement.is_select
    lock = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    assert str(compiled).startswith(f"SELECT {lock}(hashtextextended(")
    assert "current_database() ||" in str(compiled) and "|| %(schema)s" in str(compiled)
    assert sorted(compiled.params.values(), key=str) == [0, ":", None]
    assert parameters == {"schema": catalog.config.get_settings().DB_SCHEMA}


def test_nested_scope_error_removes_observation_and_unscoped_reads_stay_fresh(installed):
    uow, expected = installed
    with patch.object(uow, "refresh", wraps=uow.refresh) as refresh:
        with pytest.raises(RuntimeError, match="synthetic"):
            with catalog.runtime_catalog_read(uow):
                with catalog.runtime_catalog_read(uow):
                    assert catalog.observe_installation(uow) == expected
                    assert catalog.observe_installation(uow) == expected
                raise RuntimeError("synthetic call error")
        assert catalog._RUNTIME_READ not in uow.session.info
        assert catalog.observe_installation(uow) == expected
        assert catalog.observe_installation(uow) == expected
        assert refresh.call_count == 3


def test_retained_retry_terminal_path_bounds_full_validations_per_runtime_uow(
    retained_bridge, monkeypatch, supervisor_llm,
):
    original, validate = TestClient.request, catalog._observe_profile
    validations = []
    queries = []
    counts = []

    def sql(*_args):
        queries.append(1)

    def observed(uow, *args):
        result = validate(uow, *args)
        validations.append((uow.session, uow.session.get_transaction(), uow.session.get_nested_transaction()))
        assert validations[-1][1] is not None
        return result

    def request(self, method, url, *args, **kwargs):
        before, before_sql = len(validations), len(queries)
        response = original(self, method, url, *args, **kwargs)
        observed_transactions = validations[before:]
        # Supervisor commits are real boundaries, not reusable validation authority.
        assert len(observed_transactions) == len(set(observed_transactions))
        counts.append((str(url).rsplit("/", 1)[-1], len(observed_transactions), len(queries) - before_sql))
        return response

    monkeypatch.setattr(catalog, "_observe_profile", observed)
    monkeypatch.setattr(TestClient, "request", request)
    # Exercise original assertions, canonical identities and retained final receipt.
    event.listen(Engine, "before_cursor_execute", sql)
    try:
        retained.test_retained_retry_keeps_original_family_through_confirmation_and_terminal(
            retained_bridge, monkeypatch, supervisor_llm, "unbound",
        )
    finally:
        event.remove(Engine, "before_cursor_execute", sql)
    steps = [count for route, count, _queries in counts if route == "step"]
    assert steps and max(steps) <= 8  # includes real intermediate Supervisor commits
    assert all(queries <= 800 for route, _count, queries in counts if route == "step")
    assert counts[-1][:2] == ("readback", 1)
    assert counts[-1][2] <= 200
