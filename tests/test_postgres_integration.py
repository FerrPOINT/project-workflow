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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Barrier, Event, Thread, local
from unittest.mock import patch

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import close_all_sessions

from project_workflow import config as config_module
from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.phase_service import PhaseService
from project_workflow.application.project import ProjectService
from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db import session as health_db_session
from project_workflow.infrastructure.db.managed_catalog import (
    ensure_managed_catalog,
    validate_managed_catalog_state,
)
from project_workflow.infrastructure.db.session import (
    database_revisions,
    ensure_migrated,
    ensure_schema,
    get_engine,
    migration_head,
    reset_engine,
    run_alembic_command,
    schema_is_ready,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.interfaces.ui.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.integration
def test_postgres_legacy_agent_archives_preserve_seven_agents_and_nineteen_links(pg_url):
    from tests.test_initial_migration import assert_populated_legacy_agent_archive_upgrade

    assert_populated_legacy_agent_archive_upgrade(get_engine(pg_url))


@pytest.mark.integration
def test_postgres_legacy_archive_and_released_migrations_roll_back_together(pg_url, monkeypatch):
    from tests.test_initial_migration import assert_legacy_archive_migration_rollback

    assert_legacy_archive_migration_rollback(get_engine(pg_url), monkeypatch)


@pytest.mark.integration
@pytest.mark.parametrize("failure", [
    "partial", "unguarded", "view", "changed_source", "foreign_column", "missing_guard",
])
def test_postgres_legacy_archive_refuses_foreign_partial_or_changed_without_overwrite(pg_url, failure):
    from tests.test_initial_migration import assert_legacy_archive_refusal

    assert_legacy_archive_refusal(get_engine(pg_url), failure)


@pytest.mark.integration
def test_postgres_legacy_archive_guard_loss_at_head_is_not_readiness(pg_url):
    from tests.test_initial_migration import assert_legacy_archive_guard_loss_holds_at_head

    assert_legacy_archive_guard_loss_holds_at_head(get_engine(pg_url))


@pytest.mark.integration
@pytest.mark.parametrize("scenario", ["appearance", "versioned-adoption"])
def test_current_base_initial_professions_and_history_preservation_on_postgres(pg_url, scenario):
    from tests.test_profession_initial_catalog import (
        assert_theme_migration_updates_only_untouched_managed_professions,
        test_adoption_preserves_profession_edits_old_tasks_history_and_user_collections,
    )
    engine = get_engine(pg_url)
    if scenario == "appearance":
        assert_theme_migration_updates_only_untouched_managed_professions(engine)
    else:
        ensure_migrated(engine)
        test_adoption_preserves_profession_edits_old_tasks_history_and_user_collections(
            engine, "base_sdlc_catalog_v1_frozen.json", "parallel",
        )


@pytest.mark.integration
def test_current_single_task_family_preserves_legacy_rows_and_history_on_postgres(pg_url):
    from hashlib import sha256

    from project_workflow.infrastructure.db.single_task_catalog import (
        ensure_single_task_catalog,
        observe_installation,
    )
    from scripts.build_single_task_profile import render
    from tests.test_single_task_installation import test_side_by_side_preserves_every_legacy_row_and_history

    catalog_bytes, manifest_bytes = render()
    engine = get_engine(pg_url)
    ensure_migrated(engine)
    test_side_by_side_preserves_every_legacy_row_and_history(engine)
    with SAUnitOfWork(engine) as uow:
        first = observe_installation(uow)
        assert first.workflow_catalog_sha256 == sha256(catalog_bytes).hexdigest()
        assert first.instruction_manifest_sha256 == sha256(manifest_bytes).hexdigest()
        assert [first.namespaces, first.workflows, first.modes, first.phases] == [7, 7, 8, 24]
        assert len({binding.namespace_id for binding in first.bindings}) == 7
        assert len({binding.workflow_id for binding in first.bindings}) == 7
        modes = [mode for binding in first.bindings for mode in binding.modes]
        assert len({mode.mode_id for mode in modes}) == 8
        assert len({phase_id for mode in modes for phase_id in mode.phase_ids}) == 24
    with SAUnitOfWork(engine) as uow:
        assert ensure_single_task_catalog(uow) == first
        uow.commit()
    with SAUnitOfWork(engine) as uow:
        assert observe_installation(uow) == first


@pytest.fixture
def pm_postgres(pg_url, monkeypatch):
    from tests._retained_pm_history import retained_pm

    ensure_migrated(get_engine(pg_url))
    yield from retained_pm(monkeypatch)


@pytest.mark.integration
def test_pm_ownership_concurrent_provision_replay_and_db_immutability(pm_postgres):
    from sqlalchemy.exc import DBAPIError

    from project_workflow.application.namespace_ownership import NamespaceOwnershipService
    from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest
    from project_workflow.infrastructure.db import models as m
    from project_workflow.infrastructure.namespace_auth import NamespacePrincipal
    from tests._retained_pm_history import PROJECT_REF

    with SAUnitOfWork() as uow:
        namespace_id = uow.projects.get_by_cli_command("workflow-project_manager").id
        before = dict(uow.projects.get_pm_ownership(namespace_id))
    request = NamespaceOwnershipRequest(contract_version=1, tracker_instance_ref="tracker:one",
                                        tracker_project_ref=PROJECT_REF)
    principal = NamespacePrincipal("http://auth.test", "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")
    barrier = Barrier(2)

    def provision(project_ref):
        barrier.wait(timeout=10)
        with SAUnitOfWork() as uow:
            try:
                return NamespaceOwnershipService(uow).provision(
                    namespace_id,
                    request.model_copy(
                        update={
                            "tracker_project_ref": project_ref,
                        }
                    ),
                    principal,
                )
            except ConflictError:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        same, foreign = list(pool.map(provision, [PROJECT_REF, "ffffffff-ffff-4fff-8fff-ffffffffffff"]))
    assert same[0].model_dump() == before and same[1] is False and foreign == "conflict"
    with SAUnitOfWork() as uow:
        assert dict(uow.projects.get_pm_ownership(namespace_id)) == before
        row = uow.session.scalar(select(m.PMNamespaceOwnership))
        for statement in [
            "UPDATE pm_namespace_ownership SET tracker_instance_ref='other'",
            "DELETE FROM pm_namespace_ownership",
        ]:
            with pytest.raises(DBAPIError, match="ownership is immutable"):
                uow.session.execute(text(statement))
            uow.rollback()
        with pytest.raises(IntegrityError):
            uow.projects.delete(namespace_id)
            uow.session.flush()
        uow.rollback()
        assert uow.session.get(m.PMNamespaceOwnership, row.ownership_ref) is not None


@pytest.mark.integration
@pytest.mark.parametrize("winner", ["bootstrap", "provision"])
def test_pm_ownership_catalog_lock_order_and_incomplete_schema(pg_url, winner):
    from project_workflow.application.namespace_ownership import NamespaceOwnershipService
    from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest
    from project_workflow.infrastructure.db.session import DatabaseRecreateRequired
    from project_workflow.infrastructure.namespace_auth import NamespacePrincipal

    engine = get_engine(pg_url)
    ensure_migrated(engine)
    with SAUnitOfWork(engine) as uow:
        ensure_managed_catalog(uow)
        namespace_id = uow.projects.get_by_cli_command("workflow-project_manager").id
    held, waiting, release = Event(), Event(), Event()

    def bootstrap():
        with SAUnitOfWork(engine) as uow:
            if winner == "bootstrap":
                uow.lock_catalog_state()
                held.set()
                assert release.wait(timeout=15)
            else:
                waiting.set()
            ensure_managed_catalog(uow)

    def provision():
        with SAUnitOfWork(engine) as uow:
            if winner == "provision":
                uow.lock_catalog_state(shared=True)
                uow.projects.lock_pm_namespace(namespace_id)
                held.set()
                assert release.wait(timeout=15)
            else:
                waiting.set()
            return NamespaceOwnershipService(uow).provision(namespace_id, NamespaceOwnershipRequest(
                contract_version=1, tracker_instance_ref="tracker:one",
                tracker_project_ref="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            ), NamespacePrincipal("http://auth.test", "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(bootstrap if winner == "bootstrap" else provision)
        try:
            assert held.wait(timeout=10)
            second = pool.submit(provision if winner == "bootstrap" else bootstrap)
            assert waiting.wait(timeout=10)
        finally:
            release.set()
        first_result, second_result = first.result(timeout=20), second.result(timeout=20)
        assert (second_result if winner == "bootstrap" else first_result)[1] is True
    with SAUnitOfWork(engine) as uow:
        assert validate_managed_catalog_state(uow) is True
    assert schema_is_ready(engine)
    # An old pending head is not silently repaired or stamped as the expanded head.
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE pm_namespace_ownership"))
    assert not schema_is_ready(engine)
    with pytest.raises(DatabaseRecreateRequired):
        ensure_migrated(engine)
    assert database_revisions(engine) == {"0021_profession_task_workflows"}


@pytest.mark.integration
def test_pm_ownership_postgres_actual_bounded_auth_and_readback(pg_url, monkeypatch):
    from tests.test_namespace_ownership import SUBJECT
    from tests.test_runtime_api import _namespace

    ensure_migrated(get_engine(pg_url))
    _namespace("PM", "workflow-project_manager", "PM")
    with SAUnitOfWork() as uow:
        namespace_id = uow.projects.get_by_cli_command("workflow-project_manager").id
    probes = []
    status = [200]
    scopes = [
        "project-workflow:read", "project-workflow:write",
        f"project-workflow:namespace-owner:provision:{namespace_id}",
        f"project-workflow:namespace-owner:read:{namespace_id}",
    ]

    class Auth(BaseHTTPRequestHandler):
        def do_GET(self):
            probes.append((self.path, self.headers.get("Authorization"), self.headers.get("Accept-Encoding")))
            body = json.dumps({"sub": SUBJECT, "email": "provisioner@test", "scopes": scopes}).encode()
            self.send_response(status[0])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Auth)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("AUTH_ISSUER", root)
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", root)
    monkeypatch.setenv("AUTH_SESSION_SECRET", "x" * 40)
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_PROVISIONER_SUBJECT", SUBJECT)
    config_module.get_settings.cache_clear()
    client = TestClient(create_app())
    headers = {"Authorization": "Bearer sdlc_pat_owned-qa-test-only"}
    payload = {"contract_version": 1, "tracker_instance_ref": "tracker:one",
               "tracker_project_ref": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"}
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    try:
        from project_workflow.infrastructure.db import models as m

        rejected = client.put(url, headers=headers, json={**payload, "tracker_instance_ref": "\u0416" * 65})
        assert rejected.status_code == 422 and probes == []
        unsupported = client.put(url, headers=headers, json=payload)
        assert unsupported.status_code == 403
        with SAUnitOfWork() as uow:
            assert uow.session.query(m.PMNamespaceOwnership).count() == 0
        scopes[:] = ["project-workflow:read", "project-workflow:write"]
        first = client.put(url, headers=headers, json=payload)
        assert first.status_code == 201, first.text
        assert first.json()["result"]["authority_issuer"] == root
        assert client.put(url, headers=headers, json=payload).json() == first.json()
        assert client.get(url, headers=headers).json() == first.json()
        status[0] = 401
        denied = client.get(url, headers=headers)
        assert denied.status_code == 401 and "sdlc_pat_" not in denied.text and root not in denied.text
        assert probes == [("/auth/tokens/introspect", headers["Authorization"], "identity")] * 5
    finally:
        client.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


PG_HOST = os.environ.get("PGHOST", "127.0.0.1")
PG_PORT = int(os.environ.get("PGPORT", "5432"))
PG_USER = os.environ.get("PGUSER", "project_workflow")
PG_PASSWORD = os.environ.get("PGPASSWORD", "project_workflow")
PG_ADMIN_DB = os.environ.get("PGDATABASE", "project_workflow")
PG_CONNECT_TIMEOUT = int(os.environ.get("PGCONNECT_TIMEOUT", "10"))


@pytest.fixture(autouse=True)
def packaged_pg_test_runtime(monkeypatch):
    from project_workflow import build_provenance
    from tests.test_runtime_assignment_contract import TEST_RUNTIME_COMPATIBILITY
    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor", lambda: dict(TEST_RUNTIME_COMPATIBILITY))


def _runtime_binding(operation_key: str) -> dict[str, object]:
    from tests.test_runtime_assignment_contract import TEST_RUNTIME_COMPATIBILITY
    return {
        "runtime_compatibility": dict(TEST_RUNTIME_COMPATIBILITY),
        "workflow_key": "hermes-sdlc:developer",
        "role_key": "developer",
        "stage_key": "development",
        "execution_scope": "delivery",
        "attempt_number": 1,
        "business_task_ref": f"business-task:{operation_key}",
        "root_task_ref": "business-task:root",
        "work_item_ref": f"work-item:{operation_key}",
        "work_item_revision": 1,
        "queue_item_ref": f"queue-item:{operation_key}",
        "task_workspace_ref": "task-workspace:root",
        "workspace_revision": 1,
        "tech_execution_workspace_ref": f"tech-workspace:{operation_key}",
        "tech_execution_attempt_ref": f"tech-attempt:{operation_key}",
        "decomposition_revision_ref": "decomposition:1",
        "stage_revision": "developer:1",
        "assignment_ref": f"assignment:{operation_key}",
        "workspace_generation": 1,
        "lease_generation": 1,
        "exact_input_refs": [
            {"kind": "business_task", "ref": f"business-task:{operation_key}", "revision": "1"}
        ],
    }




def _fixture_default_mode(connection, workflow_id: int) -> int:
    """Build a valid head-schema mode for tests exercising raw SQL constraints."""
    return int(
        connection.execute(
            text(
                "INSERT INTO project_workflow.workflow_modes "
                "(workflow_id, key, name, mode_order) "
                "VALUES (:workflow_id, 'default', 'Default', 1) RETURNING id"
            ),
            {"workflow_id": workflow_id},
        ).scalar_one()
    )


@pytest.fixture(scope="function")
def pg_url(monkeypatch):
    """Create a fresh PostgreSQL database and yield a SQLAlchemy URL for it."""
    if not PG_PASSWORD:
        pytest.skip("PGPASSWORD is not set")
    pid = os.getpid()
    db_name = f"project_workflow_test_{pid}"
    base_url = f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{db_name}"

    admin_conn = psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_ADMIN_DB,
        user=PG_USER,
        password=PG_PASSWORD,
        connect_timeout=PG_CONNECT_TIMEOUT,
    )
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

    # The autouse UoW tracker tears down after this fixture. Close active
    # sessions before DROP DATABASE so its cleanup never sees AdminShutdown.
    close_all_sessions()
    reset_engine()
    admin_conn = psycopg.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_ADMIN_DB,
        user=PG_USER,
        password=PG_PASSWORD,
        connect_timeout=PG_CONNECT_TIMEOUT,
    )
    admin_conn.autocommit = True
    with admin_conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
    admin_conn.close()


@pytest.mark.integration
def test_namespace_defaults_upgrade_preserves_catalog_on_postgres(pg_url, tmp_path):
    from tests.test_namespace_default_migration import assert_upgrade_preserves_catalog

    assert_upgrade_preserves_catalog(get_engine(pg_url), tmp_path)


@pytest.mark.integration
def test_profession_collection_upgrade_preserves_history_on_postgres(pg_url):
    from tests.test_profession_execution_membership_migration import (
        assert_populated_upgrade_preserves_collection_history,
    )

    assert_populated_upgrade_preserves_collection_history(get_engine(pg_url))


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
        assert version == migration_head() == "0021_profession_task_workflows"
        assert schema_is_ready(engine) is True

    def test_managed_bootstrap_serializes_with_public_catalog_creation(self, pg_url):
        engine = get_engine(pg_url)
        ensure_migrated(engine)
        bootstrap_locked = Event()
        mutation_started = Event()

        def bootstrap() -> None:
            with SAUnitOfWork(engine) as uow:
                uow.lock_catalog_state()
                bootstrap_locked.set()
                assert mutation_started.wait(timeout=10)
                ensure_managed_catalog(uow)

        def create_user_workflow() -> str:
            assert bootstrap_locked.wait(timeout=10)
            mutation_started.set()
            with SAUnitOfWork(engine) as uow:
                WorkflowService(uow).create_workflow({"name": "User workflow"})
            return "saved"

        with ThreadPoolExecutor(max_workers=2) as pool:
            bootstrap_future = pool.submit(bootstrap)
            mutation_future = pool.submit(create_user_workflow)
            bootstrap_future.result(timeout=30)
            mutation_result = mutation_future.result(timeout=30)

        assert mutation_result == "saved"
        with SAUnitOfWork(engine) as uow:
            assert len(uow.workflows.list()) == 8
            assert any(workflow.name == "User workflow" for workflow in uow.workflows.list())
            assert uow.projects.get_by_cli_command("workflow-project_manager") is not None

    def test_installed_instruction_edit_survives_migration_restart(self, pg_url, monkeypatch):
        from scripts import init_db

        ensure_migrated(get_engine(pg_url))
        with SAUnitOfWork(pg_url) as uow:
            ensure_managed_catalog(uow)
            workflow = next(item for item in uow.workflows.list() if item.key == "hermes-sdlc:architect")
            mode = uow.workflows.list_modes(workflow.id)[0]
            phase = uow.phases.list(workflow.id, mode_id=mode.id)[0]
            instruction = uow.phase_instructions.list(phase.id)[0]
            instruction_id = instruction["id"]
            InstructionService(uow).update_instruction(instruction_id, {"description": "Saved on PostgreSQL"})

        monkeypatch.setenv("DATABASE_URL", pg_url)
        config_module.get_settings.cache_clear()
        assert init_db.main() == 0
        with SAUnitOfWork(pg_url) as readback:
            assert readback.phase_instructions.get_by_id(instruction_id)["description"] == "Saved on PostgreSQL"

    def test_public_catalog_mutation_blocks_managed_bootstrap_until_commit(self, pg_url):
        engine = get_engine(pg_url)
        ensure_migrated(engine)
        mutation_locked = Event()
        bootstrap_started = Event()
        bootstrap_finished = Event()
        release_mutation = Event()

        def mutate() -> str:
            with SAUnitOfWork(engine) as uow:
                original_create = uow.workflows.create

                def paused_create(data):
                    workflow_id = original_create(data)
                    mutation_locked.set()
                    assert release_mutation.wait(timeout=10)
                    return workflow_id

                uow.workflows.create = paused_create
                WorkflowService(uow).create_workflow({"name": "Existing unmanaged workflow"})
            return "committed"

        def bootstrap() -> str:
            assert mutation_locked.wait(timeout=10)
            with SAUnitOfWork(engine) as uow:
                original_lock = uow.lock_catalog_state

                def observed_lock(*, shared=False):
                    bootstrap_started.set()
                    return original_lock(shared=shared)

                uow.lock_catalog_state = observed_lock
                try:
                    ensure_managed_catalog(uow)
                except ValueError:
                    return "foreign-catalog-rejected"
                finally:
                    bootstrap_finished.set()
            return "initialized"

        with ThreadPoolExecutor(max_workers=2) as pool:
            mutation_future = pool.submit(mutate)
            bootstrap_future = pool.submit(bootstrap)
            try:
                assert bootstrap_started.wait(timeout=10)
                assert not bootstrap_finished.wait(timeout=0.2)
            finally:
                release_mutation.set()
            assert mutation_future.result(timeout=20) == "committed"
            assert bootstrap_future.result(timeout=20) == "initialized"

        with SAUnitOfWork(engine) as uow:
            workflows = list(uow.workflows.list())
            assert len(workflows) == 8
            assert any(workflow.name == "Existing unmanaged workflow" for workflow in workflows)
            assert validate_managed_catalog_state(uow) is True

    @pytest.mark.parametrize("revision,message", [
        ("0003_runtime_assignment_bind", "Downgrade from runtime assignment bind"),
        ("0004_wide_work_item_revision", "Downgrade from wide Business revisions"),
        ("0008_pm_execution", "PM execution downgrade refused"),
        ("0009_pm_draft_assignment", "PM Draft assignment downgrade refused"),
        ("0016_human_project_commit_guard", "Human policy requires a compatible guarded rollback cohort"),
        ("0017_human_application_clock", "Application policy requires a compatible guarded rollback cohort"),
        ("0018_identity_deletion_owner", "Identity lifecycle requires guarded cohort rollback"),
    ])
    def test_downgrade_refuses_lossy_mode_collapse(self, pg_url, revision, message):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, revision)
        with pytest.raises(RuntimeError, match=message):
            run_alembic_command("downgrade", engine, "base")
        assert database_revisions(engine) == {revision}
        assert schema_is_ready(engine) is (revision == migration_head())

    def test_populated_0001_upgrade_preserves_rows_and_backfills_per_workflow(self, pg_url):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, "0001_initial")
        with engine.begin() as conn:
            workflow_ids = [
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.workflows (name, description, is_default) "
                        "VALUES (:name, '', 0) RETURNING id"
                    ),
                    {"name": f"Legacy PG {suffix}"},
                ).scalar_one()
                for suffix in ("A", "B")
            ]
            for index, workflow_id in enumerate(workflow_ids, 1):
                phase_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.phases "
                        "(workflow_id, code, name, phase_order, execution_type) "
                        "VALUES (:workflow_id, :code, 'Legacy', 1, 'sync') RETURNING id"
                    ),
                    {"workflow_id": workflow_id, "code": f"legacy-{index}"},
                ).scalar_one()
                project_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.projects "
                        "(workflow_id, code, name, description, theme_icon, theme_color, cli_command, key_prefixes) "
                        "VALUES (:workflow_id, :code, 'Legacy', '', 'folder', '#5E6AD2', :cli, '[]') RETURNING id"
                    ),
                    {"workflow_id": workflow_id, "code": f"LPG{index}", "cli": f"legacy-pg-{index}"},
                ).scalar_one()
                task_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.tasks "
                        "(project_id, workflow_id, task_key, title, current_phase_id, status) "
                        "VALUES (:project_id, :workflow_id, :task_key, 'Legacy', :phase_id, 'active') RETURNING id"
                    ),
                    {
                        "project_id": project_id,
                        "workflow_id": workflow_id,
                        "task_key": f"LPG{index}-1",
                        "phase_id": phase_id,
                    },
                ).scalar_one()
                history_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_step_history "
                        "(task_id, workflow_id, phase_id, verdict, replay_fingerprint) "
                        "VALUES (:task_id, :workflow_id, :phase_id, 'partial', :fingerprint) RETURNING id"
                    ),
                    {
                        "task_id": task_id,
                        "workflow_id": workflow_id,
                        "phase_id": phase_id,
                        "fingerprint": f"legacy-pg-{index}",
                    },
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_phase_events "
                        "(task_id, workflow_id, phase_id, step_history_id, event_type) "
                        "VALUES (:task_id, :workflow_id, :phase_id, :history_id, 'entered')"
                    ),
                    {"task_id": task_id, "workflow_id": workflow_id, "phase_id": phase_id, "history_id": history_id},
                )

        run_alembic_command("upgrade", engine)
        with engine.connect() as conn:
            mode_rows = conn.execute(
                text(
                    "SELECT workflow_id, id FROM project_workflow.workflow_modes "
                    "WHERE key = 'default' ORDER BY workflow_id"
                )
            ).all()
            assert len(mode_rows) == 2 and mode_rows[0].id != mode_rows[1].id
            assert conn.execute(text("SELECT count(*) FROM project_workflow.tasks")).scalar_one() == 2
            assert conn.execute(text("SELECT count(*) FROM project_workflow.task_step_history")).scalar_one() == 2
            assert conn.execute(text("SELECT count(*) FROM project_workflow.task_phase_events")).scalar_one() == 2

    def test_head_preserves_nullable_legacy_assignment_shape(self, pg_url):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, "0001_initial")
        with engine.begin() as conn:
            workflow_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.workflows (name, description, is_default) "
                    "VALUES ('Legacy 0002', '', 0) RETURNING id"
                )
            ).scalar_one()
            phase_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.phases "
                    "(workflow_id, code, name, phase_order, execution_type) "
                    "VALUES (:workflow_id, 'legacy', 'Legacy', 1, 'sync') RETURNING id"
                ),
                {"workflow_id": workflow_id},
            ).scalar_one()
            project_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.projects "
                    "(workflow_id, code, name, description, theme_icon, theme_color, cli_command, key_prefixes) "
                    "VALUES (:workflow_id, 'L2', 'Legacy', '', 'folder', '#5E6AD2', 'legacy-2', '[]') "
                    "RETURNING id"
                ),
                {"workflow_id": workflow_id},
            ).scalar_one()
            task_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.tasks "
                    "(project_id, workflow_id, task_key, current_phase_id, status) "
                    "VALUES (:project_id, :workflow_id, 'L2-1', :phase_id, 'active') RETURNING id"
                ),
                {"project_id": project_id, "workflow_id": workflow_id, "phase_id": phase_id},
            ).scalar_one()

        run_alembic_command("upgrade", engine, "0002_workflow_modes")
        with engine.begin() as conn:
            mode_id = conn.execute(
                text(
                    "SELECT id FROM project_workflow.workflow_modes "
                    "WHERE workflow_id = :workflow_id AND key = 'default'"
                ),
                {"workflow_id": workflow_id},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO project_workflow.task_runtime_assignments "
                    "(operation_key, task_id, project_id, workflow_id, mode_id, cycle_number, "
                    "assignment_revision, payload) VALUES "
                    "('legacy-0002-op', :task_id, :project_id, :workflow_id, :mode_id, 0, 1, "
                    ":legacy_payload)"
                ),
                {
                    "task_id": task_id,
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "mode_id": mode_id,
                    "legacy_payload": '{"legacy":true}',
                },
            )
            workflow_key = conn.execute(
                text(
                    "SELECT key FROM project_workflow.workflows WHERE id = :workflow_id"
                ),
                {"workflow_id": workflow_id},
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO project_workflow.task_runtime_assignments "
                    "(operation_key, task_id, project_id, workflow_id, mode_id, cycle_number, "
                    "assignment_revision, workflow_key, role_key, execution_scope, stage_key, "
                    "attempt_number, business_task_ref, root_task_ref, work_item_ref, "
                    "work_item_revision, queue_item_ref, task_workspace_ref, workspace_revision, "
                    "tech_execution_workspace_ref, tech_execution_attempt_ref, "
                    "decomposition_revision_ref, stage_revision, assignment_ref, binding_ref, "
                    "hermes_run_ref, workspace_generation, lease_generation, exact_input_refs, "
                    "payload_sha256, payload) VALUES "
                    "('legacy-0002-bound', :task_id, :project_id, :workflow_id, :mode_id, 0, 2, "
                    ":workflow_key, 'developer', 'delivery', 'development', 1, 'business:1', "
                    "'business:root', 'business:item', 1, 'queue:1', 'task-workspace:1', 1, "
                    "'tech-workspace:1', 'tech-attempt:1', 'decomposition:1', 'stage:1', "
                    "'assignment:1', 'binding:legacy', 'hermes-run:legacy', 1, 1, '[]', "
                    ":payload_sha256, :bound_payload)"
                ),
                {
                    "task_id": task_id,
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "mode_id": mode_id,
                    "workflow_key": workflow_key,
                    "payload_sha256": "a" * 64,
                    "bound_payload": '{"bound":true}',
                },
            )

        ensure_migrated(engine)

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT operation_key, binding_ref, hermes_run_ref, bind_operation_key, "
                    "bind_request_sha256, payload FROM project_workflow.task_runtime_assignments "
                    "WHERE operation_key IN ('legacy-0002-op', 'legacy-0002-bound') "
                    "ORDER BY operation_key"
                )
            ).all()
        assert rows == [
            (
                "legacy-0002-bound",
                "binding:legacy",
                "hermes-run:legacy",
                None,
                None,
                '{"bound":true}',
            ),
            ("legacy-0002-op", None, None, None, None, '{"legacy":true}'),
        ]
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE project_workflow.task_runtime_assignments "
                        "SET bind_operation_key = 'partial-bind' "
                        "WHERE operation_key = 'legacy-0002-bound'"
                    )
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
                    "(key, name, description, is_default) VALUES ('fixture:w', 'W', '', 1) RETURNING id"
                )
            ).scalar_one()
            mode_id = _fixture_default_mode(conn, workflow_id)
            project_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.projects "
                    "(workflow_id, code, name, description, key_prefixes, cli_command) "
                    "VALUES (:workflow_id, 'P', 'Project', 'persisted', '[\"P\"]', 'workflow-p') RETURNING id"
                ),
                {"workflow_id": workflow_id, "mode_id": mode_id},
            ).scalar_one()
            phase_ids = [
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.phases "
                        "(workflow_id, mode_id, code, name, phase_order) "
                        "VALUES (:workflow_id, :mode_id, :code, :name, :phase_order) RETURNING id"
                    ),
                    {
                        "workflow_id": workflow_id,
                        "mode_id": mode_id,
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
                    "(project_id, workflow_id, mode_id, task_key, current_phase_id, status) "
                    "VALUES (:project_id, :workflow_id, :mode_id, 'P-1', :phase_id, 'active') RETURNING id"
                ),
                {
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "mode_id": mode_id,
                    "phase_id": phase_ids[0],
                },
            ).scalar_one()
            for phase_id in phase_ids:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_step_history "
                        "(task_id, workflow_id, mode_id, phase_id, verdict, replay_fingerprint) "
                        "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'partial', 'same')"
                    ),
                    {"task_id": task_id, "workflow_id": workflow_id, "mode_id": mode_id, "phase_id": phase_id},
                )

        with engine.connect() as conn:
            description = conn.execute(
                text("SELECT description FROM project_workflow.projects WHERE id = :id"),
                {"id": project_id},
            ).scalar_one()
        assert description == "persisted"

        with pytest.raises(IntegrityError, match="ck_phases_phase_order_positive"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.phases "
                        "(workflow_id, mode_id, code, name, phase_order) "
                        "VALUES (:workflow_id, :mode_id, 'bad', 'Bad', 0)"
                    ),
                    {"workflow_id": workflow_id, "mode_id": mode_id},
                )
        with pytest.raises(IntegrityError, match="ck_phase_instructions_step_num_positive"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.phase_instructions "
                        "(phase_id, step_num, description) VALUES (:phase_id, 0, 'Bad')"
                    ),
                    {"phase_id": phase_ids[0]},
                )
        with pytest.raises(IntegrityError, match="uq_task_step_history_replay"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_step_history "
                        "(task_id, workflow_id, mode_id, phase_id, verdict, replay_fingerprint) "
                        "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'partial', 'same')"
                    ),
                    {"task_id": task_id, "workflow_id": workflow_id, "mode_id": mode_id, "phase_id": phase_ids[0]},
                )
        with pytest.raises(IntegrityError, match="fk_tasks_current_phase_workflow"):
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM project_workflow.phases WHERE id = :phase_id"),
                    {"phase_id": phase_ids[0]},
                )

    def test_database_enforces_task_and_audit_ownership(self, pg_url):
        engine = get_engine(pg_url)
        ensure_migrated(engine)

        with engine.begin() as conn:
            workflow_ids: list[int] = []
            project_ids: list[int] = []
            mode_ids: list[int] = []
            phase_ids: list[int] = []
            for suffix in ("A", "B"):
                workflow_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.workflows (key, name, description, is_default) "
                        "VALUES (:key, :name, '', 0) RETURNING id"
                    ),
                    {"key": f"workflow-{suffix.lower()}", "name": f"Workflow {suffix}"},
                ).scalar_one()
                mode_id = _fixture_default_mode(conn, workflow_id)
                project_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.projects "
                        "(workflow_id, code, name, description, key_prefixes, cli_command) "
                        "VALUES (:workflow_id, :code, :name, '', :prefixes, :cli_command) RETURNING id"
                    ),
                    {
                        "workflow_id": workflow_id,
                        "mode_id": mode_id,
                        "code": f"P{suffix}",
                        "name": f"Project {suffix}",
                        "prefixes": f'["P{suffix}"]',
                        "cli_command": f"workflow-p{suffix.lower()}",
                    },
                ).scalar_one()
                phase_id = conn.execute(
                    text(
                        "INSERT INTO project_workflow.phases "
                        "(workflow_id, mode_id, code, name, phase_order) "
                        "VALUES (:workflow_id, :mode_id, :code, :name, 1) RETURNING id"
                    ),
                    {"workflow_id": workflow_id, "mode_id": mode_id, "code": suffix, "name": f"Phase {suffix}"},
                ).scalar_one()
                workflow_ids.append(workflow_id)
                mode_ids.append(mode_id)
                project_ids.append(project_id)
                phase_ids.append(phase_id)

        # Stored history may use a workflow other than the profession's old
        # default. Current collection admission belongs to the execution API.
        with engine.begin() as conn:
            extra_id = conn.execute(text(
                "INSERT INTO project_workflow.tasks "
                "(project_id, workflow_id, mode_id, task_key, current_phase_id, status) "
                "VALUES (:project_id, :workflow_id, :mode_id, 'PA-EXTRA', :phase_id, 'active') RETURNING id"
            ), {"project_id": project_ids[0], "workflow_id": workflow_ids[1],
                "mode_id": mode_ids[1], "phase_id": phase_ids[1]}).scalar_one()
            assert conn.execute(text(
                "SELECT project_id, workflow_id FROM project_workflow.tasks WHERE id=:id"
            ), {"id": extra_id}).one() == (project_ids[0], workflow_ids[1])

        with pytest.raises(IntegrityError, match="fk_tasks_project"):
            with engine.begin() as conn:
                absent_project = conn.execute(text(
                    "SELECT coalesce(max(id), 0) + 1 FROM project_workflow.projects"
                )).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.tasks "
                        "(project_id, workflow_id, mode_id, task_key, current_phase_id, status) "
                        "VALUES (:project_id, :workflow_id, :mode_id, 'PA-BAD', :phase_id, 'active')"
                    ),
                    {
                        "project_id": absent_project,
                        "workflow_id": workflow_ids[1],
                        "mode_id": mode_ids[1],
                        "phase_id": phase_ids[1],
                    },
                )

        with engine.begin() as conn:
            task_ids = [
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.tasks "
                        "(project_id, workflow_id, mode_id, task_key, current_phase_id, status) "
                        "VALUES (:project_id, :workflow_id, :mode_id, :task_key, :phase_id, 'active') RETURNING id"
                    ),
                    {
                        "project_id": project_ids[index],
                        "workflow_id": workflow_ids[index],
                        "mode_id": mode_ids[index],
                        "task_key": f"P{suffix}-1",
                        "phase_id": phase_ids[index],
                    },
                ).scalar_one()
                for index, suffix in enumerate(("A", "B"))
            ]

        with pytest.raises(IntegrityError, match="fk_task_step_history_phase_workflow"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_step_history "
                        "(task_id, workflow_id, mode_id, phase_id, verdict) "
                        "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'partial')"
                    ),
                    {
                        "task_id": task_ids[0],
                        "workflow_id": workflow_ids[0],
                        "mode_id": mode_ids[0],
                        "phase_id": phase_ids[1],
                    },
                )

        with pytest.raises(IntegrityError, match="fk_task_phase_events_phase_workflow"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_phase_events "
                        "(task_id, workflow_id, mode_id, phase_id, event_type) "
                        "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'entered')"
                    ),
                    {
                        "task_id": task_ids[0],
                        "workflow_id": workflow_ids[0],
                        "mode_id": mode_ids[0],
                        "phase_id": phase_ids[1],
                    },
                )

        with engine.begin() as conn:
            step_history_id = conn.execute(
                text(
                    "INSERT INTO project_workflow.task_step_history "
                    "(task_id, workflow_id, mode_id, phase_id, verdict) "
                    "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'partial') RETURNING id"
                ),
                {
                    "task_id": task_ids[0],
                    "workflow_id": workflow_ids[0],
                    "mode_id": mode_ids[0],
                    "phase_id": phase_ids[0],
                },
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO project_workflow.task_phase_events "
                    "(task_id, workflow_id, mode_id, phase_id, event_type) "
                    "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, 'entered')"
                ),
                {
                    "task_id": task_ids[0],
                    "workflow_id": workflow_ids[0],
                    "mode_id": mode_ids[0],
                    "phase_id": phase_ids[0],
                },
            )

        with pytest.raises(IntegrityError, match="fk_task_phase_events_step_task_execution"):
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO project_workflow.task_phase_events "
                        "(task_id, workflow_id, mode_id, phase_id, step_history_id, event_type) "
                        "VALUES (:task_id, :workflow_id, :mode_id, :phase_id, :step_history_id, 'entered')"
                    ),
                    {
                        "task_id": task_ids[1],
                        "workflow_id": workflow_ids[1],
                        "mode_id": mode_ids[1],
                        "phase_id": phase_ids[1],
                        "step_history_id": step_history_id,
                    },
                )

        with pytest.raises(IntegrityError, match="fk_task_step_history_task_workflow"):
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM project_workflow.tasks WHERE id = :task_id"),
                    {"task_id": task_ids[0]},
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
                for table in ("workflows", "projects", "phases")
            }
        assert counts == {"workflows": 7, "projects": 7, "phases": 33}

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
        assert {project.cli_command for project in uow.projects.list()} == {
            f"workflow-single-task-{role}" for role in (
                "project-manager", "analyst", "architect", "developer", "reviewer", "tester", "devops")}
        assert len([workflow for workflow in uow.workflows.list() if workflow.is_default]) == 1
        uow.close()

    def test_supervisor_concurrent_get_or_create_returns_one_task(self, pg_url):
        from project_workflow.supervisor import SupervisorEngine

        _initialize_legacy_database(pg_url)
        barrier = Barrier(2)
        thread_state = local()
        original_get = TaskService.get_task_by_key

        def synchronized_first_get(service, task_key, workflow_id=None, project_id=None):
            if not getattr(thread_state, "initial_lookup_done", False):
                thread_state.initial_lookup_done = True
                barrier.wait(timeout=10)
            return original_get(service, task_key, workflow_id=workflow_id, project_id=project_id)

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
    @pytest.mark.parametrize("work_item_revision", [1790840000123, (1 << 63) - 1])
    def test_upgrade_bound_assignment_preserves_rows_and_reads_imported_wide_revision(self, pg_url, work_item_revision):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, "0003_runtime_assignment_bind")
        # Seed the exact pre-0004 shape with SQL; current ORM includes later catalog columns.
        with engine.begin() as connection:
            workflow_id = connection.execute(text(
                "INSERT INTO project_workflow.workflows(key,name,is_default) "
                "VALUES ('hermes-sdlc:developer','Legacy Developer',1) RETURNING id"
            )).scalar_one()
            mode_id = connection.execute(text(
                "INSERT INTO project_workflow.workflow_modes "
                "(workflow_id,key,name,mode_order,role_key,execution_scope,tech_workspace_policy) "
                "VALUES (:workflow,'initial','Initial',1,'developer','delivery','required') RETURNING id"
            ), {"workflow": workflow_id}).scalar_one()
            phase_id = connection.execute(text(
                "INSERT INTO project_workflow.phases(workflow_id,mode_id,code,name,phase_order) "
                "VALUES (:workflow,:mode,'DV-WIDE-OLD-01','Legacy intake',1) RETURNING id"
            ), {"workflow": workflow_id, "mode": mode_id}).scalar_one()
            project_id = connection.execute(text(
                "INSERT INTO project_workflow.projects(workflow_id,code,name,cli_command) "
                "VALUES (:workflow,'DEV','Developer','workflow-developer') RETURNING id"
            ), {"workflow": workflow_id}).scalar_one()
            task_id = connection.execute(text(
                "INSERT INTO project_workflow.tasks "
                "(project_id,workflow_id,mode_id,task_key,current_phase_id,"
                "assignment_revision,assignment_operation_key) "
                "VALUES (:project,:workflow,:mode,'WIDE-1',:phase,1,'wide-old-assignment') RETURNING id"
            ), {"project": project_id, "workflow": workflow_id, "mode": mode_id, "phase": phase_id}).scalar_one()
            legacy = {**_runtime_binding("wide-old-assignment"), "task_id": task_id, "project_id": project_id,
                "workflow_id": workflow_id, "mode_id": mode_id, "operation_key": "wide-old-assignment",
                "cycle_number": 0, "assignment_revision": 1, "binding_ref": "legacy-binding",
                "hermes_run_ref": "legacy-run", "bind_operation_key": "legacy-bind", "bind_request_sha256": "b" * 64,
                "payload_sha256": "a" * 64, "payload": "{}"}
            legacy.pop("runtime_compatibility")
            legacy["exact_input_refs"] = json.dumps(legacy["exact_input_refs"])
            columns = ",".join(legacy)
            parameters = ",".join(f":{key}" for key in legacy)
            connection.execute(text(
                f"INSERT INTO project_workflow.task_runtime_assignments ({columns}) VALUES ({parameters})"
            ), legacy)
        with engine.connect() as connection:
            before = connection.execute(text(
                "SELECT to_jsonb(t)::text FROM project_workflow.task_runtime_assignments t ORDER BY id"
            )).scalars().all()
        ensure_migrated(engine)
        with engine.connect() as connection:
            after = connection.execute(text(
                "SELECT to_jsonb(t)::text FROM project_workflow.task_runtime_assignments t ORDER BY id"
            )).scalars().all()
        assert [json.loads(row) for row in after] == [
            {**json.loads(row), "concrete_agent_ref": None, "single_task_binding_json": None} for row in before
        ]
        # Import another archived row through the current typed repository. This
        # tests BIGINT storage/readback, not the retired native assignment command.
        with SAUnitOfWork(engine) as uow:
            imported = {**legacy, "operation_key": "wide-archived-assignment", "assignment_revision": 2,
                        "bind_operation_key": "wide-archived-bind",
                        "work_item_revision": work_item_revision,
                        "exact_input_refs": json.loads(legacy["exact_input_refs"]), "payload": {}}
            imported_id = uow.tasks.create_assignment(imported)
            uow.commit()
            assert uow.tasks.get_assignment_by_operation_key("wide-archived-assignment").id == imported_id
        ensure_migrated(engine)
        assert schema_is_ready(engine)
        with SAUnitOfWork(engine) as uow:
            assert uow.tasks.get_assignment_by_operation_key("wide-archived-assignment").work_item_revision == (
                work_item_revision
            )
            assert len(uow.tasks.list_assignments(task_id)) == 2



