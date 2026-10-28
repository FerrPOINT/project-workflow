"""Task history survives independently of the profession's legacy default."""

import pytest
from sqlalchemy import create_engine, delete, inspect, select

from project_workflow.infrastructure.db.models import ProfessionWorkflow
from project_workflow.infrastructure.db.session import ensure_migrated, run_alembic_command
from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def test_fresh_database_tasks_keep_independent_profession_and_workflow_constraints(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.sqlite'}")
    try:
        ensure_migrated(engine)
        keys = inspect(engine).get_foreign_keys("tasks")
        assert not any(k["referred_table"] == "profession_workflows" for k in keys)
        assert any(k["referred_table"] == "projects" and k["constrained_columns"] == ["project_id"] for k in keys)
        assert any(k["referred_table"] == "workflows" for k in keys)
        run_alembic_command("downgrade", engine, "0020_configured_cli_catalog")
        ensure_migrated(engine)
    finally:
        engine.dispose()


def test_populated_upgrade_keeps_task_and_report_and_accepts_another_workflow(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'populated.sqlite'}")
    try:
        assert_populated_upgrade_preserves_collection_history(engine)
    finally:
        engine.dispose()


def assert_populated_upgrade_preserves_collection_history(engine):
    run_alembic_command("upgrade", engine, "0020_configured_cli_catalog")
    with SAUnitOfWork(engine) as uow:
        binding = ensure_single_task_catalog(uow).bindings[0]
        namespace, workflow = int(binding.namespace_id), int(binding.workflow_id)
        mode = binding.modes[0]
        task = uow.tasks.create(
            {
                "project_id": namespace,
                "workflow_id": workflow,
                "mode_id": int(mode.mode_id),
                "task_key": "OLD-1",
                "current_phase_id": int(mode.phase_ids[0]),
                "status": "active",
            }
        )
        uow.record_step(
            task_id=task,
            phase_id=int(mode.phase_ids[0]),
            verdict="partial",
            worker_report="Historical report; must remain unchanged",
            covered_item_ids=[],
            missing_item_ids=[],
            blocker_messages=[],
            evaluation_snapshot={},
            supervisor_response={"message": "Historical response"},
        )
        before = [row.to_dict() for row in uow.step_history.list(task_id=task)]
        empty_workflow = uow.workflows.create({"name": "Detached empty default"})
        empty_profession = uow.projects.create({"workflow_id": empty_workflow, "name": "Edited collection",
                                               "code": "edited-empty-collection"})
        uow.session.execute(delete(ProfessionWorkflow).where(ProfessionWorkflow.profession_id == empty_profession))
        memberships = uow.session.execute(select(ProfessionWorkflow.workflow_id, ProfessionWorkflow.profession_id)
                                         .order_by(ProfessionWorkflow.workflow_id,
                                                   ProfessionWorkflow.profession_id)).all()
    ensure_migrated(engine)
    with SAUnitOfWork(engine) as uow:
        assert uow.session.execute(select(ProfessionWorkflow.workflow_id, ProfessionWorkflow.profession_id)
                                   .order_by(ProfessionWorkflow.workflow_id,
                                             ProfessionWorkflow.profession_id)).all() == memberships
        assert not uow.workflows.list_by_profession(empty_profession)
        assert uow.tasks.get_by_id(task).task_key == "OLD-1"
        assert [row.to_dict() for row in uow.step_history.list(task_id=task)] == before
        extra = uow.workflows.create({"key": "extra-files", "name": "Extra", "create_default_mode": False})
        uow.workflows.assign_profession(extra, namespace)
        extra_mode = uow.workflows.create_mode({"workflow_id": extra, "key": "draft", "mode_order": 1})
        phase = uow.phases.create(
            {"workflow_id": extra, "mode_id": extra_mode, "code": "FILE-1", "name": "Files", "phase_order": 1}
        )
        uow.tasks.create(
            {
                "project_id": namespace,
                "workflow_id": extra,
                "mode_id": extra_mode,
                "task_key": "NEW-1",
                "current_phase_id": phase,
                "status": "active",
            }
        )
    with pytest.raises(RuntimeError, match="history prevents downgrade"):
        run_alembic_command("downgrade", engine, "0020_configured_cli_catalog")
    with SAUnitOfWork(engine) as uow:
        assert [row.to_dict() for row in uow.step_history.list(task_id=task)] == before
        assert uow.tasks.get_by_key("NEW-1", project_id=namespace) is not None
