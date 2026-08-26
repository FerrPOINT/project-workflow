"""Integration tests against a real PostgreSQL instance.

These tests are skipped by default (`-m 'not integration'`).
Run them explicitly with:
    pytest -m integration tests/test_postgres_integration.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Barrier, Event, Thread, local
from unittest.mock import patch
from urllib.request import urlopen

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from project_workflow import config as config_module
from project_workflow.application.agent import AgentService
from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.phase_service import PhaseService
from project_workflow.application.project import ProjectService
from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.session import (
    ensure_migrated,
    ensure_schema,
    get_engine,
    reset_engine,
    run_alembic_command,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork

REPO_ROOT = Path(__file__).resolve().parents[1]

PG_HOST = os.environ.get("PGHOST", "localhost")
PG_PORT = int(os.environ.get("PGPORT", "5432"))
PG_USER = os.environ.get("PGUSER", "project_workflow")
PG_PASSWORD = os.environ.get("PGPASSWORD", "project_workflow")
PG_ADMIN_DB = os.environ.get("PGDATABASE", "project_workflow")


@pytest.fixture(scope="function")
def pg_url(monkeypatch):
    """Create a fresh PostgreSQL database and yield a SQLAlchemy URL for it."""
    if not PG_PASSWORD:
        pytest.skip("PGPASSWORD is not set")
    pid = os.getpid()
    db_name = f"project_workflow_test_{pid}"
    base_url = f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{db_name}"

    admin_conn = psycopg.connect(host=PG_HOST, port=PG_PORT, dbname=PG_ADMIN_DB, user=PG_USER, password=PG_PASSWORD)
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute("SET idle_in_transaction_session_timeout = 0")
        cur.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
        cur.execute(f"CREATE DATABASE {db_name}")
    admin_conn.close()

    monkeypatch.setenv("DATABASE_URL", base_url)
    monkeypatch.setenv("DB_SCHEMA", "project_workflow")
    config_module.get_settings.cache_clear()
    reset_engine()
    yield base_url

    reset_engine()
    admin_conn = psycopg.connect(host=PG_HOST, port=PG_PORT, dbname=PG_ADMIN_DB, user=PG_USER, password=PG_PASSWORD)
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
    admin_conn.close()


@pytest.mark.integration
class TestPostgresInitialMigration:
    def test_get_engine_postgresql(self, pg_url):
        engine = get_engine(pg_url)
        assert engine.dialect.name == "postgresql"
        assert engine.url.database == pg_url.rsplit("/", 1)[-1]

    def test_fresh_upgrade_matches_orm_metadata(self, pg_url):
        from project_workflow.infrastructure.db.models import Base
        from project_workflow.infrastructure.db.session import migration_head, schema_is_ready

        engine = get_engine(pg_url)
        ensure_migrated(engine)
        ensure_migrated(engine)

        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names(schema="project_workflow"))
        assert actual_tables - {"alembic_version"} == set(Base.metadata.tables)
        for table_name, table in Base.metadata.tables.items():
            actual_columns = {
                column["name"] for column in inspector.get_columns(table_name, schema="project_workflow")
            }
            assert actual_columns == set(table.columns.keys()), table_name

        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn,
                opts={"compare_type": True, "compare_server_default": True},
            )
            assert compare_metadata(context, Base.metadata) == []

        with engine.connect() as conn:
            version = conn.execute(
                text("SELECT version_num FROM project_workflow.alembic_version")
            ).scalar_one()
        assert version == migration_head() == "0001_initial"
        assert schema_is_ready(engine) is True

    def test_downgrade_and_reupgrade(self, pg_url):
        from project_workflow.infrastructure.db.models import Base

        engine = get_engine(pg_url)
        ensure_migrated(engine)
        run_alembic_command("downgrade", engine, "base")

        tables_after_downgrade = set(
            inspect(engine).get_table_names(schema="project_workflow")
        )
        assert tables_after_downgrade.isdisjoint(Base.metadata.tables)
        assert "project_workflow" not in inspect(engine).get_schema_names()

        ensure_migrated(engine)
        assert "project_workflow" in inspect(engine).get_schema_names()
        assert set(Base.metadata.tables).issubset(
            inspect(engine).get_table_names(schema="project_workflow")
        )

    def test_legacy_revision_is_refused_without_mutation(self, pg_url):
        from project_workflow.infrastructure.db.session import (
            DatabaseRecreateRequired,
            database_revisions,
        )

        engine = get_engine(pg_url)
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA project_workflow"))
            conn.execute(
                text(
                    "CREATE TABLE project_workflow.alembic_version "
                    "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO project_workflow.alembic_version(version_num) "
                    "VALUES ('e6a4c2d8b901')"
                )
            )
            conn.execute(text("CREATE TABLE project_workflow.keep_me (id INTEGER PRIMARY KEY)"))

        with pytest.raises(DatabaseRecreateRequired, match="Несовместимую базу данных необходимо пересоздать"):
            ensure_migrated(engine)

        assert database_revisions(engine) == {"e6a4c2d8b901"}
        assert inspect(engine).has_table("keep_me", schema="project_workflow")

    def test_head_with_column_drift_is_not_ready(self, pg_url):
        from project_workflow.infrastructure.db.session import DatabaseRecreateRequired, schema_is_ready

        engine = get_engine(pg_url)
        ensure_migrated(engine)
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE project_workflow.projects ADD COLUMN unexpected_column TEXT"))

        assert schema_is_ready(engine) is False
        with pytest.raises(DatabaseRecreateRequired):
            ensure_migrated(engine)

    def test_initial_constraints_and_phase_scoped_fingerprint(self, pg_url):
        engine = get_engine(pg_url)
        ensure_migrated(engine)
        with engine.begin() as conn:
            workflow_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.workflows "
                    "(name, description, is_default) VALUES ('W', '', 1) RETURNING id"
                )
            ).scalar_one()
            project_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.projects "
                    "(workflow_id, code, name, description, key_prefixes) "
                    "VALUES (:workflow_id, 'P', 'Project', 'persisted', '[\"P\"]') RETURNING id"
                ),
                {"workflow_id": workflow_id},
            ).scalar_one()
            phase_ids = [
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.phases "
                        "(workflow_id, code, name, phase_order) "
                        "VALUES (:workflow_id, :code, :name, :phase_order) RETURNING id"
                    ),
                    {
                        "workflow_id": workflow_id,
                        "code": str(order),
                        "name": f"Phase {order}",
                        "phase_order": order,
                    },
                ).scalar_one()
                for order in (1, 2)
            ]
            task_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.tasks "
                    "(project_id, workflow_id, task_key, current_phase, status) "
                    "VALUES (:project_id, :workflow_id, 'P-1', '1', 'active') RETURNING id"
                ),
                {"project_id": project_id, "workflow_id": workflow_id},
            ).scalar_one()
            for phase_id in phase_ids:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.supervisor_runs "
                        "(task_id, phase_id, verdict, report_fingerprint) "
                        "VALUES (:task_id, :phase_id, 'partial', 'same')"
                    ),
                    {"task_id": task_id, "phase_id": phase_id},
                )

        with engine.connect() as conn:
            description = conn.execute(
                text("SELECT description FROM project_workflow.projects WHERE id = :id"),
                {"id": project_id},
            ).scalar_one()
        assert description == "persisted"

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.phases "
                        "(workflow_id, code, name, phase_order) "
                        "VALUES (:workflow_id, 'bad', 'Bad', 0)"
                    ),
                    {"workflow_id": workflow_id},
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.instructions "
                        "(phase_id, step_num, description) VALUES (:phase_id, 0, 'Bad')"
                    ),
                    {"phase_id": phase_ids[0]},
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.supervisor_runs "
                        "(task_id, phase_id, verdict, report_fingerprint) "
                        "VALUES (:task_id, :phase_id, 'partial', 'same')"
                    ),
                    {"task_id": task_id, "phase_id": phase_ids[0]},
                )
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM project_workflow.phases WHERE id = :phase_id"),
                    {"phase_id": phase_ids[0]},
                )

    def test_bootstrap_is_idempotent(self, pg_url):
        from scripts.init_db import main

        assert main() == 0
        assert main() == 0

        engine = get_engine(pg_url)
        with engine.connect() as conn:
            counts = {
                table: conn.execute(
                    text(f"SELECT count(*) FROM project_workflow.{table}")
                ).scalar_one()
                for table in ("workflows", "projects", "agents", "phases")
            }
            default_projects = conn.execute(
                text("SELECT count(*) FROM project_workflow.projects WHERE code = 'RUN'")
            ).scalar_one()
        assert all(count > 0 for count in counts.values())
        assert default_projects == 1

    def test_two_concurrent_init_processes_are_idempotent(self, pg_url):
        env = os.environ.copy()
        env.update(
            {
                "DATABASE_URL": pg_url,
                "DB_SCHEMA": "project_workflow",
                "PYTHONUTF8": "1",
            }
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: _run_process(["-m", "scripts.init_db"], env), range(2)))
        assert [result.returncode for result in results] == [0, 0], [
            result.stderr or result.stdout for result in results
        ]

        uow = SAUnitOfWork(pg_url)
        assert [project.code for project in uow.projects.list()].count("RUN") == 1
        assert len([workflow for workflow in uow.workflows.list() if workflow.is_default]) == 1
        uow.close()

    def test_supervisor_concurrent_get_or_create_returns_one_task(self, pg_url):
        from project_workflow.supervisor import SupervisorEngine
        from scripts.init_db import main

        assert main() == 0
        barrier = Barrier(2)
        thread_state = local()
        original_get = TaskService.get_task_by_key

        def synchronized_first_get(service, task_key):
            if not getattr(thread_state, "initial_lookup_done", False):
                thread_state.initial_lookup_done = True
                barrier.wait(timeout=10)
            return original_get(service, task_key)

        def create() -> int:
            uow = SAUnitOfWork(pg_url)
            try:
                return int(SupervisorEngine("RUN-90001", uow=uow).task["id"])
            finally:
                uow.close()

        with (
            patch.object(TaskService, "get_task_by_key", synchronized_first_get),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            task_ids = list(pool.map(lambda _: create(), range(2)))

        assert task_ids[0] == task_ids[1]
        verify = SAUnitOfWork(pg_url)
        assert len([task for task in verify.tasks.list() if task.task_key == "RUN-90001"]) == 1
        verify.close()

    def test_orm_create_all_is_rejected_for_postgresql(self, pg_url):
        engine = get_engine(pg_url)
        with pytest.raises(RuntimeError, match="изолированных тестах SQLite"):
            ensure_schema(engine)
@pytest.mark.integration
class TestPostgresUoW:
    def test_create_and_read_workflow_project_task(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        uow = SAUnitOfWork(pg_url)
        with uow:
            wf_id = uow.workflows.create({"name": "Test Workflow", "description": "Test", "is_default": True})
            workflows = {w.name: w.id for w in uow.workflows.list()}
            assert workflows.get("Test Workflow") == wf_id

            proj_id = uow.projects.create({"workflow_id": wf_id, "code": "TST", "name": "Default"})
            projects = {p.code: p.id for p in uow.projects.list()}
            assert projects.get("TST") == proj_id

            task_id = uow.tasks.create(
                {
                    "project_id": proj_id,
                    "workflow_id": wf_id,
                    "task_key": "TST-1",
                    "title": "First task",
                    "current_phase": "start",
                }
            )
            tasks = {t.task_key: t.id for t in uow.tasks.list()}
            assert tasks.get("TST-1") == task_id
            uow.commit()

    def test_repository_list_reads_have_deterministic_id_order(self, pg_url):
        from scripts.init_db import main

        assert main() == 0
        uow = SAUnitOfWork(pg_url)
        workflow = uow.workflows.get_default()
        assert workflow is not None and workflow.id is not None
        phase = uow.phases.get_by_code(int(workflow.id), "1.INTAKE")
        assert phase is not None and phase.id is not None
        project = uow.projects.list()[0]
        uow.projects.create(
            {
                "workflow_id": int(workflow.id),
                "code": "ORDERING",
                "name": "Ordering project",
                "description": "",
                "key_prefixes": ["ORD"],
            }
        )
        task_id = uow.tasks.create(
            {
                "project_id": int(project.id),
                "workflow_id": int(workflow.id),
                "task_key": "RUN-ORDER",
                "title": "Ordering test",
                "current_phase": phase.code,
            }
        )
        history_phases = list(uow.phases.list(int(workflow.id)))[:3]
        for history_phase in history_phases:
            assert history_phase.id is not None
            uow.tasks.add_history(task_id, int(history_phase.id), "pending")

        uow.session.execute(text("CREATE INDEX checks_desc_test_idx ON checks (id DESC)"))
        uow.session.execute(text("CREATE INDEX evidence_desc_test_idx ON evidence (id DESC)"))
        uow.session.execute(text("CREATE INDEX task_history_desc_test_idx ON task_history (id DESC)"))
        uow.session.execute(text("CREATE INDEX agents_desc_test_idx ON agents (id DESC)"))
        uow.session.execute(text("CREATE INDEX projects_desc_test_idx ON projects (id DESC)"))
        uow.commit()
        uow.session.execute(text("CLUSTER checks USING checks_desc_test_idx"))
        uow.session.execute(text("CLUSTER evidence USING evidence_desc_test_idx"))
        uow.session.execute(text("CLUSTER task_history USING task_history_desc_test_idx"))
        uow.session.execute(text("CLUSTER agents USING agents_desc_test_idx"))
        uow.session.execute(text("CLUSTER projects USING projects_desc_test_idx"))
        uow.commit()
        uow.session.execute(text("SET LOCAL enable_indexscan = off"))
        uow.session.execute(text("SET LOCAL enable_bitmapscan = off"))

        phase_checks = list(uow.phases.get_checks(int(phase.id)))
        phase_evidence = list(uow.phases.get_evidence(int(phase.id)))
        checks = list(uow.checks.list(int(phase.id)))
        evidence = list(uow.evidence.list(int(phase.id)))
        history = list(uow.tasks.get_history(task_id))
        batch_history = list(uow.tasks.get_history_batch([task_id])[task_id])
        agents = list(uow.agents.list())
        projects = list(uow.projects.list())

        assert [row["id"] for row in phase_checks] == sorted(row["id"] for row in phase_checks)
        assert [row["id"] for row in phase_evidence] == sorted(row["id"] for row in phase_evidence)
        assert [row["id"] for row in checks] == sorted(row["id"] for row in checks)
        assert [row["id"] for row in evidence] == sorted(row["id"] for row in evidence)
        assert [row["id"] for row in history] == sorted(row["id"] for row in history)
        assert [row["id"] for row in batch_history] == sorted(row["id"] for row in batch_history)
        assert [agent.id for agent in agents] == sorted(agent.id for agent in agents)
        assert [item.id for item in projects] == sorted(item.id for item in projects)
        uow.close()

    def test_ensure_phase_catalog_does_not_overwrite_existing_workflow(self, pg_url):
        from project_workflow.infrastructure.db import schema as schema_module

        ensure_migrated(get_engine(pg_url))
        uow = SAUnitOfWork(pg_url)
        with uow:
            default_wf_id = uow.workflows.create({"name": "Default", "description": "default", "is_default": True})
            uow.projects.create({"workflow_id": default_wf_id, "code": "DEFAULT", "name": "Default Project"})
            uow.commit()

        schema_module.ensure_phase_catalog(uow)
        with uow:
            default_wf = uow.workflows.get_default()
            phases = uow.phases.list(workflow_id=default_wf.id)
            assert phases == []

    def test_uow_commit_and_rollback(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        uow = SAUnitOfWork(pg_url)
        with uow:
            wf_id = uow.workflows.create({"name": "Rollback WF", "description": "rollback"})
            uow.rollback()

        with uow:
            ids = {w.id for w in uow.workflows.list()}
            assert wf_id not in ids

    def test_concurrent_task_and_prefix_update_cannot_break_project_invariants(self, pg_url):
        from scripts.init_db import main

        assert main() == 0
        setup = SAUnitOfWork(pg_url)
        project = ProjectService(setup).create_project(
            {"code": "RACE", "name": "Race", "key_prefixes": ["RACE"]}
        )
        setup.close()
        barrier = Barrier(2)

        def create_task() -> str:
            uow = SAUnitOfWork(pg_url)
            barrier.wait()
            try:
                TaskService(uow).create_task(
                    {"project_id": project["id"], "task_key": "RACE-1", "title": "Race"}
                )
                return "created"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        def update_prefix() -> str:
            uow = SAUnitOfWork(pg_url)
            barrier.wait()
            try:
                ProjectService(uow).update_project(project["id"], {"key_prefixes": ["NEW"]})
                return "updated"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            task_result = pool.submit(create_task)
            update_result = pool.submit(update_prefix)
            outcomes = {task_result.result(), update_result.result()}
        assert "rejected" in outcomes

        verify = SAUnitOfWork(pg_url)
        stored_project = verify.projects.get_by_id(project["id"])
        stored_task = verify.tasks.get_by_key("RACE-1")
        assert stored_project is not None
        if stored_task is None:
            assert stored_project.key_prefixes == ["NEW"]
        else:
            assert stored_project.key_prefixes == ["RACE"]
        verify.close()

    def test_concurrent_project_creates_serialize_prefix_namespace(self, pg_url):
        from scripts.init_db import main

        assert main() == 0
        barrier = Barrier(2)

        def create(code: str) -> str:
            uow = SAUnitOfWork(pg_url)
            barrier.wait()
            try:
                ProjectService(uow).create_project(
                    {"code": code, "name": code, "key_prefixes": ["SHARED"]}
                )
                return "created"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(create, ["PREFIX-A", "PREFIX-B"]))
        assert sorted(outcomes) == ["created", "rejected"]

    def test_task_creation_serializes_with_phase_deletion(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        workflow_id = setup.workflows.create({"name": "Phase race", "description": ""})
        first_id = setup.phases.create(
            {"workflow_id": workflow_id, "code": "race.first", "name": "First", "phase_order": 1}
        )
        setup.phases.create(
            {"workflow_id": workflow_id, "code": "race.second", "name": "Second", "phase_order": 2}
        )
        setup.commit()
        project = ProjectService(setup).create_project(
            {
                "workflow_id": workflow_id,
                "code": "PHASE-RACE",
                "name": "Phase race",
                "key_prefixes": ["PHASERACE"],
            }
        )
        setup.close()

        task_holds_workflow_lock = Event()
        delete_started_lock = Event()
        release_task = Event()

        def create_task() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lookup = uow.phases.get_by_code

            def paused_lookup(workflow_id_arg: int, code: str):
                task_holds_workflow_lock.set()
                assert release_task.wait(10)
                return original_lookup(workflow_id_arg, code)

            uow.phases.get_by_code = paused_lookup
            try:
                TaskService(uow).create_task(
                    {
                        "project_id": project["id"],
                        "task_key": "PHASERACE-1",
                        "current_phase": "race.first",
                    }
                )
                return "created"
            finally:
                uow.close()

        def delete_phase() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.workflows.lock

            def observed_lock(workflow_id_arg: int):
                delete_started_lock.set()
                return original_lock(workflow_id_arg)

            uow.workflows.lock = observed_lock
            try:
                PhaseServiceApp(uow).delete_phase(first_id)
                return "deleted"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            task_result = pool.submit(create_task)
            assert task_holds_workflow_lock.wait(10)
            delete_result = pool.submit(delete_phase)
            assert delete_started_lock.wait(10)
            release_task.set()
            assert task_result.result(timeout=20) == "created"
            assert delete_result.result(timeout=20) == "rejected"

        verify = SAUnitOfWork(pg_url)
        assert verify.tasks.get_by_key("PHASERACE-1") is not None
        assert verify.phases.get_by_id(first_id) is not None
        verify.close()

    @pytest.mark.parametrize("operation", ["project", "phase"])
    def test_workflow_delete_serializes_with_dependent_creation(self, pg_url, operation):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        workflow = WorkflowService(setup).create_workflow({"name": f"Delete race {operation}"})
        workflow_id = int(workflow["id"])
        setup.close()

        creator_holds_workflow_lock = Event()
        delete_started_lock = Event()
        release_creator = Event()

        def create_dependent() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.workflows.lock

            def paused_lock(workflow_id_arg: int):
                locked = original_lock(workflow_id_arg)
                creator_holds_workflow_lock.set()
                assert release_creator.wait(10)
                return locked

            uow.workflows.lock = paused_lock
            try:
                if operation == "project":
                    ProjectService(uow).create_project(
                        {
                            "workflow_id": workflow_id,
                            "code": "DELETE-RACE",
                            "name": "Delete race",
                            "key_prefixes": ["DELETERACE"],
                        }
                    )
                else:
                    PhaseServiceApp(uow).create_phase(
                        {
                            "workflow_id": workflow_id,
                            "code": "delete.race.phase",
                            "name": "Delete race phase",
                            "phase_order": 2,
                        }
                    )
                return "created"
            finally:
                uow.close()

        def delete_workflow() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.workflows.lock

            def observed_lock(workflow_id_arg: int):
                delete_started_lock.set()
                return original_lock(workflow_id_arg)

            uow.workflows.lock = observed_lock
            try:
                WorkflowService(uow).delete_workflow(workflow_id)
                return "deleted"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            create_result = pool.submit(create_dependent)
            assert creator_holds_workflow_lock.wait(10)
            delete_result = pool.submit(delete_workflow)
            assert delete_started_lock.wait(10)
            release_creator.set()
            assert create_result.result(timeout=20) == "created"
            assert delete_result.result(timeout=20) == "rejected"

        verify = SAUnitOfWork(pg_url)
        assert verify.workflows.get_by_id(workflow_id) is not None
        if operation == "project":
            assert verify.projects.get_by_code("DELETE-RACE") is not None
        else:
            assert verify.phases.get_by_code(workflow_id, "delete.race.phase") is not None
        verify.close()

    def test_project_move_serializes_with_task_creation(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        source = WorkflowService(setup).create_workflow({"name": "Move race source"})
        target = WorkflowService(setup).create_workflow({"name": "Move race target"})
        project = ProjectService(setup).create_project(
            {
                "workflow_id": source["id"],
                "code": "MOVE-RACE",
                "name": "Move race",
                "key_prefixes": ["MOVERACE"],
            }
        )
        setup.close()

        task_holds_workflow_lock = Event()
        move_started_lock = Event()
        release_task = Event()

        def create_task() -> str:
            uow = SAUnitOfWork(pg_url)
            original_project_lock = uow.projects.lock

            def paused_project_lock(project_id_arg: int):
                locked = original_project_lock(project_id_arg)
                task_holds_workflow_lock.set()
                assert release_task.wait(10)
                return locked

            uow.projects.lock = paused_project_lock
            try:
                TaskService(uow).create_task(
                    {"project_id": project["id"], "task_key": "MOVERACE-1"}
                )
                return "created"
            finally:
                uow.close()

        def move_project() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.workflows.lock

            def observed_lock(workflow_id_arg: int):
                move_started_lock.set()
                return original_lock(workflow_id_arg)

            uow.workflows.lock = observed_lock
            try:
                ProjectService(uow).update_project(
                    project["id"], {"workflow_id": target["id"]}
                )
                return "moved"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            task_result = pool.submit(create_task)
            assert task_holds_workflow_lock.wait(10)
            move_result = pool.submit(move_project)
            assert move_started_lock.wait(10)
            release_task.set()
            assert task_result.result(timeout=20) == "created"
            assert move_result.result(timeout=20) == "rejected"

        verify = SAUnitOfWork(pg_url)
        stored_project = verify.projects.get_by_id(project["id"])
        assert stored_project is not None and stored_project.workflow_id == source["id"]
        assert verify.tasks.get_by_key("MOVERACE-1") is not None
        verify.close()

    def test_agent_assignment_serializes_with_delete(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        workflow = WorkflowService(setup).create_workflow({"name": "Agent assignment race"})
        phase = setup.phases.list(int(workflow["id"]))[0]
        agent = AgentService(setup).create_agent({"name": "Race agent"})
        setup.close()

        assignment_holds_agent = Event()
        delete_started = Event()
        release_assignment = Event()

        def assign() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.agents.lock

            def paused_lock(agent_id: int):
                locked = original_lock(agent_id)
                assignment_holds_agent.set()
                assert release_assignment.wait(10)
                return locked

            uow.agents.lock = paused_lock
            try:
                PhaseServiceApp(uow).update_phase(int(phase.id), {"agent_id": int(agent["id"])})
                return "assigned"
            finally:
                uow.close()

        def delete() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.agents.lock

            def observed_lock(agent_id: int):
                delete_started.set()
                return original_lock(agent_id)

            uow.agents.lock = observed_lock
            try:
                AgentService(uow).delete_agent(int(agent["id"]))
                return "deleted"
            except ConflictError:
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            assignment_result = pool.submit(assign)
            assert assignment_holds_agent.wait(10)
            delete_result = pool.submit(delete)
            assert delete_started.wait(10)
            release_assignment.set()
            assert assignment_result.result(timeout=20) == "assigned"
            assert delete_result.result(timeout=20) == "rejected"

        verify = SAUnitOfWork(pg_url)
        assert verify.agents.get_by_id(int(agent["id"])) is not None
        assert verify.phases.get_by_id(int(phase.id)).agent_id == agent["id"]
        verify.close()

    @pytest.mark.parametrize("operation", ["create", "update"])
    def test_concurrent_hermes_profile_claim_is_domain_conflict(self, pg_url, operation):
        ensure_migrated(get_engine(pg_url))
        agent_ids: list[int] = []
        if operation == "update":
            setup = SAUnitOfWork(pg_url)
            agent_ids = [
                int(AgentService(setup).create_agent({"name": f"Profile owner {index}"})["id"])
                for index in range(2)
            ]
            setup.close()
        barrier = Barrier(2)

        def claim(index: int) -> str:
            uow = SAUnitOfWork(pg_url)
            repository_method = uow.agents.create if operation == "create" else uow.agents.update

            def synchronized_write(*args, **kwargs):
                barrier.wait(timeout=10)
                return repository_method(*args, **kwargs)

            if operation == "create":
                uow.agents.create = synchronized_write
            else:
                uow.agents.update = synchronized_write
            try:
                if operation == "create":
                    AgentService(uow).create_agent(
                        {"name": f"Concurrent profile {index}", "hermes_profile": "shared-race-profile"}
                    )
                else:
                    AgentService(uow).update_agent(
                        agent_ids[index], {"hermes_profile": "shared-race-profile"}
                    )
                return "saved"
            except ConflictError:
                return "conflict"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, range(2)))

        assert sorted(results) == ["conflict", "saved"]
        verify = SAUnitOfWork(pg_url)
        assert len([agent for agent in verify.agents.list() if agent.hermes_profile == "shared-race-profile"]) == 1
        verify.close()

    def test_catalog_mutation_during_supervisor_provider_call_fails_closed(self, pg_url):
        from project_workflow.infrastructure.llm import OpenAICompatibleClient
        from project_workflow.supervisor import SupervisorEngine
        from scripts.init_db import main

        assert main() == 0
        provider_started = Event()
        release_provider = Event()

        def provider(*_args, **kwargs):
            provider_started.set()
            assert release_provider.wait(10)
            return _pass_response(str(kwargs["user"]))

        def evaluate() -> dict:
            uow = SAUnitOfWork(pg_url)
            try:
                with patch.object(OpenAICompatibleClient, "chat", side_effect=provider):
                    return SupervisorEngine("RUN-90002", uow=uow).evaluate("done")
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            result_future = pool.submit(evaluate)
            assert provider_started.wait(10)
            mutation = SAUnitOfWork(pg_url)
            workflow = mutation.workflows.get_default()
            assert workflow is not None and workflow.id is not None
            phase = mutation.phases.get_by_code(int(workflow.id), "1.INTAKE")
            assert phase is not None and phase.id is not None
            checks = [dict(row) for row in mutation.phases.get_checks(int(phase.id))]
            checks.append({"description": "Concurrent PostgreSQL catalog check"})
            PhaseService(mutation).update_phase_detail(int(phase.id), {"checks": checks})
            mutation.close()
            release_provider.set()
            result = result_future.result(timeout=20)

        assert result["verdict"] == "BLOCKED"
        assert result["retryable"] is True
        verify = SAUnitOfWork(pg_url)
        task = verify.tasks.get_by_key("RUN-90002")
        assert task is not None and task.status == "blocked" and task.current_phase == "1.INTAKE"
        run = verify.supervisor_runs.list(task_key="RUN-90002", limit=1)[0]
        assert run.verdict == "blocked"
        assert run.report_fingerprint is None
        verify.close()

    def test_task_delete_waits_for_supervisor_commit(self, pg_url):
        from project_workflow.infrastructure.llm import OpenAICompatibleClient
        from project_workflow.supervisor import SupervisorEngine
        from scripts.init_db import main

        assert main() == 0
        evaluation_holds_workflow = Event()
        allow_evaluation_commit = Event()
        delete_started = Event()
        delete_finished = Event()

        def evaluate() -> dict:
            uow = SAUnitOfWork(pg_url)
            original_create_run = uow.create_supervisor_run

            def paused_create_run(*args, **kwargs):
                evaluation_holds_workflow.set()
                assert allow_evaluation_commit.wait(10)
                return original_create_run(*args, **kwargs)

            uow.create_supervisor_run = paused_create_run
            try:
                with patch.object(
                    OpenAICompatibleClient,
                    "chat",
                    side_effect=lambda *_args, **kwargs: _pass_response(str(kwargs["user"])),
                ):
                    return SupervisorEngine("RUN-90003", uow=uow).evaluate("done")
            finally:
                uow.close()

        def delete() -> str:
            uow = SAUnitOfWork(pg_url)
            try:
                task = uow.tasks.get_by_key("RUN-90003")
                assert task is not None and task.id is not None
                delete_started.set()
                TaskService(uow).delete_task(int(task.id))
                return "deleted"
            finally:
                delete_finished.set()
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            evaluation_result = pool.submit(evaluate)
            assert evaluation_holds_workflow.wait(10)
            deletion_result = pool.submit(delete)
            assert delete_started.wait(10)
            deletion_was_serialized = not delete_finished.wait(0.5)
            allow_evaluation_commit.set()
            evaluated = evaluation_result.result(timeout=20)
            deleted = deletion_result.result(timeout=20)

        assert deletion_was_serialized
        assert evaluated["verdict"] == "PASS"
        assert deleted == "deleted"

    def test_assigned_agent_update_waits_for_supervisor_commit(self, pg_url):
        from project_workflow.infrastructure.llm import OpenAICompatibleClient
        from project_workflow.supervisor import SupervisorEngine
        from scripts.init_db import main

        assert main() == 0
        setup = SAUnitOfWork(pg_url)
        workflow = setup.workflows.get_default()
        assert workflow is not None and workflow.id is not None
        phase = setup.phases.get_by_code(int(workflow.id), "1.INTAKE")
        assert phase is not None and phase.agent_id is not None
        agent_id = int(phase.agent_id)
        setup.close()

        evaluation_holds_workflow = Event()
        allow_evaluation_commit = Event()
        update_started = Event()
        update_finished = Event()

        def evaluate() -> dict:
            uow = SAUnitOfWork(pg_url)
            original_create_run = uow.create_supervisor_run

            def paused_create_run(*args, **kwargs):
                evaluation_holds_workflow.set()
                assert allow_evaluation_commit.wait(10)
                return original_create_run(*args, **kwargs)

            uow.create_supervisor_run = paused_create_run
            try:
                with patch.object(
                    OpenAICompatibleClient,
                    "chat",
                    side_effect=lambda *_args, **kwargs: _pass_response(str(kwargs["user"])),
                ):
                    return SupervisorEngine("RUN-90004", uow=uow).evaluate("done")
            finally:
                uow.close()

        def update_agent() -> str:
            uow = SAUnitOfWork(pg_url)
            try:
                update_started.set()
                AgentService(uow).update_agent(agent_id, {"name": "Обновлённый агент"})
                return "updated"
            finally:
                update_finished.set()
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            evaluation_result = pool.submit(evaluate)
            assert evaluation_holds_workflow.wait(10)
            update_result = pool.submit(update_agent)
            assert update_started.wait(10)
            update_was_serialized = not update_finished.wait(0.5)
            allow_evaluation_commit.set()
            evaluated = evaluation_result.result(timeout=20)
            updated = update_result.result(timeout=20)

        assert update_was_serialized
        assert evaluated["verdict"] == "PASS"
        assert updated == "updated"
        verify = SAUnitOfWork(pg_url)
        agent = verify.agents.get_by_id(agent_id)
        assert agent is not None and agent.name == "Обновлённый агент"
        verify.close()

    @pytest.mark.parametrize("operation", ["update", "delete", "reorder"])
    def test_instruction_mutation_serializes_with_phase_update(self, pg_url, operation):
        ensure_migrated(get_engine(pg_url))
        setup = SAUnitOfWork(pg_url)
        workflow = WorkflowService(setup).create_workflow({"name": f"Instruction race {operation}"})
        phase = setup.phases.list(int(workflow["id"]))[0]
        first = InstructionService(setup).create_instruction(int(phase.id), {"description": "first"})
        second = InstructionService(setup).create_instruction(int(phase.id), {"description": "second"})
        setup.close()

        instruction_holds_workflow = Event()
        phase_update_started = Event()
        release_instruction = Event()

        def mutate_instruction() -> str:
            uow = SAUnitOfWork(pg_url)
            repository_method = getattr(uow.instructions, operation)

            def paused_write(*args, **kwargs):
                instruction_holds_workflow.set()
                assert release_instruction.wait(10)
                return repository_method(*args, **kwargs)

            setattr(uow.instructions, operation, paused_write)
            try:
                service = InstructionService(uow)
                if operation == "update":
                    service.update_instruction(int(first["id"]), {"description": "updated"})
                elif operation == "delete":
                    service.delete_instruction(int(first["id"]))
                else:
                    service.reorder_instructions(
                        int(phase.id), [int(second["id"]), int(first["id"])]
                    )
                return "instruction-saved"
            finally:
                uow.close()

        def mutate_phase() -> str:
            uow = SAUnitOfWork(pg_url)
            original_lock = uow.workflows.lock

            def observed_lock(workflow_id: int):
                phase_update_started.set()
                return original_lock(workflow_id)

            uow.workflows.lock = observed_lock
            try:
                PhaseServiceApp(uow).update_phase(int(phase.id), {"name": f"Phase after {operation}"})
                return "phase-saved"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            instruction_result = pool.submit(mutate_instruction)
            assert instruction_holds_workflow.wait(10)
            phase_result = pool.submit(mutate_phase)
            assert phase_update_started.wait(10)
            release_instruction.set()
            assert instruction_result.result(timeout=20) == "instruction-saved"
            assert phase_result.result(timeout=20) == "phase-saved"

        verify = SAUnitOfWork(pg_url)
        assert verify.phases.get_by_id(int(phase.id)).name == f"Phase after {operation}"
        rows = list(verify.instructions.list(int(phase.id)))
        if operation == "update":
            assert rows[0]["description"] == "updated"
        elif operation == "delete":
            assert [row["step_num"] for row in rows] == [1]
            assert rows[0]["id"] == second["id"]
        else:
            assert [row["id"] for row in rows] == [second["id"], first["id"]]
        verify.close()


def _pass_response(user_prompt: str) -> dict:
    item_ids = []
    for line in user_prompt.splitlines():
        stripped = line.strip()
        if stripped.startswith('ID: "') and '" — ' in stripped:
            item_ids.append(stripped[5:].split('" — ', 1)[0])
    return {
        "verdict": "PASS",
        "covered": item_ids,
        "missing": [],
        "blockers": [],
        "message": "ok",
        "confidence": 1.0,
    }


def _prepare_concurrent_task(pg_url: str, task_key: str) -> None:
    from project_workflow.infrastructure.db import schema
    from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

    engine = get_engine(pg_url)
    ensure_migrated(engine)
    uow = SAUnitOfWork(engine)
    schema.ensure_phase_catalog(uow)
    bootstrap_default_project(uow)
    project = uow.projects.get_by_code("RUN")
    phase = uow.phases.list(workflow_id=project.workflow_id)[0]
    uow.tasks.create(
        {
            "project_id": project.id,
            "workflow_id": project.workflow_id,
            "task_key": task_key,
            "current_phase": phase.code,
        }
    )
    uow.commit()
    uow.close()


@pytest.mark.integration
@pytest.mark.parametrize("same_report", [True, False])
def test_concurrent_reports_create_one_transition_and_run(pg_url, same_report):
    from project_workflow.supervisor import SupervisorEngine

    task_key = "RUN-90005"
    _prepare_concurrent_task(pg_url, task_key)
    barrier = Barrier(2)

    def evaluate(report: str):
        uow = SAUnitOfWork(pg_url)
        engine = SupervisorEngine(task_key, uow=uow, create_if_missing=False)
        barrier.wait()
        try:
            return engine.evaluate(report)
        finally:
            uow.close()

    reports = ["same report", "same report" if same_report else "different report"]
    with (
        patch(
            "project_workflow.supervisor.evaluate.OpenAICompatibleClient.chat",
            side_effect=lambda *_args, **kwargs: _pass_response(kwargs["user"]),
        ),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(evaluate, reports))

    uow = SAUnitOfWork(pg_url)
    task = uow.tasks.get_by_key(task_key)
    runs = uow.supervisor_runs.list(task_id=task.id)
    history = uow.tasks.get_history(task.id)
    uow.close()

    assert len(runs) == 1
    assert history
    assert sum(result["verdict"] == "PASS" for result in results) == (2 if same_report else 1)
    if same_report:
        assert sum(result["replayed"] is True for result in results) == 1
    else:
        assert sum(result["verdict"] == "BLOCKED" and result["retryable"] is True for result in results) == 1


@pytest.mark.integration
def test_concurrent_distinct_partial_reports_do_not_apply_stale_snapshot(pg_url):
    from project_workflow.supervisor import SupervisorEngine

    task_key = "RUN-90006"
    _prepare_concurrent_task(pg_url, task_key)
    start = Barrier(2)
    providers = Barrier(2)

    def partial_response(user_prompt: str) -> dict:
        response = _pass_response(user_prompt)
        response["verdict"] = "PARTIAL"
        response["missing"] = response.pop("covered")
        response["covered"] = []
        response["message"] = "partial"
        return response

    def provider(*_args, **kwargs):
        providers.wait(timeout=10)
        return partial_response(str(kwargs["user"]))

    def evaluate(report: str) -> dict:
        uow = SAUnitOfWork(pg_url)
        try:
            engine = SupervisorEngine(task_key, uow=uow, create_if_missing=False)
            start.wait(timeout=10)
            return engine.evaluate(report)
        finally:
            uow.close()

    with (
        patch("project_workflow.supervisor.evaluate.OpenAICompatibleClient.chat", side_effect=provider),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = list(pool.map(evaluate, ["first partial", "second partial"]))

    assert sorted(result["verdict"] for result in results) == ["BLOCKED", "PARTIAL"]
    blocked = next(result for result in results if result["verdict"] == "BLOCKED")
    assert blocked["retryable"] is True
    verify = SAUnitOfWork(pg_url)
    task = verify.tasks.get_by_key(task_key)
    assert task is not None
    assert len(verify.supervisor_runs.list(task_id=task.id)) == 1
    assert len(verify.tasks.get_history(task.id)) == 1
    verify.close()


class _ProviderState:
    def __init__(self) -> None:
        self.chat_requests: list[dict] = []
        self.chat_phases: list[str] = []
        self.model_requests = 0


@contextmanager
def _openai_compatible_server():
    state = _ProviderState()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/v1/models":
                self._send_json(404, {"error": "not found"})
                return
            state.model_requests += 1
            self._send_json(200, {"object": "list", "data": [{"id": "e2e-contract-model"}]})

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self._send_json(404, {"error": "not found"})
                return
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            state.chat_requests.append(payload)
            user_prompt = str(payload["messages"][-1]["content"])
            phase_line = next(line for line in user_prompt.splitlines() if line.startswith("CURRENT PHASE:"))
            state.chat_phases.append(phase_line.split(":", 1)[1].split(" — ", 1)[0].strip())
            item_ids = [
                line.strip()[5:].split('" — ', 1)[0]
                for line in user_prompt.splitlines()
                if line.strip().startswith('ID: "') and '" — ' in line
            ]

            if "MODE=HTTP_ERROR" in user_prompt:
                self._send_json(503, {"error": "provider unavailable"})
                return
            if "MODE=INVALID" in user_prompt:
                content = "not-json"
            else:
                verdict = "PASS"
                covered = item_ids
                missing: list[str] = []
                blockers: list[str] = []
                if "MODE=PARTIAL" in user_prompt:
                    verdict, covered, missing = "PARTIAL", item_ids[:1], item_ids[1:] or item_ids
                elif "MODE=BLOCKED" in user_prompt:
                    verdict, covered, missing, blockers = "BLOCKED", [], item_ids, ["Controlled test blocker"]
                elif "MODE=ROLLBACK" in user_prompt:
                    verdict, covered, missing = "ROLLBACK", [], item_ids
                elif "MODE=DELEGATE" in user_prompt:
                    verdict, covered, missing = "DELEGATE", [], item_ids
                content = json.dumps(
                    {
                        "verdict": verdict,
                        "covered": covered,
                        "missing": missing,
                        "blockers": blockers,
                        "message": f"Controlled {verdict}",
                        "confidence": 1.0,
                    }
                )
            self._send_json(
                200,
                {
                    "id": "chatcmpl-e2e",
                    "object": "chat.completion",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
                },
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _cli_env(pg_url: str, provider_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": pg_url,
            "DB_SCHEMA": "project_workflow",
            "OPENAI_BASE_URL": provider_url,
            "OPENAI_MODEL": "e2e-contract-model",
            "OPENAI_TIMEOUT": "10",
            "OPENAI_API_KEY": "integration-test-key",
            "PYTHONUTF8": "1",
        }
    )
    env.pop("PYTHONIOENCODING", None)
    return env


def _run_process(
    args: list[str], env: dict[str, str], *, encoding: str = "utf-8"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding=encoding,
        timeout=60,
        check=False,
    )


def _run_cli(env: dict[str, str], *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = _run_process(["-m", "project_workflow.interfaces.cli", *args], env)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"CLI did not return JSON: stdout={result.stdout!r}, stderr={result.stderr!r}") from exc
    return result, payload


def _initialize_cli_database(env: dict[str, str]) -> None:
    # Module execution keeps the checkout root first on sys.path.  This matters
    # when the test reuses a dependency environment whose editable install may
    # point at another worktree.
    result = _run_process(["-m", "scripts.init_db"], env)
    assert result.returncode == 0, result.stderr or result.stdout


def _step(env: dict[str, str], task_key: str, report: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    return _run_cli(env, "--json", "step", "--task", task_key, "--report", report)


@pytest.mark.integration
@pytest.mark.timeout(240)
def test_full_supervisor_runtime_through_cli_postgres_and_http(pg_url):
    expected_phases = [
        "1.INTAKE",
        "2.REQUIREMENTS",
        "3.DOR_GATE",
        "4.START",
        "5.RESEARCH",
        "6.SOLUTION",
        "7.PLAN_GATE",
        "8.IMPLEMENT",
        "9.PR",
        "10.REVIEW",
        "11.RUNTIME",
        "12.RELEASE_GATE",
        "13.DELIVERY",
        "14.CLOSE",
        "15.RETRO",
    ]
    expected_groups = {
        "5.RESEARCH": ["5.RESEARCH", "5.PREFLIGHT"],
        "6.SOLUTION": ["6.SOLUTION", "6.TEST_PLAN"],
        "10.REVIEW": ["10.REVIEW", "10.QA", "10.DATAFLOW"],
    }
    task_key = "RUN-82001"

    with _openai_compatible_server() as (provider_url, provider_state):
        env = _cli_env(pg_url, provider_url)
        _initialize_cli_database(env)
        with urlopen(f"{provider_url}/models", timeout=5) as response:
            assert response.status == 200

        bootstrap_uow = SAUnitOfWork(pg_url)
        try:
            workflows = list(bootstrap_uow.workflows.list())
            projects = list(bootstrap_uow.projects.list())
            assert [workflow.name for workflow in workflows] == [config_module.DEFAULT_WORKFLOW_NAME]
            assert [project.code for project in projects] == ["RUN"]
            assert len(bootstrap_uow.phases.list(workflow_id=workflows[0].id)) == 19
        finally:
            bootstrap_uow.close()

        assignment_result, assignment = _run_cli(env, "--json", "step", "--task", task_key)
        assert assignment_result.returncode == 0
        assert assignment["prompt"]
        assignment_contract = assignment["phase_contract"]
        assert assignment_contract["phase_code"] == "1.INTAKE"
        assert assignment_contract["phase_name"] == "Приём задачи"
        assert assignment_contract["workflow_revision"] == "sdlc-business-tech-v1"
        assert assignment_contract["actor"] == "hermes"
        assert assignment_contract["skills"] == [
            "project-workflow-executor",
            "relevanter-business-operator",
        ]
        assert assignment_contract["execution_type"] == "sync"
        assert assignment_contract["delegate_agent"] == "orchestrator"
        assert assignment_contract["hermes_profile"] == "sdlc-orchestrator"
        assert assignment_contract["group_phases"] is None

        first_report = "E2E report 1 for phase 1.INTAKE"
        for index, expected_phase in enumerate(expected_phases, start=1):
            report = first_report if index == 1 else f"E2E report {index} for phase {expected_phase}"
            result, payload = _step(env, task_key, report)
            assert result.returncode == 0, result.stderr or result.stdout
            assert payload["verdict"] == "PASS"
            assert payload["phase"] == expected_phase
            assert payload["group_phases"] == expected_groups.get(expected_phase)

            if expected_phase == "5.RESEARCH":
                assert payload["next_phase"] == "6.SOLUTION"
                assert payload["next_phase_contract"]["group_phases"] == [
                    "6.SOLUTION",
                    "6.TEST_PLAN",
                ]
                assert [
                    detail["hermes_profile"]
                    for detail in payload["next_phase_contract"]["group_details"]
                ] == ["sdlc-orchestrator", "sdlc-critic"]
                assert "workflow-writing-plans" in payload["next_phase_contract"]["skills"]
                assert any(
                    "workflow-code-intelligence" in instruction
                    for instruction in payload["next_phase_contract"]["instructions"]
                )
                uow = SAUnitOfWork(pg_url)
                task = uow.tasks.get_by_key(task_key)
                assert task is not None
                phases = {phase.id: phase.code for phase in uow.phases.list(workflow_id=task.workflow_id)}
                statuses = {phases[row["phase_id"]]: row["status"] for row in uow.tasks.get_history(task.id)}
                assert task.current_phase == "6.SOLUTION"
                assert statuses["6.SOLUTION"] == "pending"
                assert statuses.get("6.TEST_PLAN") != "done"
                uow.close()

            if expected_phase == "6.SOLUTION":
                assert payload["next_phase"] == "7.PLAN_GATE"

            if expected_phase == "7.PLAN_GATE":
                assert payload["next_phase_contract"]["group_phases"] is None
                assert any(
                    "test-driven-development" in instruction
                    for instruction in payload["next_phase_contract"]["instructions"]
                )

        terminal_result, terminal = _run_cli(env, "--json", "step", "--task", task_key)
        history_result, history_payload = _run_cli(env, "--json", "history", "--task", task_key)
        assert terminal_result.returncode == history_result.returncode == 0
        assert terminal["phase"] == "15.RETRO"
        assert terminal["next_phase"] is None
        assert terminal["phase_contract"]["hermes_profile"] == "sdlc-critic"
        assert terminal["status"] == "done"
        assert history_payload["count"] == 15

        completed_request_count = len(provider_state.chat_requests)
        completed_result, completed = _step(env, task_key, "New report after workflow completion")
        assert completed_result.returncode == 0
        assert completed["verdict"] == "PASS"
        assert completed["status"] == "done"
        assert completed["next_phase"] is None
        assert "уже завершён" in completed["message"]
        assert len(provider_state.chat_requests) == completed_request_count

        human_env = env.copy()
        human_env.update({"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1251"})
        human_step = _run_process(
            ["-m", "project_workflow.interfaces.cli", "step", "--task", task_key],
            human_env,
            encoding="cp1251",
        )
        assert human_step.returncode == 0
        assert "Улучшения" in human_step.stdout
        assert "UnicodeEncodeError" not in human_step.stderr

        assert provider_state.model_requests == 1
        assert len(provider_state.chat_requests) == 15
        assert provider_state.chat_phases == expected_phases
        assert all(request["model"] == "e2e-contract-model" for request in provider_state.chat_requests)
        assert all(
            request["response_format"] == {"type": "json_object"}
            for request in provider_state.chat_requests
        )

    uow = SAUnitOfWork(pg_url)
    task = uow.tasks.get_by_key(task_key)
    runs = list(uow.supervisor_runs.list(task_id=task.id, limit=100))
    task_history = list(uow.tasks.get_history(task.id))
    assert task.current_phase == "15.RETRO"
    assert task.status == "done"
    assert len(runs) == 15
    assert len(task_history) == 19
    assert all(row["status"] == "done" for row in task_history)
    fingerprints = [run.report_fingerprint for run in runs]
    assert all(fingerprints)
    assert len(set(fingerprints)) == 15
    assert all(run.context_snapshot["model"] == "e2e-contract-model" for run in runs)
    assert all(run.context_snapshot["endpoint_mode"] == "openai-compatible" for run in runs)
    assert all(run.context_snapshot["prompt_version"] == "supervisor-evaluator-v7" for run in runs)
    assert all(run.context_snapshot["contract_snapshot"]["evaluation_items"] for run in runs)
    assert all(run.context_snapshot["raw_evaluator"]["verdict"] == "PASS" for run in runs)
    uow.close()


def _advance_to_phase(env: dict[str, str], task_key: str, phases: list[str]) -> None:
    for index, phase in enumerate(phases, start=1):
        result, payload = _step(env, task_key, f"Advance {index} through {phase}")
        assert result.returncode == 0
        assert payload["verdict"] == "PASS"
        assert payload["phase"] == phase


@pytest.mark.integration
@pytest.mark.timeout(240)
def test_cli_verdicts_replay_and_fail_closed_through_postgres_and_http(pg_url):
    with _openai_compatible_server() as (provider_url, provider_state):
        env = _cli_env(pg_url, provider_url)
        _initialize_cli_database(env)

        first_cross_result, first_cross = _step(env, "RUN-82008", "identical cross-phase report")
        second_cross_result, second_cross = _step(env, "RUN-82008", "identical cross-phase report")
        assert first_cross_result.returncode == second_cross_result.returncode == 0
        assert first_cross["phase"] != second_cross["phase"]
        assert first_cross["replayed"] is second_cross["replayed"] is False

        partial_result, partial = _step(env, "RUN-82002", "MODE=PARTIAL incomplete report")
        request_count = len(provider_state.chat_requests)
        progress_result, progress = _step(env, "RUN-82002", "MODE=PARTIAL incomplete report")
        stable_request_count = len(provider_state.chat_requests)
        replay_result, replay = _step(env, "RUN-82002", "MODE=PARTIAL incomplete report")
        assert partial_result.returncode == progress_result.returncode == replay_result.returncode == 0
        assert partial["verdict"] == progress["verdict"] == replay["verdict"] == "PARTIAL"
        assert progress["replayed"] is False
        assert stable_request_count == request_count + 1
        assert replay["replayed"] is True
        assert len(provider_state.chat_requests) == stable_request_count

        blocked_result, blocked = _step(env, "RUN-82003", "MODE=BLOCKED blocked report")
        assert blocked_result.returncode == 1
        assert blocked["verdict"] == "BLOCKED"
        assert blocked["retryable"] is False

        invalid_result, invalid = _step(env, "RUN-82004", "MODE=INVALID invalid response")
        invalid_retry_result, invalid_retry = _step(env, "RUN-82004", "MODE=INVALID invalid response")
        assert invalid_result.returncode == invalid_retry_result.returncode == 1
        assert invalid["verdict"] == invalid_retry["verdict"] == "BLOCKED"
        assert invalid["retryable"] is invalid_retry["retryable"] is True
        assert invalid["replayed"] is invalid_retry["replayed"] is False

        http_result, http_error = _step(env, "RUN-82005", "MODE=HTTP_ERROR provider error")
        assert http_result.returncode == 1
        assert http_error["verdict"] == "BLOCKED"
        assert http_error["retryable"] is True

        phases_before_rollback = [
            "1.INTAKE",
            "2.REQUIREMENTS",
            "3.DOR_GATE",
            "4.START",
            "5.RESEARCH",
            "6.SOLUTION",
            "7.PLAN_GATE",
            "8.IMPLEMENT",
            "9.PR",
        ]
        _advance_to_phase(env, "RUN-82006", phases_before_rollback)
        rollback_result, rollback = _step(
            env, "RUN-82006", "MODE=ROLLBACK return to implementation"
        )
        assert rollback_result.returncode == 0
        assert rollback["verdict"] == "ROLLBACK"
        assert rollback["rollback_target"] == "8.IMPLEMENT"

        _advance_to_phase(env, "RUN-82007", phases_before_rollback)
        delegate_result, delegate = _step(env, "RUN-82007", "MODE=DELEGATE hand off review")
        assert delegate_result.returncode == 0
        assert delegate["verdict"] == "DELEGATE"

    uow = SAUnitOfWork(pg_url)
    partial_task = uow.tasks.get_by_key("RUN-82002")
    blocked_task = uow.tasks.get_by_key("RUN-82003")
    invalid_task = uow.tasks.get_by_key("RUN-82004")
    http_task = uow.tasks.get_by_key("RUN-82005")
    rollback_task = uow.tasks.get_by_key("RUN-82006")
    delegate_task = uow.tasks.get_by_key("RUN-82007")
    assert (partial_task.current_phase, partial_task.status) == ("1.INTAKE", "active")
    assert (blocked_task.current_phase, blocked_task.status) == ("1.INTAKE", "blocked")
    assert (invalid_task.current_phase, invalid_task.status) == ("1.INTAKE", "blocked")
    assert (http_task.current_phase, http_task.status) == ("1.INTAKE", "blocked")
    assert (rollback_task.current_phase, rollback_task.status) == ("8.IMPLEMENT", "active")
    assert (delegate_task.current_phase, delegate_task.status) == ("10.REVIEW", "active")
    invalid_runs = list(uow.supervisor_runs.list(task_id=invalid_task.id, limit=10))
    assert len(invalid_runs) == 2
    assert all(run.report_fingerprint is None for run in invalid_runs)
    assert [item["status"] for item in uow.tasks.get_history(invalid_task.id)] == ["blocked"]
    assert [item["status"] for item in uow.tasks.get_history(http_task.id)] == ["blocked"]
    uow.close()
