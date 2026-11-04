"""The migration entrypoint installs defaults and preserves populated catalogs."""

from sqlalchemy import create_engine, text

from project_workflow import config
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog
from project_workflow.infrastructure.db.session import reset_engine, run_alembic_command
from project_workflow.infrastructure.db.single_task_catalog import observe_installation
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from scripts.init_db import main


def test_migration_entrypoint_creates_current_namespace_defaults_and_is_repeatable(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.fixture.invalid")
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", "https://auth.fixture.invalid")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "migration-fixture-session-secret-32-characters")
    monkeypatch.setattr(config, "CATALOG_VARIANT", "single-task-v1")
    url = f"sqlite:///{tmp_path / 'defaults.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config.get_settings.cache_clear()
    reset_engine()
    try:
        assert main() == 0
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                before = [tuple(row) for row in connection.execute(text(
                    "SELECT p.id,p.cli_command,p.workflow_id,w.key,w.name "
                    "FROM projects p JOIN workflows w ON w.id=p.workflow_id ORDER BY p.id"
                ))]
                assert len(before) == 7
                assert len({row[2] for row in before}) == 7
                assert all(row[4] == "Дефолтный" for row in before)
                assert all(row[1] == "workflow-single-task-" + row[3].split(":", 1)[1].replace("_", "-")
                           for row in before)
                assert connection.execute(text("SELECT count(*) FROM phases")).scalar_one() > 0
            with SAUnitOfWork(engine) as uow:
                installation = observe_installation(uow)
                assert {int(item.namespace_id) for item in installation.bindings} == {row[0] for row in before}
            assert main() == 0
            with engine.connect() as connection:
                assert [tuple(row) for row in connection.execute(text(
                    "SELECT p.id,p.cli_command,p.workflow_id,w.key,w.name "
                    "FROM projects p JOIN workflows w ON w.id=p.workflow_id ORDER BY p.id"
                ))] == before
            with SAUnitOfWork(engine) as uow:
                assert observe_installation(uow) == installation
        finally:
            engine.dispose()
    finally:
        reset_engine()
        config.get_settings.cache_clear()


def test_upgrade_renames_only_managed_workflows_and_preserves_edits_and_history(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'existing.db'}")
    try:
        assert_upgrade_preserves_catalog(engine, tmp_path)
    finally:
        engine.dispose()


def assert_upgrade_preserves_catalog(engine, tmp_path):
    run_alembic_command("upgrade", engine)
    with SAUnitOfWork(engine) as uow:
        catalog = ensure_managed_catalog(uow)
        for definition in catalog.workflows:
            workflow = next(item for item in uow.workflows.list() if item.key == definition.key)
            uow.workflows.update(workflow.id, {"name": definition.name})
        namespace = uow.projects.get_by_cli_command("workflow-developer")
        mode = uow.workflows.get_mode_by_key(namespace.workflow_id, "initial")
        phase = uow.phases.list(namespace.workflow_id, mode_id=mode.id)[0]
        instruction = uow.phase_instructions.list(phase.id)[0]
        uow.phase_instructions.update(instruction["id"], {"description": "Preserved custom instructions"})
        task_id = uow.tasks.create({
            "project_id": namespace.id, "workflow_id": namespace.workflow_id,
            "mode_id": phase.mode_id, "task_key": "DV-42", "title": "Keep this task",
            "current_phase_id": phase.id, "status": "active",
        })
        uow.record_step(task_id=task_id, phase_id=phase.id, verdict="pass", worker_report="Saved report",
                        covered_item_ids=[], missing_item_ids=[], blocker_messages=[],
                        evaluation_snapshot={}, supervisor_response={})
        uow.workflows.create({"key": "user:custom", "name": "Custom workflow", "is_default": False})
    from importlib import import_module

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    tables = ["projects", "workflow_modes", "phases", "phase_instructions", "tasks", "task_step_history"]
    with engine.connect() as connection:
        before = {table: [tuple(row) for row in connection.execute(text(f"SELECT * FROM {table} ORDER BY id"))]
                  for table in tables}
    with engine.begin() as connection:
        migration = import_module("project_workflow.infrastructure.db.migrations.versions.0010_namespace_default_names")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
    with engine.connect() as connection:
        for table in tables:
            rows = connection.execute(text(f"SELECT * FROM {table} ORDER BY id"))
            assert [tuple(row) for row in rows] == before[table]
        assert connection.execute(text("SELECT name FROM workflows WHERE key='user:custom'")).scalar_one() == (
            "Custom workflow"
        )
    with SAUnitOfWork(engine) as uow:
        assert all(w.name == "Дефолтный" for w in uow.workflows.list() if w.key.startswith("hermes-sdlc:"))
        assert uow.tasks.get_by_id(task_id).task_key == "DV-42"
        assert uow.step_history.list(task_id=task_id)[0].worker_report == "Saved report"