@pytest.mark.integration
class TestPostgresUoW:
    def test_create_and_read_workflow_project_task(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        uow = SAUnitOfWork(pg_url)
        with uow:
            wf_id = uow.workflows.create({"name": "Test Workflow", "description": "Test", "is_default": True})
            workflows = {w.name: w.id for w in uow.workflows.list()}
            assert workflows.get("Test Workflow") == wf_id

            proj_id = uow.projects.create(
                {"workflow_id": wf_id, "code": "TST", "name": "Default", "key_prefixes": ["TST"]}
            )
            projects = {p.code: p.id for p in uow.projects.list()}
            assert projects.get("TST") == proj_id

            phase_id = uow.phases.create(
                {"workflow_id": wf_id, "code": "start", "name": "Start", "phase_order": 1}
            )
            task_id = uow.tasks.create(
                {
                    "project_id": proj_id,
                    "workflow_id": wf_id,
                    "task_key": "TST-1",
                    "title": "First task",
                    "current_phase_id": phase_id,
                }
            )
            tasks = {t.task_key: t.id for t in uow.tasks.list()}
            assert tasks.get("TST-1") == task_id
            uow.commit()

    def test_repository_list_reads_have_deterministic_id_order(self, pg_url):
        _initialize_legacy_database(pg_url)
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
                "current_phase_id": phase.id,
            }
        )
        history_phases = list(uow.phases.list(int(workflow.id)))[:3]
        for history_phase in history_phases:
            assert history_phase.id is not None
            uow.tasks.record_phase_event(task_id, int(history_phase.id), "blocked")

        uow.session.execute(text("CREATE INDEX checks_desc_test_idx ON phase_checks (id DESC)"))
        uow.session.execute(text("CREATE INDEX evidence_desc_test_idx ON phase_evidence_requirements (id DESC)"))
        uow.session.execute(text("CREATE INDEX phase_events_desc_test_idx ON task_phase_events (id DESC)"))
        uow.session.execute(text("CREATE INDEX projects_desc_test_idx ON projects (id DESC)"))
        uow.commit()
        uow.session.execute(text("CLUSTER phase_checks USING checks_desc_test_idx"))
        uow.session.execute(text("CLUSTER phase_evidence_requirements USING evidence_desc_test_idx"))
        uow.session.execute(text("CLUSTER task_phase_events USING phase_events_desc_test_idx"))
        uow.session.execute(text("CLUSTER projects USING projects_desc_test_idx"))
        uow.commit()
        uow.session.execute(text("SET LOCAL enable_indexscan = off"))
        uow.session.execute(text("SET LOCAL enable_bitmapscan = off"))

        phase_checks = list(uow.phases.get_checks(int(phase.id)))
        phase_evidence = list(uow.phases.get_evidence(int(phase.id)))
        checks = list(uow.phase_checks.list(int(phase.id)))
        evidence = list(uow.phase_evidence_requirements.list(int(phase.id)))
        history = list(uow.tasks.list_phase_events(task_id))
        batch_history = list(uow.tasks.list_phase_events_batch([task_id])[task_id])
        projects = list(uow.projects.list())

        assert [row["id"] for row in phase_checks] == sorted(row["id"] for row in phase_checks)
        assert [row["id"] for row in phase_evidence] == sorted(row["id"] for row in phase_evidence)
        assert [row["id"] for row in checks] == sorted(row["id"] for row in checks)
        assert [row["id"] for row in evidence] == sorted(row["id"] for row in evidence)
        assert [row.id for row in history] == sorted(row.id for row in history)
        assert [row.id for row in batch_history] == sorted(row.id for row in batch_history)
        assert [item.id for item in projects] == sorted(item.id for item in projects)
        uow.close()

    def test_ensure_phase_catalog_populates_an_empty_default_workflow(self, pg_url):
        from project_workflow.infrastructure.db import schema as schema_module

        ensure_migrated(get_engine(pg_url))
        uow = SAUnitOfWork(pg_url)
        with uow:
            default_wf_id = uow.workflows.create({"name": "Default", "description": "default", "is_default": True})
            uow.projects.create(
                {
                    "workflow_id": default_wf_id,
                    "code": "DEFAULT",
                    "name": "Default Project",
                    "key_prefixes": ["DEFAULT"],
                }
            )
            uow.commit()

        schema_module.ensure_phase_catalog(uow)
        with uow:
            default_wf = uow.workflows.get_default()
            phases = uow.phases.list(workflow_id=default_wf.id)
            assert [phase.code for phase in phases] == [
                phase.code for phase in schema_module.load_phases_from_seed()
            ]

    def test_uow_commit_and_rollback(self, pg_url):
        ensure_migrated(get_engine(pg_url))
        uow = SAUnitOfWork(pg_url)
        with uow:
            wf_id = uow.workflows.create({"name": "Rollback WF", "description": "rollback"})
            uow.rollback()

        with uow:
            ids = {w.id for w in uow.workflows.list()}
            assert wf_id not in ids

    def test_concurrent_task_and_legacy_prefix_update_can_both_commit(self, pg_url):
        _initialize_legacy_database(pg_url)
        setup = SAUnitOfWork(pg_url)
        workflow_id = setup.workflows.get_default().id
        project = ProjectService(setup).create_project(
            {
                "code": "RACE",
                "name": "Race",
                "key_prefixes": ["RACE"],
                "workflow_id": workflow_id,
            }
        )
        setup.close()
        barrier = Barrier(2)

        def create_task() -> str:
            uow = SAUnitOfWork(pg_url)
            barrier.wait()
            try:
                TaskService(uow).create_task({"project_id": project["id"], "task_key": "RACE-1", "title": "Race"})
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
        assert outcomes == {"created", "updated"}

        verify = SAUnitOfWork(pg_url)
        stored_project = verify.projects.get_by_id(project["id"])
        stored_task = verify.tasks.get_by_key("RACE-1", project_id=project["id"])
        assert stored_project is not None
        assert stored_task is not None
        assert stored_project.key_prefixes == ["NEW"]
        verify.close()

    def test_concurrent_project_creates_allow_same_legacy_prefix(self, pg_url):
        _initialize_legacy_database(pg_url)
        setup = SAUnitOfWork(pg_url)
        workflow_id = setup.workflows.get_default().id
        setup.close()
        barrier = Barrier(2)

        def create(code: str) -> str:
            uow = SAUnitOfWork(pg_url)
            barrier.wait()
            try:
                ProjectService(uow).create_project(
                    {
                        "code": code,
                        "name": code,
                        "key_prefixes": ["SHARED"],
                        "workflow_id": workflow_id,
                    }
                )
                return "created"
            except ConflictError:
                uow.rollback()
                return "rejected"
            finally:
                uow.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(create, ["PREFIX-A", "PREFIX-B"]))
        assert sorted(outcomes) == ["created", "created"]

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
            original_list = uow.phases.list

            def paused_list(workflow_id: int, *, mode_id: int | None = None):
                task_holds_workflow_lock.set()
                assert release_task.wait(10)
                return original_list(workflow_id, mode_id=mode_id)

            uow.phases.list = paused_list
            try:
                TaskService(uow).create_task(
                    {
                        "project_id": project["id"],
                        "task_key": "PHASERACE-1",
                        "current_phase_id": first_id,
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


    def test_catalog_mutation_during_supervisor_provider_call_fails_closed(self, pg_url):
        from project_workflow.supervisor import SupervisorEngine

        _initialize_legacy_database(pg_url)
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
            checks = [{"id": item["id"], "description": item["description"]} for item in checks]
            checks.append({"id": None, "description": "Concurrent PostgreSQL catalog check"})
            PhaseService(mutation).update_phase_detail(int(phase.id), {"checks": checks})
            mutation.close()
            release_provider.set()
            result = result_future.result(timeout=20)

        assert result["verdict"] == "BLOCKED"
        assert result["retryable"] is True
        verify = SAUnitOfWork(pg_url)
        task = verify.tasks.get_by_key("RUN-90002")
        assert task is not None and task.status == "blocked" and task.current_phase_code == "1.INTAKE"
        run = verify.step_history.list(task_key="RUN-90002", limit=1)[0]
        assert run.verdict == "blocked"
        assert run.replay_fingerprint is None
        verify.close()

    @pytest.mark.parametrize("field", ["checks", "evidence"])
    def test_phase_aggregate_swaps_nested_descriptions_without_replacing_ids(self, pg_url, field):
        _initialize_legacy_database(pg_url)
        uow = SAUnitOfWork(pg_url)
        workflow = uow.workflows.get_default()
        assert workflow is not None and workflow.id is not None
        phase = uow.phases.get_by_code(int(workflow.id), "2.REQUIREMENTS")
        assert phase is not None and phase.id is not None
        service = PhaseService(uow)
        before = service.get_phase_detail(int(phase.id))[field]
        assert len(before) >= 2
        first, second = before[:2]
        payload = [
            {"id": first["id"], "description": second["description"]},
            {"id": second["id"], "description": first["description"]},
            *[{"id": item["id"], "description": item["description"]} for item in before[2:]],
        ]

        result = service.update_phase_detail(int(phase.id), {field: payload})
        after = service.get_phase_detail(int(phase.id))[field]
        uow.close()

        assert result[field] == [item["id"] for item in before]
        assert after[0]["description"] == second["description"]
        assert after[1]["description"] == first["description"]

    def test_noop_catalog_save_during_provider_call_keeps_verdict_and_replay(self, pg_url):
        from project_workflow.supervisor import SupervisorEngine

        _initialize_legacy_database(pg_url)
        provider_started = Event()
        release_provider = Event()

        def provider(*_args, **kwargs):
            provider_started.set()
            assert release_provider.wait(10)
            return _partial_response(str(kwargs["user"]))

        def evaluate() -> dict:
            uow = SAUnitOfWork(pg_url)
            try:
                with patch.object(OpenAICompatibleClient, "chat", side_effect=provider):
                    return SupervisorEngine("RUN-90003", uow=uow).evaluate("still working")
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
            detail = PhaseService(mutation).get_phase_detail(int(phase.id))
            PhaseService(mutation).update_phase_detail(
                int(phase.id),
                {
                    "instructions": [
                        {
                            "id": item["id"],
                            "description": item["description"],
                            "execution_type": item["execution_type"],
                            "skills": item["skills"],
                        }
                        for item in detail["instructions"]
                    ],
                    "checks": [
                        {"id": item["id"], "description": item["description"]}
                        for item in detail["checks"]
                    ],
                    "evidence": [
                        {"id": item["id"], "description": item["description"]}
                        for item in detail["evidence"]
                    ],
                },
            )
            mutation.close()
            release_provider.set()
            result = result_future.result(timeout=20)

        replay_uow = SAUnitOfWork(pg_url)
        try:
            with patch.object(OpenAICompatibleClient, "chat") as replay_provider:
                replay = SupervisorEngine("RUN-90003", uow=replay_uow).evaluate(
                    "still working"
                )
        finally:
            replay_uow.close()

        assert result["verdict"] == "PARTIAL"
        assert result["retryable"] is False
        assert replay["replayed"] is True
        replay_provider.assert_not_called()


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
            repository_method = getattr(uow.phase_instructions, operation)

            def paused_write(*args, **kwargs):
                instruction_holds_workflow.set()
                assert release_instruction.wait(10)
                return repository_method(*args, **kwargs)

            setattr(uow.phase_instructions, operation, paused_write)
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
        rows = list(verify.phase_instructions.list(int(phase.id)))
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


def _partial_response(user_prompt: str) -> dict:
    response = _pass_response(user_prompt)
    response.update(
        {
            "verdict": "PARTIAL",
            "covered": [],
            "missing": response["covered"],
            "message": "work remains",
            "confidence": 0.5,
        }
    )
    return response


def _initialize_legacy_database(pg_url: str) -> None:
    """Create the explicit unmanaged compatibility catalog for legacy CLI tests."""
    from project_workflow.infrastructure.db import schema
    from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

    engine = get_engine(pg_url)
    ensure_migrated(engine)
    with SAUnitOfWork(engine) as uow:
        schema.ensure_phase_catalog(
            uow,
            seed_path=config_module.LEGACY_UNMANAGED_SEED_PATH,
        )
        bootstrap_default_project(uow)
        uow.commit()


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
            "current_phase_id": phase.id,
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
    runs = uow.step_history.list(task_id=task.id)
    history = uow.tasks.list_phase_events(task.id)
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
    assert len(verify.step_history.list(task_id=task.id)) == 1
    assert len(verify.tasks.list_phase_events(task.id)) == 1
    verify.close()








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














@pytest.mark.integration
class TestPostgresContinuationCatalogVersioning:

    def test_additive_0005_0006_preserve_legacy_policy_and_support_versioned_duplicates(self, pg_url):
        engine = get_engine(pg_url)
        run_alembic_command("upgrade", engine, "0004_wide_work_item_revision")
        with engine.begin() as connection:
            workflow_id = connection.execute(
                text(
                    "INSERT INTO project_workflow.workflows (key,name,is_default) "
                    "VALUES ('hermes-sdlc:developer','Developer',1) RETURNING id"
                )
            ).scalar_one()
            old_id = connection.execute(
                text(
                    "INSERT INTO project_workflow.workflow_modes "
                    "(workflow_id,key,name,mode_order,role_key,execution_scope,tech_workspace_policy) "
                    "VALUES (:workflow,'initial','Initial',1,'developer','delivery','required') RETURNING id"
                ),
                {"workflow": workflow_id},
            ).scalar_one()
        ensure_migrated(engine)
        with engine.begin() as connection:
            old = connection.execute(
                text(
                    "SELECT execution_scope,execution_scopes,catalog_version "
                    "FROM project_workflow.workflow_modes WHERE id=:id"
                ),
                {"id": old_id},
            ).one()
            assert tuple(old) == ("delivery", None, 1)
            connection.execute(
                text(
                    "INSERT INTO project_workflow.workflow_modes "
                    "(workflow_id,key,name,mode_order,role_key,execution_scope,execution_scopes,"
                    "tech_workspace_policy,catalog_version) "
                    "VALUES (:workflow,'initial','Initial',1,'developer','delivery',:scopes,'required',2)"
                ),
                {"workflow": workflow_id, "scopes": json.dumps(["delivery", "aggregate"])},
            )
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM project_workflow.workflow_modes "
                        "WHERE workflow_id=:workflow AND key='initial'"
                    ),
                    {"workflow": workflow_id},
                ).scalar_one()
                == 2
            )
        assert schema_is_ready(engine)


