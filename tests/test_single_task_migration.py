"""One actual predecessor upgrade preserves legacy data and strict CHECKs."""

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog
from project_workflow.infrastructure.db.session import ensure_migrated, run_alembic_command
from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def test_actual_0014_upgrade_preserves_legacy_predicates_rows_and_history(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'upgrade.db'}")
    try:
        run_alembic_command("upgrade", engine, "0014_launch_profile_only")
        before_checks = {c["name"]: c["sqltext"] for c in
                         sa.inspect(engine).get_check_constraints("task_runtime_assignments")}
        with SAUnitOfWork(engine) as uow:
            ensure_managed_catalog(uow)
            project = uow.projects.get_by_cli_command("workflow-developer")
            mode = uow.workflows.get_mode_by_key(project.workflow_id, "initial")
            phase = uow.phases.list(project.workflow_id, mode_id=mode.id)[0]
            task_id = uow.tasks.create({"project_id": project.id, "workflow_id": project.workflow_id,
                                        "mode_id": mode.id, "task_key": "OLD-9", "title": "Legacy",
                                        "current_phase_id": phase.id, "status": "active"})
            uow.record_step(task_id=task_id, phase_id=phase.id, verdict="pass", worker_report="Legacy",
                            covered_item_ids=[], missing_item_ids=[], blocker_messages=[],
                            evaluation_snapshot={"original": "unchanged"}, supervisor_response={"status": "active"})
            table = sa.Table("task_runtime_assignments", sa.MetaData(), autoload_with=uow.session.connection())
            uow.session.execute(table.insert().values(operation_key="legacy:empty", task_id=task_id,
                                project_id=project.id, workflow_id=project.workflow_id, mode_id=mode.id,
                                cycle_number=0, assignment_revision=1, payload="{}"))
            uow.commit()
        with engine.connect() as connection:
            metadata = sa.MetaData()
            metadata.reflect(connection)
            before = {name: [dict(r) for r in connection.execute(sa.select(table)).mappings()]
                      for name, table in metadata.tables.items() if name != "alembic_version"}
        ensure_migrated(engine)
        ensure_migrated(engine)
        after_checks = {c["name"]: c["sqltext"] for c in
                        sa.inspect(engine).get_check_constraints("task_runtime_assignments")}
        for name, sql in before_checks.items():
            assert sql in after_checks[name]
        with engine.connect() as connection:
            metadata = sa.MetaData()
            metadata.reflect(connection)
            for name, previous in before.items():
                current = [dict(r) for r in connection.execute(sa.select(metadata.tables[name])).mappings()]
                if name == "task_runtime_assignments":
                    assert all(r.pop("single_task_binding_json") is None for r in current)
                assert current == previous, name
        with SAUnitOfWork(engine) as uow:
            ensure_single_task_catalog(uow)
            assert uow.tasks.get_by_key("OLD-9").id == task_id
        # Legacy delivery missing tech pair must remain rejected by the old CHECK.
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(m.TaskRuntimeAssignment.__table__.insert().values(
                operation_key="legacy:invalid", task_id=task_id, project_id=project.id,
                workflow_id=project.workflow_id, mode_id=mode.id, cycle_number=0, assignment_revision=2,
                workflow_key="hermes-sdlc:developer", role_key="developer", execution_scope="delivery",
                stage_key="development", attempt_number=1, business_task_ref="task", root_task_ref="root",
                work_item_ref="item", work_item_revision=1, queue_item_ref="queue", task_workspace_ref="workspace",
                workspace_revision=1, decomposition_revision_ref="decomposition", stage_revision="stage",
                assignment_ref="assignment", workspace_generation=1, lease_generation=1,
                exact_input_refs="[]", payload_sha256="a" * 64, payload="{}",
            ))
    finally:
        engine.dispose()
