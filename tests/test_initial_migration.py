"""Contract tests for the single clean Alembic baseline."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.pool import NullPool, StaticPool

from project_workflow import config
from project_workflow.domain.runtime_assignment import MANAGED_WORKFLOW_KEYS
from project_workflow.infrastructure.db import models as db_models
from project_workflow.infrastructure.db import schema
from project_workflow.infrastructure.db.models import Base
from project_workflow.infrastructure.db.session import (
    DatabaseRecreateRequired,
    DatabaseUnavailable,
    database_revisions,
    ensure_migrated,
    migration_head,
    run_alembic_command,
    schema_is_ready,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project

LEGACY_REVISIONS = [
    "0002_sdlc_v2",
    "249bc4ab2fa9",
    "4d7c2a9e6b10",
    "57316bf44b1a",
    "6f3d8a2c1b47",
    "75bc288f78c6",
    "7a1e9c3b4d5f",
    "8d2e7f1a9b3c",
    "9b71d2e4c6a0",
    "a1b2c3d4e5f6",
    "a42e91d6c7f3",
    "a8d3c7e9f201",
    "b7f3c9d2a641",
    "becf90549ae1",
    "c31a9f6d4e20",
    "caeb9ba65f4a",
    "d4e8f1a2b703",
    "d83b7c2e4f10",
    "e4a7b19c2d01",
    "e6a4c2d8b901",
    "e92c4f7a1b63",
    "f61c2a7d9e04",
]


_SQLITE_ENGINES = []


@pytest.fixture(autouse=True)
def _dispose_sqlite_engines():
    yield
    for engine in reversed(_SQLITE_ENGINES):
        engine.dispose()
    _SQLITE_ENGINES.clear()


def _sqlite_engine(tmp_path: Path, filename: str = "initial.db"):
    engine = create_engine(f"sqlite:///{tmp_path / filename}", poolclass=NullPool)
    _SQLITE_ENGINES.append(engine)
    return engine


def _constraint_names(items: list[dict]) -> set[str]:
    return {str(item["name"]) for item in items if item.get("name")}


def test_repository_has_one_linear_migration_head():
    versions = Path(__file__).parents[1] / "project_workflow" / "infrastructure" / "db" / "migrations" / "versions"
    assert sorted(path.name for path in versions.glob("*.py")) == [
        "0001_initial_schema.py",
        "0002_workflow_modes.py",
        "0003_runtime_assignment_bind.py",
        "0004_wide_work_item_revision.py",
        "0005_pm_execution.py",
    ]
    assert migration_head() == "0005_pm_execution"


def test_fresh_sqlite_migration_matches_orm_metadata(tmp_path):
    engine = _sqlite_engine(tmp_path)
    ensure_migrated(engine)

    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names()) - {"alembic_version"}
    assert actual_tables == set(Base.metadata.tables)

    for table_name, table in Base.metadata.tables.items():
        actual_columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert set(actual_columns) == set(table.columns.keys()), table_name
        assert {
            name: column["nullable"] for name, column in actual_columns.items()
        } == {name: column.nullable for name, column in table.columns.items()}

        expected_checks = {
            constraint.name
            for constraint in table.constraints
            if constraint.__class__.__name__ == "CheckConstraint"
        }
        expected_uniques = {
            constraint.name
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        assert _constraint_names(inspector.get_check_constraints(table_name)) == expected_checks - {None}
        assert _constraint_names(inspector.get_unique_constraints(table_name)) == expected_uniques - {None}
        assert _constraint_names(inspector.get_indexes(table_name)) == {index.name for index in table.indexes}

        actual_fks = {
            (
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                (fk.get("options") or {}).get("ondelete"),
            )
            for fk in inspector.get_foreign_keys(table_name)
        }
        expected_fks = {
            (
                tuple(constraint.column_keys),
                next(iter(constraint.elements)).column.table.name,
                tuple(element.column.name for element in constraint.elements),
                constraint.ondelete,
            )
            for constraint in table.foreign_key_constraints
        }
        assert actual_fks == expected_fks, table_name

    assert database_revisions(engine) == {"0005_pm_execution"}
    assert schema_is_ready(engine) is True
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"compare_type": True, "compare_server_default": True},
        )
        assert compare_metadata(context, Base.metadata) == []


def test_sqlite_upgrade_populated_legacy_backfills_each_workflow_mode(tmp_path):
    engine = _sqlite_engine(tmp_path, "legacy-populated.db")
    run_alembic_command("upgrade", engine, "0001_initial")
    with engine.begin() as conn:
        workflow_ids = [
            conn.execute(
                text("INSERT INTO workflows (name, description, is_default) VALUES (:name, '', 0) RETURNING id"),
                {"name": f"Legacy {suffix}"},
            ).scalar_one()
            for suffix in ("A", "B")
        ]
        rows: list[tuple[int, int, int, int]] = []
        for index, workflow_id in enumerate(workflow_ids, 1):
            phase_id = conn.execute(
                text(
                    "INSERT INTO phases (workflow_id, code, name, phase_order) "
                    "VALUES (:workflow_id, :code, :name, 1) RETURNING id"
                ),
                {"workflow_id": workflow_id, "code": f"legacy-{index}", "name": "Legacy"},
            ).scalar_one()
            project_id = conn.execute(
                text(
                    "INSERT INTO projects "
                    "(workflow_id, code, name, description, key_prefixes, cli_command) "
                    "VALUES (:workflow_id, :code, :name, '', '[]', :cli) RETURNING id"
                ),
                {"workflow_id": workflow_id, "code": f"LP{index}", "name": "Legacy", "cli": f"legacy-{index}"},
            ).scalar_one()
            task_id = conn.execute(
                text(
                    "INSERT INTO tasks (project_id, workflow_id, task_key, current_phase_id, status) "
                    "VALUES (:project_id, :workflow_id, :task_key, :phase_id, 'active') RETURNING id"
                ),
                {
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "task_key": f"LP{index}-1",
                    "phase_id": phase_id,
                },
            ).scalar_one()
            history_id = conn.execute(
                text(
                    "INSERT INTO task_step_history "
                    "(task_id, workflow_id, phase_id, verdict, replay_fingerprint) "
                    "VALUES (:task_id, :workflow_id, :phase_id, 'partial', :fingerprint) RETURNING id"
                ),
                {
                    "task_id": task_id,
                    "workflow_id": workflow_id,
                    "phase_id": phase_id,
                    "fingerprint": f"legacy-{index}",
                },
            ).scalar_one()
            conn.execute(
                text(
                    "INSERT INTO task_phase_events "
                    "(task_id, workflow_id, phase_id, step_history_id, event_type) "
                    "VALUES (:task_id, :workflow_id, :phase_id, :history_id, 'entered')"
                ),
                {"task_id": task_id, "workflow_id": workflow_id, "phase_id": phase_id, "history_id": history_id},
            )
            rows.append((workflow_id, project_id, task_id, phase_id))

    ensure_migrated(engine)
    with engine.connect() as conn:
        mode_rows = conn.execute(
            text("SELECT workflow_id, id FROM workflow_modes WHERE key = 'default' ORDER BY workflow_id")
        ).all()
        assert len(mode_rows) == 2
        assert mode_rows[0].id != mode_rows[1].id
        for workflow_id, _project_id, task_id, phase_id in rows:
            mode_id = conn.execute(
                text("SELECT id FROM workflow_modes WHERE workflow_id = :workflow_id AND key = 'default'"),
                {"workflow_id": workflow_id},
            ).scalar_one()
            assert conn.execute(
                text("SELECT mode_id, cycle_number FROM tasks WHERE id = :id"), {"id": task_id}
            ).one() == (mode_id, 0)
            assert conn.execute(
                text(
                    "SELECT mode_id, cycle_number, step_operation_key, request_sha256, "
                    "assignment_revision, assignment_operation_key, assignment_ref, binding_ref, "
                    "hermes_run_ref, attempt_number, role_key "
                    "FROM task_step_history WHERE task_id = :id"
                ),
                {"id": task_id},
            ).one() == (mode_id, 0, None, None, None, None, None, None, None, None, None)
            assert conn.execute(
                text("SELECT mode_id, cycle_number FROM task_phase_events WHERE task_id = :id"),
                {"id": task_id},
            ).one() == (mode_id, 0)
            assert conn.execute(
                text("SELECT mode_id FROM phases WHERE id = :id"), {"id": phase_id}
            ).scalar_one() == mode_id
        workflow_key = inspect(engine).get_columns("workflows")
        assert next(column for column in workflow_key if column["name"] == "key")["nullable"] is False
        with pytest.raises(IntegrityError):
            conn.execute(
                text("INSERT INTO workflows (key, name, description, is_default) VALUES (NULL, 'Invalid', '', 0)")
            )


@pytest.mark.parametrize("prior_revision", ["0002_workflow_modes", "0004_wide_work_item_revision"])
def test_sqlite_runtime_assignment_rejects_invalid_immutable_bindings(tmp_path, prior_revision):
    engine = _sqlite_engine(tmp_path, "binding-constraints.db")
    run_alembic_command("upgrade", engine, prior_revision)
    with engine.begin() as conn:
        workflow_id = conn.execute(
            text(
                "INSERT INTO workflows (key, name, description, is_default) "
                "VALUES ('bindings', 'Bindings', '', 0) RETURNING id"
            )
        ).scalar_one()
        mode_id = conn.execute(
            text(
                "INSERT INTO workflow_modes "
                "(workflow_id, key, name, mode_order, role_key, execution_scope, tech_workspace_policy) "
                "VALUES (:workflow_id, 'delivery', 'Delivery', 1, 'developer', 'delivery', 'required') "
                "RETURNING id"
            ),
            {"workflow_id": workflow_id},
        ).scalar_one()
        phase_id = conn.execute(
            text(
                "INSERT INTO phases (workflow_id, mode_id, code, name, phase_order) "
                "VALUES (:workflow_id, :mode_id, 'start', 'Start', 1) RETURNING id"
            ),
            {"workflow_id": workflow_id, "mode_id": mode_id},
        ).scalar_one()
        project_ids = [
            conn.execute(
                text(
                    "INSERT INTO projects (workflow_id, code, name, description, key_prefixes, cli_command) "
                    "VALUES (:workflow_id, :code, :code, '', '[]', :cli) RETURNING id"
                ),
                {"workflow_id": workflow_id, "code": code, "cli": f"binding-{code.lower()}"},
            ).scalar_one()
            for code in ("BIND1", "BIND2")
        ]
        task_id = conn.execute(
            text(
                "INSERT INTO tasks "
                "(project_id, workflow_id, mode_id, cycle_number, assignment_revision, task_key, "
                "current_phase_id, status) VALUES "
                "(:project_id, :workflow_id, :mode_id, 0, 0, 'BIND-1', :phase_id, 'active') RETURNING id"
            ),
            {
                "project_id": project_ids[0],
                "workflow_id": workflow_id,
                "mode_id": mode_id,
                "phase_id": phase_id,
            },
        ).scalar_one()

    base_0002 = {
        "operation_key": "legacy-bound",
        "task_id": task_id,
        "project_id": project_ids[0],
        "workflow_id": workflow_id,
        "mode_id": mode_id,
        "cycle_number": 0,
        "assignment_revision": 1,
        "workflow_key": "hermes-sdlc:developer",
        "role_key": "developer",
        "stage_key": "development",
        "execution_scope": "delivery",
        "attempt_number": 1,
        "business_task_ref": "business:1",
        "root_task_ref": "business:root",
        "work_item_ref": "business:item",
        "work_item_revision": 1,
        "queue_item_ref": "queue-item:1",
        "task_workspace_ref": "workspace:task",
        "workspace_revision": 1,
        "tech_execution_workspace_ref": "workspace:tech",
        "tech_execution_attempt_ref": "attempt:1",
        "decomposition_revision_ref": "decomposition:1",
        "stage_revision": "stage:1",
        "assignment_ref": "assignment:1",
        "binding_ref": "binding:1",
        "hermes_run_ref": "run:1",
        "workspace_generation": 1,
        "lease_generation": 1,
        "exact_input_refs": "[]",
        "payload_sha256": "a" * 64,
        "payload": "{}",
    }
    old_columns = ", ".join(base_0002)
    old_values = ", ".join(f":{column}" for column in base_0002)
    old_statement = text(
        f"INSERT INTO task_runtime_assignments ({old_columns}) VALUES ({old_values})"
    )
    with engine.begin() as conn:
        conn.execute(old_statement, base_0002)
        conn.execute(
            text(
                "INSERT INTO task_runtime_assignments "
                "(operation_key, task_id, project_id, workflow_id, mode_id, cycle_number, "
                "assignment_revision, payload) VALUES "
                "('legacy-unbound', :task_id, :project_id, :workflow_id, :mode_id, 0, 2, "
                ":legacy_payload)"
            ),
            {
                "task_id": task_id,
                "project_id": project_ids[0],
                "workflow_id": workflow_id,
                "mode_id": mode_id,
                "legacy_payload": '{"legacy":true}',
            },
        )

    ensure_migrated(engine)
    assert database_revisions(engine) == {"0005_pm_execution"}
    with engine.connect() as conn:
        preserved = conn.execute(
            text(
                "SELECT operation_key, binding_ref, hermes_run_ref, bind_operation_key, "
                "bind_request_sha256, payload, concrete_agent_ref FROM task_runtime_assignments "
                "WHERE operation_key IN ('legacy-bound', 'legacy-unbound') ORDER BY operation_key"
            )
        ).all()
    assert preserved == [
        ("legacy-bound", "binding:1", "run:1", None, None, "{}", None),
        ("legacy-unbound", None, None, None, None, '{"legacy":true}', None),
    ]

    base = {
        **base_0002,
        "operation_key": "valid",
        "assignment_revision": 3,
        "bind_operation_key": "bind:1",
        "bind_request_sha256": "b" * 64,
        "concrete_agent_ref": None,
    }
    columns = ", ".join(base)
    values = ", ".join(f":{column}" for column in base)
    statement = text(f"INSERT INTO task_runtime_assignments ({columns}) VALUES ({values})")
    with engine.begin() as conn:
        conn.execute(statement, base)
        conn.execute(
            statement,
            {
                **base,
                "operation_key": "valid-unbound",
                "assignment_revision": 4,
                "binding_ref": None,
                "hermes_run_ref": None,
                "bind_operation_key": None,
                "bind_request_sha256": None,
            },
        )

    invalid_rows = [
        {
            **base, "operation_key": "mapping-without-binding", "assignment_revision": 5,
            "binding_ref": None, "hermes_run_ref": None, "bind_operation_key": None,
            "bind_request_sha256": None, "concrete_agent_ref": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        },
        {
            **base, "operation_key": "mapping-role-name", "assignment_revision": 5,
            "bind_operation_key": "bind:mapping-role-name", "concrete_agent_ref": "project_manager",
        },
        {
            **base,
            "operation_key": "cross-project",
            "bind_operation_key": "bind:cross-project",
            "assignment_revision": 5,
            "project_id": project_ids[1],
        },
        {
            **base,
            "operation_key": "partial",
            "bind_operation_key": "bind:partial",
            "assignment_revision": 5,
            "binding_ref": None,
        },
        {
            **base,
            "operation_key": "partial-bind-metadata",
            "bind_operation_key": "bind:partial-metadata",
            "bind_request_sha256": None,
            "assignment_revision": 5,
        },
        {
            **base,
            "operation_key": "business-with-tech",
            "bind_operation_key": "bind:business-with-tech",
            "assignment_revision": 5,
            "execution_scope": "business",
        },
        {
            **base,
            "operation_key": "delivery-without-tech",
            "bind_operation_key": "bind:delivery-without-tech",
            "assignment_revision": 5,
            "tech_execution_attempt_ref": None,
        },
    ]
    for invalid in invalid_rows:
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(statement, invalid)


def test_in_memory_sqlite_migration_keeps_the_schema_alive():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    try:
        ensure_migrated(engine)

        assert schema_is_ready(engine) is True
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision,message", [
    ("0003_runtime_assignment_bind", "Downgrade from runtime assignment bind"),
    ("0004_wide_work_item_revision", "Downgrade from wide Business revisions"),
    ("0005_pm_execution", "PM execution downgrade refused"),
])
def test_sqlite_downgrade_refuses_lossy_runtime_history(tmp_path, revision, message):
    engine = _sqlite_engine(tmp_path)
    run_alembic_command("upgrade", engine, revision)
    with pytest.raises(RuntimeError, match=message):
        run_alembic_command("downgrade", engine, "base")
    assert database_revisions(engine) == {revision}
    assert schema_is_ready(engine) is (revision == migration_head())


def test_empty_initial_schema_can_be_recreated_through_supported_migrations(tmp_path):
    engine = _sqlite_engine(tmp_path, "initial-roundtrip.db")
    run_alembic_command("upgrade", engine, "0001_initial")
    initial_tables = set(inspect(engine).get_table_names())
    assert "tasks" in initial_tables and "workflow_modes" not in initial_tables
    run_alembic_command("downgrade", engine, "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    assert database_revisions(engine) == set()
    run_alembic_command("upgrade", engine, "0001_initial")
    assert set(inspect(engine).get_table_names()) == initial_tables
    ensure_migrated(engine)
    assert schema_is_ready(engine) is True


def test_mode_schema_refuses_lossy_downgrade_before_bind_migration(tmp_path):
    engine = _sqlite_engine(tmp_path, "mode-downgrade.db")
    run_alembic_command("upgrade", engine, "0002_workflow_modes")
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO workflows (key, name, is_default) VALUES ('legacy:1', 'Keep', 1)"))
    before_tables = set(inspect(engine).get_table_names())
    with pytest.raises(RuntimeError, match="Downgrade from workflow modes"):
        run_alembic_command("downgrade", engine, "0001_initial")
    assert database_revisions(engine) == {"0002_workflow_modes"}
    assert set(inspect(engine).get_table_names()) == before_tables
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM workflows WHERE key='legacy:1'")).scalar_one() == "Keep"


@pytest.mark.parametrize("legacy_revision", LEGACY_REVISIONS)
def test_sqlite_legacy_revision_is_refused_without_mutation(tmp_path, legacy_revision):
    engine = _sqlite_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        conn.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": legacy_revision},
        )
        conn.execute(text("CREATE TABLE keep_me (id INTEGER PRIMARY KEY)"))

    with pytest.raises(DatabaseRecreateRequired, match="Несовместимую базу данных необходимо пересоздать"):
        ensure_migrated(engine)

    assert database_revisions(engine) == {legacy_revision}
    assert inspect(engine).has_table("keep_me")


def test_sqlite_unversioned_nonempty_database_is_refused(tmp_path):
    engine = _sqlite_engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE keep_me (id INTEGER PRIMARY KEY, value TEXT)"))
        conn.execute(text("INSERT INTO keep_me VALUES (1, 'сохранить')"))

    with pytest.raises(DatabaseRecreateRequired, match="Несовместимую базу данных необходимо пересоздать"):
        ensure_migrated(engine)

    assert inspect(engine).has_table("keep_me")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT value FROM keep_me WHERE id = 1")).scalar_one() == "сохранить"


def test_init_db_restarts_populated_versioned_legacy_catalog_without_rewriting_history(
    tmp_path, monkeypatch
):
    from project_workflow.config import get_settings
    from project_workflow.infrastructure.db.session import reset_engine
    from scripts.init_db import main

    database_url = f"sqlite:///{tmp_path / 'legacy-restart.db'}"
    engine = create_engine(database_url, poolclass=NullPool)
    _SQLITE_ENGINES.append(engine)
    ensure_migrated(engine)
    with SAUnitOfWork(engine) as uow:
        schema.ensure_phase_catalog(
            uow, seed_path=config.LEGACY_UNMANAGED_SEED_PATH
        )
        bootstrap_default_project(uow)
        workflow = uow.workflows.get_default()
        namespace = uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE)
        assert workflow is not None and workflow.id is not None
        assert namespace is not None and namespace.id is not None
        mode = uow.workflows.get_mode_by_key(workflow.id, "default")
        assert mode is not None and mode.id is not None
        phase = uow.phases.get_by_code(workflow.id, "1.INTAKE", mode_id=mode.id)
        assert phase is not None and phase.id is not None
        workflow_row = uow.session.get(db_models.Workflow, workflow.id)
        assert workflow_row is not None
        workflow_row.key = f"legacy:{workflow.id}"
        task_id = uow.tasks.create(
            {
                "project_id": namespace.id,
                "workflow_id": workflow.id,
                "mode_id": mode.id,
                "task_key": "RUN-RESTART-1",
                "title": "Restart compatibility",
                "current_phase_id": phase.id,
                "status": "active",
            }
        )
        history_id = uow.record_step(
            task_id=task_id,
            phase_id=phase.id,
            verdict="pass",
            worker_report="immutable legacy report",
            covered_item_ids=[],
            missing_item_ids=[],
            blocker_messages=[],
            evaluation_snapshot={"legacy": True},
            supervisor_response={"verdict": "PASS"},
        )
        uow.tasks.record_phase_event(
            task_id, phase.id, "completed", step_history_id=history_id
        )
        uow.commit()
        legacy_workflow_id = workflow.id
        original_task = uow.tasks.get_by_id(task_id).to_dict()
        original_history = uow.step_history.list(task_id=task_id, limit=None)[0].to_dict()
        original_events = [item.to_dict() for item in uow.tasks.list_phase_events(task_id)]

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    reset_engine()
    try:
        assert main() == 0
        assert main() == 0
        with SAUnitOfWork(database_url) as restarted:
            assert restarted.tasks.get_by_id(task_id).to_dict() == original_task
            assert (
                restarted.step_history.list(task_id=task_id, limit=None)[0].to_dict()
                == original_history
            )
            assert [
                item.to_dict() for item in restarted.tasks.list_phase_events(task_id)
            ] == original_events
            assert restarted.workflows.get_default().id == legacy_workflow_id
            assert {
                workflow.key
                for workflow in restarted.workflows.list()
                if workflow.key in MANAGED_WORKFLOW_KEYS
            } == MANAGED_WORKFLOW_KEYS
    finally:
        get_settings.cache_clear()
        reset_engine()


@pytest.mark.parametrize("shape", ["legacy", "v2", "unversioned", "damaged-head"])
def test_init_db_returns_exit_code_two_without_mutation(tmp_path, monkeypatch, capsys, shape):
    from project_workflow.config import get_settings
    from project_workflow.infrastructure.db.session import reset_engine
    from scripts.init_db import main

    database_url = f"sqlite:///{tmp_path / f'{shape}-init.db'}"
    engine = create_engine(database_url, poolclass=NullPool)
    _SQLITE_ENGINES.append(engine)
    if shape == "damaged-head":
        ensure_migrated(engine)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE keep_me (id INTEGER PRIMARY KEY, value TEXT)"))
            connection.execute(text("INSERT INTO keep_me VALUES (1, 'сохранить')"))
    else:
        with engine.begin() as connection:
            if shape != "unversioned":
                connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
                revision = "0002_sdlc_v2" if shape == "v2" else "57316bf44b1a"
                connection.execute(
                    text("INSERT INTO alembic_version VALUES (:revision)"),
                    {"revision": revision},
                )
            connection.execute(text("CREATE TABLE keep_me (id INTEGER PRIMARY KEY, value TEXT)"))
            connection.execute(text("INSERT INTO keep_me VALUES (1, 'сохранить')"))

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    reset_engine()
    try:
        assert main() == 2
        assert "Несовместимую базу данных необходимо пересоздать" in capsys.readouterr().err
        assert inspect(engine).has_table("keep_me")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT value FROM keep_me WHERE id = 1")).scalar_one() == "сохранить"
    finally:
        get_settings.cache_clear()
        reset_engine()


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (DatabaseUnavailable(), "Не удалось подключиться к базе данных"),
        (
            OperationalError("sql-secret-marker", {}, RuntimeError("dsn-secret-marker")),
            "Не удалось инициализировать базу данных",
        ),
    ],
)
def test_init_db_hides_database_exception_details(monkeypatch, capsys, error, message):
    from scripts import init_db

    monkeypatch.setattr(
        init_db,
        "get_engine",
        lambda _url: (_ for _ in ()).throw(error),
    )

    assert init_db.main() == 1
    stderr = capsys.readouterr().err
    assert message in stderr
    assert "sql-secret-marker" not in stderr
    assert "dsn-secret-marker" not in stderr


def test_init_db_configures_output_encoding(monkeypatch):
    from scripts import init_db

    class Stream:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def reconfigure(self, **kwargs: str) -> None:
            self.calls.append(kwargs)

    stdout = Stream()
    stderr = Stream()
    monkeypatch.setattr(init_db.sys, "stdout", stdout)
    monkeypatch.setattr(init_db.sys, "stderr", stderr)

    init_db._configure_output_encoding()

    assert stdout.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_init_db_reports_invalid_managed_catalog_without_traceback(tmp_path, monkeypatch, capsys):
    from project_workflow import config
    from project_workflow.infrastructure.db.session import reset_engine
    from scripts import init_db

    closed = False
    real_uow_cls = init_db.SAUnitOfWork

    class TrackingUoW(real_uow_cls):
        def close(self) -> None:
            nonlocal closed
            closed = True
            super().close()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'invalid-seed.db'}")
    monkeypatch.setattr(init_db, "SAUnitOfWork", TrackingUoW)
    monkeypatch.setattr(
        init_db,
        "ensure_managed_catalog",
        lambda _uow: (_ for _ in ()).throw(ValueError("Некорректный managed каталог: phase.code")),
    )
    config.get_settings.cache_clear()
    reset_engine()
    try:
        assert init_db.main() == 1
        stderr = capsys.readouterr().err
        assert "Некорректный managed каталог: phase.code" in stderr
        assert "Traceback" not in stderr
        assert closed is True
    finally:
        config.get_settings.cache_clear()
        reset_engine()


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_head_with_damaged_or_polluted_schema_is_refused(tmp_path, mutation):
    engine = _sqlite_engine(tmp_path)
    ensure_migrated(engine)
    with engine.begin() as connection:
        if mutation == "missing":
            connection.execute(text("DROP TABLE phase_instructions"))
        else:
            connection.execute(text("CREATE TABLE unexpected_table (id INTEGER PRIMARY KEY)"))
            connection.execute(text("INSERT INTO unexpected_table VALUES (42)"))

    assert schema_is_ready(engine) is False
    with pytest.raises(DatabaseRecreateRequired):
        ensure_migrated(engine)
    assert database_revisions(engine) == {"0005_pm_execution"}
    if mutation == "extra":
        with engine.connect() as connection:
            assert connection.execute(text("SELECT id FROM unexpected_table")).scalar_one() == 42


@pytest.mark.parametrize(
    "statement",
    [
        "ALTER TABLE projects ADD COLUMN unexpected_column TEXT",
        "ALTER TABLE projects DROP COLUMN description",
    ],
)
def test_head_with_column_drift_is_refused(tmp_path, statement):
    engine = _sqlite_engine(tmp_path)
    ensure_migrated(engine)
    with engine.begin() as connection:
        connection.execute(text(statement))

    assert schema_is_ready(engine) is False
    with pytest.raises(DatabaseRecreateRequired):
        ensure_migrated(engine)


def test_sqlite_initial_constraints(tmp_path):
    engine = _sqlite_engine(tmp_path)
    ensure_migrated(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO agents (name, description) VALUES ('Reviewer', '')"))

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO agents (name, description) VALUES ('Reviewer', '')"))

    with engine.begin() as conn:
        workflow_id = conn.execute(
            text(
                "INSERT INTO workflows (key, name, description, is_default) "
                "VALUES ('w', 'W', '', 1) RETURNING id"
            )
        ).scalar_one()
        mode_id = conn.execute(
            text(
                "INSERT INTO workflow_modes (workflow_id, key, name, mode_order) "
                "VALUES (:workflow_id, 'default', 'Default', 1) RETURNING id"
            ),
            {"workflow_id": workflow_id},
        ).scalar_one()
        phase_id = conn.execute(
            text(
                "INSERT INTO phases (workflow_id, mode_id, code, name, phase_order) "
                "VALUES (:workflow_id, :mode_id, '1', 'Phase', 1) RETURNING id"
            ),
            {"workflow_id": workflow_id, "mode_id": mode_id},
        ).scalar_one()
        project_id = conn.execute(
            text(
                "INSERT INTO projects (workflow_id, code, name, cli_command, key_prefixes) "
                "VALUES (:workflow_id, 'P1', 'Namespace 1', 'workflow-p1', '[\"RUN\"]') RETURNING id"
            ),
            {"workflow_id": workflow_id},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO tasks (project_id, workflow_id, mode_id, task_key, current_phase_id) "
                "VALUES (:project_id, :workflow_id, :mode_id, 'RUN-42', :phase_id)"
            ),
            {
                "project_id": project_id,
                "workflow_id": workflow_id,
                "mode_id": mode_id,
                "phase_id": phase_id,
            },
        )
        second_workflow_id = conn.execute(
            text("INSERT INTO workflows (key, name, description) VALUES ('w2', 'W2', '') RETURNING id")
        ).scalar_one()
        second_mode_id = conn.execute(
            text(
                "INSERT INTO workflow_modes (workflow_id, key, name, mode_order) "
                "VALUES (:workflow_id, 'default', 'Default', 1) RETURNING id"
            ),
            {"workflow_id": second_workflow_id},
        ).scalar_one()
        second_phase_id = conn.execute(
            text(
                "INSERT INTO phases (workflow_id, mode_id, code, name, phase_order) "
                "VALUES (:workflow_id, :mode_id, '1', 'Phase', 1) RETURNING id"
            ),
            {"workflow_id": second_workflow_id, "mode_id": second_mode_id},
        ).scalar_one()
        second_project_id = conn.execute(
            text(
                "INSERT INTO projects (workflow_id, code, name, cli_command, key_prefixes) "
                "VALUES (:workflow_id, 'P2', 'Namespace 2', 'workflow-p2', '[\"RUN\"]') RETURNING id"
            ),
            {"workflow_id": second_workflow_id},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO tasks (project_id, workflow_id, mode_id, task_key, current_phase_id) "
                "VALUES (:project_id, :workflow_id, :mode_id, 'RUN-42', :phase_id)"
            ),
            {
                "project_id": second_project_id,
                "workflow_id": second_workflow_id,
                "mode_id": second_mode_id,
                "phase_id": second_phase_id,
            },
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO phases (workflow_id, mode_id, code, name, phase_order) "
                    "VALUES (:workflow_id, :mode_id, '0', 'Bad', 0)"
                ),
                {"workflow_id": workflow_id, "mode_id": mode_id},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO phase_instructions (phase_id, step_num, description) VALUES (:id, 0, 'Bad')"),
                {"id": phase_id},
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tasks (project_id, workflow_id, mode_id, task_key, current_phase_id) "
                    "VALUES (:project_id, :workflow_id, :mode_id, 'RUN-42', :phase_id)"
                ),
                {
                    "project_id": project_id,
                    "workflow_id": workflow_id,
                    "mode_id": mode_id,
                    "phase_id": phase_id,
                },
            )


def test_health_requires_migrated_schema_and_hides_internal_details(tmp_path, monkeypatch):
    from project_workflow.infrastructure.db import session
    from project_workflow.interfaces.ui.app import _health

    engine = _sqlite_engine(tmp_path)
    monkeypatch.setattr(session, "get_engine", lambda: engine)
    unavailable = asyncio.run(_health())
    assert unavailable.status_code == 503
    assert b'"error_code":"schema-not-ready"' in unavailable.body
    assert b"sqlite" not in unavailable.body.lower()

    ensure_migrated(engine)
    ready = asyncio.run(_health())
    assert ready.status_code == 200
    assert b'"database":"ok"' in ready.body
    assert b'"schema":"ok"' in ready.body
