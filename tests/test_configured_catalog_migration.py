"""Exercise the real forward migration on populated and empty predecessors."""

import pytest
import sqlalchemy as sa

from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.session import ensure_migrated, run_alembic_command
from project_workflow.infrastructure.db.uow import SAUnitOfWork


@pytest.fixture(params=[
    ("0026_analyst_artifact_acceptance", "ab182b9bc6f7182c6250ba20cc322749f6fbae28ddc183765fbd888a658900e6"),
    ("0025_pm_analysis_acceptance", "d76ecbb632b1ceebf33bf78e8e0dedaec278538227d653aa9fd3c998e19ea694"),
    ("0024_analyst_research_catalog", "332cfd4fb3419d5765008e196cffb508540462ddd89b798ab4e89379ac5b1796"),
    ("0019_pm_terminal_resume_retry", "1535516545520eb5ea489cf1583cfaebc458e5729a94762751515841078671c3"),
    ("0023_catalog_publication_author", "e0cde0c044fe1a38b6fa0f387cc30e0da6e89dedb35b89a893263fd7d2558a40"),
])
def predecessor(request):
    return request.param


@pytest.mark.parametrize("role", ["project_manager", "analyst", "developer"])
def test_populated_catalog_upgrade_preserves_task_phase_and_report_history(tmp_path, monkeypatch, predecessor, role):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'populated.db'}")
    assert_populated_catalog_upgrade_preserves_history(engine, monkeypatch, predecessor, role)


def assert_populated_catalog_upgrade_preserves_history(engine, monkeypatch, predecessor, role):
    """The same migration invariant runs on SQLite and real PostgreSQL."""
    try:
        revision, previous = predecessor
        run_alembic_command("upgrade", engine, revision)
        old = catalog.load_profile(previous)
        with monkeypatch.context() as patch:
            patch.setattr(catalog, "load_profile", lambda *_args: old)
            with SAUnitOfWork(engine) as uow:
                installed = catalog.ensure_single_task_catalog(uow)
                binding = next(b for b in installed.bindings if b.role_key == role)
                mode = binding.modes[0]
                phase = int(mode.phase_ids[-1])
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
            checks = connection.execute(sa.text("SELECT id,phase_id FROM phase_checks ORDER BY id")).all()
            evidence = connection.execute(sa.text(
                "SELECT id,phase_id FROM phase_evidence_requirements ORDER BY id"
            )).all()
        ensure_migrated(engine)
        ensure_migrated(engine)
        with SAUnitOfWork(engine) as uow:
            assert catalog.observe_installation(uow).instruction_manifest_sha256 == catalog.MANIFEST_SHA256
        with engine.connect() as connection:
            for name, rows in before.items():
                assert connection.execute(sa.text(f"SELECT * FROM {name}")).mappings().all() == rows
            assert connection.execute(sa.text("SELECT id,code,mode_id FROM phases ORDER BY id")).all() == phases
            if revision in {
                "0024_analyst_research_catalog", "0025_pm_analysis_acceptance", "0026_analyst_artifact_acceptance"
            }:
                # The earlier research migration legitimately adds Analyst checks;
                # these acceptance corrections change existing text only.
                assert connection.execute(sa.text("SELECT id,phase_id FROM phase_checks ORDER BY id")).all() == checks
                assert connection.execute(sa.text(
                    "SELECT id,phase_id FROM phase_evidence_requirements ORDER BY id"
                )).all() == evidence
            assert (
                "0027_analyst_no_pm_return"
                == connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
            )
    finally:
        engine.dispose()


def test_empty_predecessor_receives_current_catalog_after_upgrade(tmp_path, predecessor):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    try:
        run_alembic_command("upgrade", engine, predecessor[0])
        ensure_migrated(engine)
        with SAUnitOfWork(engine) as uow:
            assert catalog.ensure_single_task_catalog(uow).modes == 8
    finally:
        engine.dispose()


@pytest.mark.parametrize("drift", ["instruction", "missing_profession", "phase_check"])
def test_upgrade_refuses_customized_catalog_without_changing_data_or_ledger(tmp_path, monkeypatch, drift, predecessor):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'customized.db'}")
    try:
        revision, previous = predecessor
        run_alembic_command("upgrade", engine, revision)
        old = catalog.load_profile(previous)
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
