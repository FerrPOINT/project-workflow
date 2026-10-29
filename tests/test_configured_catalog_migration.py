"""Exercise the real forward migration on populated and empty predecessors."""

import pytest
import sqlalchemy as sa

from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.session import ensure_migrated, run_alembic_command
from project_workflow.infrastructure.db.uow import SAUnitOfWork

PREVIOUS = "1535516545520eb5ea489cf1583cfaebc458e5729a94762751515841078671c3"


def test_populated_catalog_upgrade_preserves_task_phase_and_report_history(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'populated.db'}")
    try:
        run_alembic_command("upgrade", engine, "0019_pm_terminal_resume_retry")
        old = catalog.load_profile(PREVIOUS)
        with monkeypatch.context() as patch:
            patch.setattr(catalog, "load_profile", lambda *_args: old)
            with SAUnitOfWork(engine) as uow:
                installed = catalog.ensure_single_task_catalog(uow)
                binding = next(b for b in installed.bindings if b.role_key == "developer")
                mode = binding.modes[0]
                phase = int(mode.phase_ids[1])
                task = uow.tasks.create(
                    {
                        "project_id": int(binding.namespace_id),
                        "workflow_id": int(binding.workflow_id),
                        "mode_id": int(mode.mode_id),
                        "task_key": "PRESERVE-42",
                        "title": "Unfinished business work",
                        "current_phase_id": phase,
                        "status": "active",
                    }
                )
                uow.record_step(
                    task_id=task,
                    phase_id=phase,
                    verdict="partial",
                    worker_report="Original saved report",
                    covered_item_ids=["old-check"],
                    missing_item_ids=[],
                    blocker_messages=[],
                    evaluation_snapshot={"original": "immutable instructions at evaluation time"},
                    supervisor_response={"status": "active", "original": True},
                )
                uow.commit()
        with engine.connect() as connection:
            before = {
                name: connection.execute(sa.text(f"SELECT * FROM {name}")).mappings().all()
                for name in ("tasks", "task_step_history")
            }
            phases = connection.execute(sa.text("SELECT id,code,mode_id FROM phases ORDER BY id")).all()
        ensure_migrated(engine)
        ensure_migrated(engine)
        with SAUnitOfWork(engine) as uow:
            assert catalog.observe_installation(uow).instruction_manifest_sha256 != PREVIOUS
        with engine.connect() as connection:
            for name, rows in before.items():
                assert connection.execute(sa.text(f"SELECT * FROM {name}")).mappings().all() == rows
            assert connection.execute(sa.text("SELECT id,code,mode_id FROM phases ORDER BY id")).all() == phases
            assert (
                "0021_profession_task_workflows"
                == connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
            )
    finally:
        engine.dispose()


def test_empty_predecessor_receives_current_catalog_after_upgrade(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    try:
        run_alembic_command("upgrade", engine, "0019_pm_terminal_resume_retry")
        ensure_migrated(engine)
        with SAUnitOfWork(engine) as uow:
            assert catalog.ensure_single_task_catalog(uow).modes == 8
    finally:
        engine.dispose()


@pytest.mark.parametrize("drift", ["instruction", "missing_profession", "phase_check"])
def test_upgrade_refuses_customized_catalog_without_changing_data_or_ledger(tmp_path, monkeypatch, drift):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'customized.db'}")
    try:
        run_alembic_command("upgrade", engine, "0019_pm_terminal_resume_retry")
        old = catalog.load_profile(PREVIOUS)
        with monkeypatch.context() as patch:
            patch.setattr(catalog, "load_profile", lambda *_args: old)
            with SAUnitOfWork(engine) as uow:
                installed = catalog.ensure_single_task_catalog(uow)
                phase = int(installed.bindings[0].modes[0].phase_ids[0])
                if drift == "instruction":
                    instruction = uow.phase_instructions.list(phase)[0]
                    uow.phase_instructions.update(instruction["id"], {
                        "description": instruction["description"] + "\nCustom security: preserve owner approval."
                    })
                elif drift == "phase_check":
                    from project_workflow.infrastructure.db import models as m

                    uow.session.add(m.PhaseCheck(phase_id=phase, description="Custom security condition"))
                else:
                    from project_workflow.infrastructure.db import models as m

                    binding = installed.bindings[0]
                    uow.session.delete(uow.session.get(m.ProfessionWorkflow,
                        (int(binding.workflow_id), int(binding.namespace_id))))
                uow.commit()
        tables = sa.MetaData()
        tables.reflect(bind=engine)

        def snapshot():
            with engine.connect() as connection:
                return {table.name: connection.execute(sa.select(table)).mappings().all()
                        for table in tables.sorted_tables}

        before = snapshot()
        with pytest.raises(ValueError, match="partial or customized"):
            ensure_migrated(engine)
        assert snapshot() == before
    finally:
        engine.dispose()
