"""Upgrade sealed historical PM data without replaying a retired native writer."""

import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, create_engine, inspect, select, text

from project_workflow.infrastructure.db.session import database_revisions, ensure_migrated, run_alembic_command

CURRENT_RUN = "11111111-1111-4111-8111-111111111111"


def test_pm_review_migration_preserves_populated_execution_and_history(tmp_path):
    url = f"sqlite:///{tmp_path / 'retained-pm.db'}"
    engine = create_engine(url)
    try:
        run_alembic_command("upgrade", engine, "0014_launch_profile_only")
        legacy = MetaData()
        legacy.reflect(bind=engine)
        with engine.begin() as connection:
            def insert(table_name, **values):
                table = legacy.tables[table_name]
                return connection.execute(table.insert().values(**values).returning(table.c.id)).scalar_one()

            workflow = insert("workflows", key="historical:pm", name="Historical PM", description="", is_default=1)
            mode = insert("workflow_modes", workflow_id=workflow, key="default", name="Historical", mode_order=1)
            project = insert("projects", workflow_id=workflow, code="OLD", name="Old namespace", cli_command="old")
            phase = insert("phases", workflow_id=workflow, mode_id=mode, code="OLD-01", name="Old", phase_order=1)
            task = insert("tasks", workflow_id=workflow, mode_id=mode, project_id=project, task_key="OLD-1",
                          current_phase_id=phase, status="done", assignment_revision=1,
                          assignment_operation_key="old:assignment")
            assignment = insert("task_runtime_assignments", operation_key="old:assignment", task_id=task,
                                project_id=project, workflow_id=workflow, mode_id=mode, cycle_number=0,
                                assignment_revision=1, payload='{"retained":"original legacy body"}')
            history = insert("task_step_history", task_id=task, workflow_id=workflow, mode_id=mode, phase_id=phase,
                             verdict="pass", worker_report="Retained historical report")
            insert("task_phase_events", task_id=task, workflow_id=workflow, mode_id=mode, phase_id=phase,
                   step_history_id=history, event_type="completed")
            # Schema-preservation fixtures, not authenticated runtime/assignment proof.
            connection.execute(legacy.tables["pm_executions"].insert().values(
                execution_ref="old:execution", task_id=task, assignment_id=assignment,
                tracker_instance_ref="tracker:one",
                tracker_project_ref="old:project", task_ref="old:task", root_ref="old:task", agent_ref="old:agent",
                session_run_id=CURRENT_RUN, identity_json='{"retained":"identity"}', state="active",
                version=1, fence=1, phase_id=phase,
            ))
            connection.execute(legacy.tables["pm_runs"].insert().values(
                session_run_id=CURRENT_RUN, run_ref="old:run", execution_ref="old:execution", binding_ref="old:binding",
                fence=1, observation_json='{"retained":"observation"}', terminal_json='{"retained":"terminal"}',
            ))
            connection.execute(legacy.tables["pm_operations"].insert().values(
                operation_key="old:bind", execution_ref="old:execution", kind="bind", request_sha256="a" * 64,
                result_json='{"retained":"original result"}',
            ))
        tables = {name: table for name, table in legacy.tables.items() if name != "alembic_version"}
        with engine.connect() as connection:
            frozen = {name: connection.execute(select(table)).mappings().all() for name, table in tables.items()}
        assert "uq_pm_task_agent" in {u["name"] for u in inspect(engine).get_unique_constraints("pm_executions")}
        ensure_migrated(engine)
        ensure_migrated(engine)
        assert database_revisions(engine) == {"0020_configured_cli_catalog"}
        assert "uq_pm_task_agent" not in {u["name"] for u in inspect(engine).get_unique_constraints("pm_executions")}
        assert "ix_pm_task_agent" in {i["name"] for i in inspect(engine).get_indexes("pm_executions")}
        with engine.connect() as connection:
            assert not connection.execute(text("PRAGMA foreign_key_check")).all()
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            for name, table in tables.items():
                assert connection.execute(select(table)).mappings().all() == frozen[name], name
            assert connection.execute(text("SELECT single_task_binding_json FROM task_runtime_assignments")).all() == [
                (None,),
            ]
        with pytest.raises(
            RuntimeError, match="Configured phase history is forward-only"
        ):
            run_alembic_command("downgrade", engine, "0014_launch_profile_only")
        assert database_revisions(engine) == {"0020_configured_cli_catalog"}
        with engine.connect() as connection:
            for name, table in tables.items():
                assert connection.execute(select(table)).mappings().all() == frozen[name], name
    finally:
        engine.dispose()


def test_migration_only_extends_kind_and_refuses_to_drop_retained_retry(tmp_path, monkeypatch):
    migration = importlib.import_module(
        "project_workflow.infrastructure.db.migrations.versions.0019_pm_terminal_resume_retry"
    )
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "kind-test.db"))
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE pm_operations (operation_key TEXT PRIMARY KEY, kind TEXT NOT NULL, "
            "CONSTRAINT ck_pm_operation_kind CHECK(kind IN ('bind','checkpoint','resume','rebind')))"
        )
        connection.exec_driver_sql("INSERT INTO pm_operations VALUES ('old:resume','resume')")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.exec_driver_sql("SELECT * FROM pm_operations").all() == [("old:resume", "resume")]
        connection.exec_driver_sql("INSERT INTO pm_operations VALUES ('new:retry','resume_retry')")
        with pytest.raises(RuntimeError, match="prevent downgrade"):
            migration.downgrade()
        assert connection.exec_driver_sql("SELECT count(*) FROM pm_operations").scalar() == 2
    engine.dispose()
