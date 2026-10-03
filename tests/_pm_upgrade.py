"""Rehydrate real legacy PM API fixture records into a published 0007 test schema."""

from typing import Any

from sqlalchemy import JSON, MetaData, select
from sqlalchemy.engine import Engine

from project_workflow import config
from project_workflow.infrastructure.db.session import ensure_migrated, get_engine, reset_engine


def snapshot_rows(engine: Engine) -> dict[str, list[dict[str, Any]]]:
    metadata = MetaData(schema=config.get_settings().DB_SCHEMA if engine.dialect.name == "postgresql" else None)
    with engine.connect() as connection:
        metadata.reflect(bind=connection)
        return {
            table.name: [dict(row) for row in connection.execute(
                select(table).order_by(*table.primary_key.columns)
            ).mappings()]
            for table in metadata.sorted_tables if table.name != "alembic_version"
        }


def capture_legacy_pm_records(monkeypatch, supervisor_llm, source_url: str, *, source_schema: str | None = None):
    from sqlalchemy.orm import close_all_sessions

    from tests.test_pm_execution import ADAPTER, BASE, NEW_RUN, RUNTIME, prepare_pm
    from tests.test_pm_execution_edges import test_resumed_supervisor_report_is_persistent_and_replayable

    try:
        with monkeypatch.context() as settings:
            settings.setenv("DATABASE_URL", source_url)
            if source_schema is not None:
                settings.setenv("DB_SCHEMA", source_schema)
            config.get_settings.cache_clear()
            reset_engine()
            ensure_migrated(get_engine())
            prepared = prepare_pm(settings)
            pm = next(prepared)
            try:
                test_resumed_supervisor_report_is_persistent_and_replayable(pm, supervisor_llm)
                client, identity = pm[:2]
                read = client.post(BASE + "/readback", headers=ADAPTER,
                                   json={**identity, "operation_key": "resume:1"})
                assert read.status_code == 200, read.text
                runtime = {**RUNTIME, "X-Workflow-Execution-Token": read.json()["execution_token"]}
                history = client.get("/internal/runtime/history", headers=runtime,
                                     params={"task": identity["task"], "session_run_id": NEW_RUN})
                assert history.status_code == 200, history.text
                rows = snapshot_rows(get_engine())
                assert len(rows["pm_executions"]) == 1 and rows["pm_executions"][0]["checkpoint_json"]
                assert len(rows["pm_runs"]) == 2 and len(rows["pm_operations"]) == 4
                assert rows["task_step_history"] and rows["task_phase_events"]
                assert all(row["assignment_shape"] is None for row in rows["task_runtime_assignments"])
                return rows, identity, read.json(), history.json()
            finally:
                pm[0].close()
                prepared.close()
                close_all_sessions()
                reset_engine()
    finally:
        config.get_settings.cache_clear()
        reset_engine()


def restore_0007_records(engine: Engine, rows: dict[str, list[dict[str, Any]]]) -> None:
    """Restore only compatible legacy rows, not a stamp or a lossy downgrade."""
    metadata = MetaData(schema=config.get_settings().DB_SCHEMA if engine.dialect.name == "postgresql" else None)
    with engine.begin() as connection:
        metadata.reflect(bind=connection)
        for table in metadata.sorted_tables:
            if table.name == "alembic_version" or not rows[table.name]:
                continue
            # Reflection otherwise serializes SQL NULL as JSON null on INSERT.
            for column in table.columns:
                if isinstance(column.type, JSON):
                    column.type = column.type.copy()
                    column.type.none_as_null = True
            records = []
            for row in rows[table.name]:
                extra = row.keys() - table.columns.keys()
                assert not extra or (table.name == "task_runtime_assignments"
                                     and extra == {"assignment_shape"} and row["assignment_shape"] is None)
                records.append({key: value for key, value in row.items() if key in table.columns})
            connection.execute(table.insert(), records)


def assert_0008_preserves_records(engine: Engine, before: dict[str, list[dict[str, Any]]]) -> None:
    after = snapshot_rows(engine)
    assert after.keys() == before.keys()
    for name, records in before.items():
        expected = records
        if name == "task_runtime_assignments":
            expected = [dict(row, assignment_shape=None) for row in records]
        assert after[name] == expected, name


def assert_upgraded_pm_readback(monkeypatch, identity, expected_read, expected_history):
    import json

    from fastapi.testclient import TestClient

    from project_workflow import build_provenance
    from project_workflow.interfaces.ui.app import create_app
    from project_workflow.interfaces.ui.routes import runtime_api
    from tests.test_pm_execution import ADAPTER, BASE, NEW_RUN, RUNTIME
    from tests.test_runtime_api import TEST_RUNTIME_COMPATIBILITY

    def descriptor(**_kwargs):
        return dict(TEST_RUNTIME_COMPATIBILITY)

    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor", descriptor)
    monkeypatch.setattr(runtime_api, "runtime_compatibility_descriptor", descriptor)
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"project_manager": "a" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"project_manager": "r" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_SCOPE_SECRET", "s" * 40)
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_URL", "http://runtime.test/readback")
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_TOKEN", "p" * 40)
    config.get_settings.cache_clear()
    # Match the legacy custom-namespace fixture: test routes, not managed startup readiness.
    client = TestClient(create_app())
    try:
        read = client.post(BASE + "/readback", headers=ADAPTER,
                           json={**identity, "operation_key": "resume:1"})
        assert read.status_code == 200, read.text
        assert read.json() == expected_read, (read.json(), expected_read)
        runtime = {**RUNTIME, "X-Workflow-Execution-Token": read.json()["execution_token"]}
        history = client.get("/internal/runtime/history", headers=runtime,
                             params={"task": identity["task"], "session_run_id": NEW_RUN})
        assert history.status_code == 200, history.text
        assert history.json() == expected_history, (history.json(), expected_history)
    finally:
        client.close()
