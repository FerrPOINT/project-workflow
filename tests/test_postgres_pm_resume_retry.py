"""Real PostgreSQL migration/row locks; existing synthetic native callbacks only."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import inspect, text

from project_workflow import config
from project_workflow.application import state as app_state
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db.session import (
    database_revisions,
    ensure_migrated,
    get_engine,
    run_alembic_command,
    schema_is_ready,
)
from project_workflow.interfaces import ui as ui_package
from project_workflow.interfaces.ui import state as ui_state
from tests import test_pm_resume_retry as retry_cases
from tests import test_postgres_integration as pg_fixtures
from tests import test_single_task_runtime as profile_fixtures

pytestmark = pytest.mark.integration
pg_url = pg_fixtures.pg_url
pending = retry_cases.pending
PREDECESSOR = "0018_identity_deletion_owner"
HEAD = "0020_configured_cli_catalog"


@pytest.fixture(autouse=True)
def postgres(isolate_ui_runtime_state, pg_url, monkeypatch):
    # Keep the global SQLite isolation intact; only this module's requests/UoWs
    # use the disposable database created (and removed) by the existing pg_url.
    engine = get_engine(pg_url)
    assert engine.dialect.name == "postgresql"
    assert engine.url.database == pg_url.rsplit("/", 1)[-1]
    state = app_state._AppState(database_url=pg_url)
    for module in (app_state, ui_state, ui_package):
        monkeypatch.setattr(module, "_app_state", state)
    config.get_settings.cache_clear()
    return engine


@pytest.fixture
def bridge(postgres, monkeypatch, request):
    if getattr(request, "param", None) == PREDECESSOR:
        run_alembic_command("upgrade", postgres, PREDECESSOR)
        assert database_revisions(postgres) == {PREDECESSOR}
    else:
        ensure_migrated(postgres)
    # Reuse the unchanged catalog/token/TestClient fixture, not its SQLite DB.
    yield from profile_fixtures.bridge.__wrapped__(monkeypatch)


def checks(engine):
    return {
        item["name"]: item["sqltext"]
        for item in inspect(engine).get_check_constraints(
            "pm_operations",
            schema=config.get_settings().DB_SCHEMA,
        )
    }


@pytest.mark.parametrize("bridge", [PREDECESSOR], indirect=True)
def test_populated_0018_upgrade_is_idempotent_and_retry_blocks_downgrade(pending, postgres):
    client, command, _, _, _ = pending
    assert database_revisions(postgres) == {PREDECESSOR}
    before = retry_cases.stored()
    assert {row["kind"] for row in before["pm_operations"]} == {"bind", "checkpoint", "resume"}
    original_checks = checks(postgres)
    assert "resume_retry" not in original_checks["ck_pm_operation_kind"]

    ensure_migrated(postgres)
    assert database_revisions(postgres) == {HEAD}
    assert schema_is_ready(postgres)
    assert retry_cases.stored() == before
    expanded = checks(postgres)
    assert "resume_retry" in expanded["ck_pm_operation_kind"]
    assert {k: v for k, v in expanded.items() if k != "ck_pm_operation_kind"} == {
        k: v for k, v in original_checks.items() if k != "ck_pm_operation_kind"
    }
    ensure_migrated(postgres)
    assert retry_cases.stored() == before and checks(postgres) == expanded

    run_alembic_command("downgrade", postgres, PREDECESSOR)
    assert database_revisions(postgres) == {PREDECESSOR}
    assert retry_cases.stored() == before and checks(postgres) == original_checks
    ensure_migrated(postgres)
    accepted = client.post(retry_cases.PM + "resume-retry", headers=retry_cases.WRITER, json=command)
    assert accepted.status_code == 200, accepted.text
    retained = retry_cases.stored()
    with pytest.raises(RuntimeError, match="Retained PM resume retry receipts prevent downgrade"):
        run_alembic_command("downgrade", postgres, PREDECESSOR)
    assert database_revisions(postgres) == {HEAD}
    assert schema_is_ready(postgres)
    assert retry_cases.stored() == retained and checks(postgres) == expanded


def test_retry_replay_restart_and_original_readback_on_postgres(pending, monkeypatch):
    retry_cases.test_retry_keeps_source_fence_and_checkpoint_with_exact_replay_and_readback(pending, monkeypatch)


def test_bootstrap_canonical_identity_survives_retry_on_postgres(bridge, monkeypatch):
    retry_cases.test_bootstrap_canonical_identity_survives_terminal_resume_retry(bridge, monkeypatch)


@pytest.mark.parametrize("checkpoint_ref", [None, retry_cases.CHECKPOINT], ids=["absent", "inherited-source"])
def test_retry_preserves_failed_terminal_checkpoint_marker_on_postgres(pending, monkeypatch, checkpoint_ref):
    retry_cases.test_retry_preserves_failed_terminal_checkpoint_marker(pending, monkeypatch, checkpoint_ref)


def test_retry_rejects_foreign_checkpoint_marker_on_postgres(pending):
    retry_cases.test_retry_rejects_nonterminal_or_foreign_trusted_readback(
        pending, "checkpoint_ref", "foreign-checkpoint"
    )


def test_retry_rejects_genuine_rebound_pm_run_on_postgres(pending, monkeypatch):
    retry_cases.test_retry_rejects_target_with_genuine_rebound_pm_run(pending, monkeypatch)


@pytest.mark.parametrize("same_key", [True, False], ids=["same-key", "different-target"])
def test_concurrent_retry_serializes_one_receipt_and_target(pending, postgres, monkeypatch, same_key):
    client, command, _, _, _ = pending
    before = retry_cases.stored()
    second = (
        command
        if same_key
        else {
            **command,
            "operation_key": "resume-retry:competitor",
            "new_session_run_id": retry_cases.LATER,
            "new_binding_ref": "fleet:pm:" + retry_cases.LATER,
        }
    )
    barrier, entered, release = Barrier(2), Event(), Event()
    observe = pm_readback.observe_run
    probes = []

    def held_callback(run):
        probes.append(run)
        assert run == retry_cases.FAILED
        entered.set()
        assert release.wait(timeout=15)
        return observe(run)

    monkeypatch.setattr(pm_readback, "observe_run", held_callback)

    def send(body):
        barrier.wait(timeout=10)
        return client.post(retry_cases.PM + "resume-retry", headers=retry_cases.WRITER, json=body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(send, body) for body in (command, second)]
        try:
            assert entered.wait(timeout=10)
            # Prove that the competing real PG transaction is blocked while
            # the winner retains its task row lock across the native callback.
            deadline = time.monotonic() + 5
            with postgres.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
                while True:
                    blocked = connection.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            "WHERE datname=current_database() AND cardinality(pg_blocking_pids(pid)) > 0)"
                        )
                    ).scalar_one()
                    if blocked or time.monotonic() >= deadline:
                        break
                    time.sleep(0.02)
            assert blocked, "Expected an actual PostgreSQL lock wait, not sequential HTTP replay"
        finally:
            release.set()
        responses = [future.result(timeout=20) for future in futures]

    assert sorted(response.status_code for response in responses) == ([200, 200] if same_key else [200, 409])
    winner = next(response.json() for response in responses if response.status_code == 200)
    if same_key:
        assert responses[0].json() == responses[1].json()
    assert probes == [retry_cases.FAILED]
    after = retry_cases.stored()
    for name in ("tasks", "task_runtime_assignments", "task_step_history"):
        assert after[name] == before[name]
    for name in ("pm_runs", "pm_operations"):
        assert all(row in after[name] for row in before[name])
        assert len(after[name]) == len(before[name]) + 1
    assert winner["result"]["pending"]["version"] == command["expected_version"] + 1
    assert winner["result"]["pending"]["fence"] == command["expected_fence"] + 1
    assert winner["result"]["source"]["session_run_id"] == command["session_run_id"]
    assert winner["result"]["source"]["checkpoint_ref"] == command["checkpoint_ref"]
    saved = next(row for row in after["pm_operations"] if row["kind"] == "resume_retry")
    assert saved["operation_key"] == winner["result"]["operation_key"]
    assert saved["request_sha256"] == winner["result"]["request_sha256"]
    replay_command = command if saved["operation_key"] == command["operation_key"] else second
    assert (
        client.post(retry_cases.PM + "resume-retry", headers=retry_cases.WRITER, json=replay_command).json() == winner
    )
    assert probes == [retry_cases.FAILED] and retry_cases.stored() == after
