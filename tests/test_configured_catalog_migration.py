"""Exercise the real forward migration on populated and empty predecessors."""

import pytest
import sqlalchemy as sa

from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.session import ensure_migrated, run_alembic_command
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._historical_catalog import historical_catalog


@pytest.fixture(params=[
    ("0028_analyst_read_sources", "62762bf58f337d9e063226aef58ea6c89cdfb2e87159056f1a6b2b6c4d1ddf3a"),
    ("0027_analyst_no_pm_return", "9384121a0c1bc9c869a25fcdf11cab4064a0491ebcf329a6310229874ab835d0"),
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
        with historical_catalog(previous):
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
            current = catalog.observe_installation(uow)
            assert current.instruction_manifest_sha256 == (
                "d035a0ddb06436714b76e40bc8cb68084203011f53dd52436732367690940e85"
            )
            analyst = next(b for b in current.bindings if b.role_key == "analyst")
            assert len(analyst.modes[0].phase_ids) == 12
            from project_workflow.application.catalog_publication import read_revision

            workflow = uow.workflows.get_by_id(int(analyst.workflow_id))
            assert workflow.active_catalog_version == 5
            assert len(read_revision(uow, workflow, 1)["modes"][0]["phases"]) == 3
            assert len(read_revision(uow, workflow, 2)["modes"][0]["phases"]) == 12
        with engine.connect() as connection:
            for name, rows in before.items():
                assert connection.execute(sa.text(f"SELECT * FROM {name}")).mappings().all() == rows
            after_phases = connection.execute(sa.text("SELECT id,code,mode_id FROM phases ORDER BY id")).all()
            assert after_phases[:len(phases)] == phases
            assert len(after_phases) == len(phases) + 24 + 33 + 33
            new_modes = connection.execute(sa.text(
                "SELECT id FROM workflow_modes"
            )).scalars().all()
            assert {row.mode_id for row in after_phases[len(phases):]} == set(new_modes) - {
                row.mode_id for row in phases}
            if revision in {
                "0024_analyst_research_catalog", "0025_pm_analysis_acceptance", "0026_analyst_artifact_acceptance",
                "0027_analyst_no_pm_return", "0028_analyst_read_sources"
            }:
                # The earlier research migration legitimately adds Analyst checks;
                # existing item identities remain while the new baseline appends its own.
                assert connection.execute(sa.text(
                    "SELECT id,phase_id FROM phase_checks ORDER BY id"
                )).all()[:len(checks)] == checks
                assert connection.execute(sa.text(
                    "SELECT id,phase_id FROM phase_evidence_requirements ORDER BY id"
                )).all()[:len(evidence)] == evidence
            assert (
                "0032_current_source_baseline"
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
        with historical_catalog(previous):
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


@pytest.mark.parametrize("role", ["analyst", "developer"])
@pytest.mark.parametrize("published", [False, True])
def test_structural_upgrade_preserves_operator_publications_and_drafts(tmp_path, monkeypatch, role, published):
    from project_workflow.application import catalog_publication as editor
    from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish

    engine = sa.create_engine(f"sqlite:///{tmp_path / 'publications.db'}")
    try:
        run_alembic_command("upgrade", engine, "0028_analyst_read_sources")
        with historical_catalog("62762bf58f337d9e063226aef58ea6c89cdfb2e87159056f1a6b2b6c4d1ddf3a"):
            with SAUnitOfWork(engine) as uow:
                installed = catalog.ensure_single_task_catalog(uow)
                workflow_id = int(next(b for b in installed.bindings if b.role_key == role).workflow_id)
                base = editor.read_active(uow, workflow_id)
                base["modes"][0]["phases"][0]["name"] += " custom clarification"
                saved = editor.save_draft(uow, workflow_id, CatalogDraft(
                    expected_version=1, expected_sha256=base["content_sha256"], modes=base["modes"]))
                if published:
                    saved = editor.publish(uow, workflow_id, saved["catalog_version"], CatalogPublish(
                        expected_version=1, expected_sha256=base["content_sha256"],
                        draft_sha256=saved["content_sha256"], operation_key="retained-publication"),
                        publisher_subject="verified-qa-admin")
        tables = sa.MetaData()
        tables.reflect(bind=engine)

        def snapshot():
            with engine.connect() as connection:
                return {t.name: connection.execute(sa.select(t)).mappings().all() for t in tables.sorted_tables}

        before = snapshot()
        if published and role == "developer":
            with pytest.raises(ValueError, match="Explicit Start cutover publication required"):
                ensure_migrated(engine)
            assert snapshot() == before
            with historical_catalog("62762bf58f337d9e063226aef58ea6c89cdfb2e87159056f1a6b2b6c4d1ddf3a"), \
                    SAUnitOfWork(engine) as uow:
                assert editor.read_operation(uow, workflow_id, "retained-publication") == saved
                assert editor.read_active(uow, workflow_id)["catalog_version"] == saved["catalog_version"]
            return
        ensure_migrated(engine)
        with SAUnitOfWork(engine) as uow:
            assert catalog.observe_installation(uow).phases == 33
            read = (editor.read_operation(uow, workflow_id, "retained-publication") if published
                    else editor.read_draft(uow, workflow_id, saved["catalog_version"]))
            if not published:
                assert read.pop("active_catalog_version") == uow.workflows.get_by_id(workflow_id).active_catalog_version
                saved.pop("active_catalog_version")
            assert read == saved
        after = snapshot()
        assert after["task_step_history"] == before["task_step_history"]
    finally:
        engine.dispose()