def _health_probe_client(pg_url):
    engine = health_db_session.get_engine(pg_url)
    health_db_session.ensure_migrated(engine)
    return engine, TestClient(create_app())


@pytest.mark.integration
def test_postgres_warm_health_reuses_exact_validation_with_bounded_queries(pg_url):
    engine, client = _health_probe_client(pg_url)
    with patch.object(health_db_session, "schema_is_ready", wraps=health_db_session.schema_is_ready) as deep:
        assert client.get("/health").status_code == 200
        queries = []

        def record(_conn, _cursor, statement, _parameters, _context, _many):
            queries.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            for _ in range(3):
                assert client.get("/health").status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", record)
        assert deep.call_count == 1
        assert len(queries) <= 18


@pytest.mark.parametrize("change", [
    "ALTER TABLE projects ADD COLUMN unexpected_health_column TEXT",
    "ALTER TABLE projects ALTER COLUMN name TYPE text",
    "ALTER TABLE projects ALTER COLUMN name SET DEFAULT 'unexpected-default'",
    "CREATE INDEX health_extra_index ON projects(name)",
    "CREATE TABLE unexpected_health_table(id integer)",
    "CREATE FUNCTION legacy_metadata_readonly() RETURNS trigger LANGUAGE plpgsql "
    "AS $$BEGIN RETURN NEW; END;$$",
    "UPDATE alembic_version SET version_num='unknown_health_revision'",
])
@pytest.mark.integration
def test_postgres_health_rejects_ddl_or_revision_drift_without_ttl(pg_url, change):
    engine, client = _health_probe_client(pg_url)
    assert client.get("/health").status_code == 200
    with engine.begin() as connection:
        connection.execute(text(change))
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["error_code"] == "schema-not-ready"


@pytest.mark.integration
def test_postgres_health_recovers_after_ddl_repair(pg_url):
    engine, client = _health_probe_client(pg_url)
    assert client.get("/health").status_code == 200
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE unexpected_health_table(id integer)"))
    assert client.get("/health").status_code == 503
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE unexpected_health_table"))
    assert client.get("/health").status_code == 200


@pytest.mark.integration
def test_postgres_health_neighbor_namespace_and_same_revision_dml_do_not_repeat_validation(pg_url):
    engine, client = _health_probe_client(pg_url)
    with patch.object(health_db_session, "schema_is_ready", wraps=health_db_session.schema_is_ready) as deep:
        assert client.get("/health").status_code == 200
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num=version_num"))
            connection.execute(text('CREATE SCHEMA "Health_Neighbor"'))
            connection.execute(text('CREATE TABLE "Health_Neighbor".extra(id integer)'))
        assert client.get("/health").status_code == 200
        assert deep.call_count == 1


@pytest.mark.integration
def test_retired_phase_edges_do_not_block_deletion_and_rollback_is_atomic(pg_url):
    from uuid import uuid4

    engine = get_engine(pg_url)
    ensure_migrated(engine)
    with SAUnitOfWork(engine) as uow:
        workflow_id = WorkflowService(uow).create_workflow({"name": "Deletion " + uuid4().hex})["id"]
        service = PhaseServiceApp(uow)
        first = service.list_phases(workflow_id)[0]
        second = service.create_phase({"workflow_id": workflow_id, "name": "Second", "phase_order": 2})
        third = service.create_phase({"workflow_id": workflow_id, "name": "Third", "phase_order": 3})
        uow.phases.update(
            second["id"], {"parallel_with_phase_id": first["id"], "rollback_target_phase_id": third["id"]}
        )
        uow.phases.update(third["id"], {"rollback_target_phase_id": first["id"]})
        uow.commit()
        with patch.object(uow, "commit", side_effect=RuntimeError("commit failure")):
            with pytest.raises(RuntimeError, match="commit failure"):
                service.delete_phase(first["id"])
        assert service.get_phase(first["id"]) is not None
        assert service.get_phase(second["id"])["parallel_with_phase_id"] == first["id"]
        assert service.get_phase(third["id"])["rollback_target_phase_id"] == first["id"]
        service.delete_phase(first["id"])
        assert service.get_phase(first["id"]) is None
        assert service.get_phase(second["id"])["parallel_with_phase_id"] is None
        assert service.get_phase(second["id"])["rollback_target_phase_id"] == third["id"]
        assert service.get_phase(third["id"])["rollback_target_phase_id"] is None
        assert [phase["phase_order"] for phase in service.list_phases(workflow_id)] == [1, 2]
        project = ProjectService(uow).create_project(
            {
                "workflow_id": workflow_id,
                "code": "delete-" + uuid4().hex,
                "name": "Delete guard",
                "key_prefixes": ["DELETE"],
            }
        )
        task = TaskService(uow).create_task(
            {"project_id": project["id"], "task_key": "DELETE-1", "current_phase_id": second["id"]}
        )
        with pytest.raises(ConflictError, match="текущая задача"):
            service.delete_phase(second["id"])
        uow.tasks.update(task["id"], {"current_phase_id": third["id"]})
        uow.tasks.record_phase_event(task["id"], second["id"], "completed")
        uow.commit()
        with pytest.raises(ConflictError, match="история задачи"):
            service.delete_phase(second["id"])
        assert service.get_phase(second["id"]) is not None
        assert service.get_phase(second["id"])["rollback_target_phase_id"] == third["id"]
