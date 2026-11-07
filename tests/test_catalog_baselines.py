"""Source revisions share the existing ledger without consuming operator versions."""

from copy import deepcopy

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, delete, select, update

from project_workflow.application import catalog_publication as editor
from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.session import ensure_migrated, run_alembic_command
from project_workflow.infrastructure.db.uow import SAUnitOfWork

PREVIOUS = "62762bf58f337d9e063226aef58ea6c89cdfb2e87159056f1a6b2b6c4d1ddf3a"


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'baselines.db'}")
    yield engine
    engine.dispose()


@pytest.mark.parametrize("publish", [False, True])
def test_unchanged_operator_revision_survives_migration_and_remains_discoverable(database, monkeypatch, publish):
    run_alembic_command("upgrade", database, "0028_analyst_read_sources")
    reader = catalog.load_profile
    old = reader(PREVIOUS)
    with monkeypatch.context() as patch:
        patch.setattr(catalog, "load_profile", lambda digest=None: reader(digest) if digest else old)
        with SAUnitOfWork(database) as uow:
            installed = catalog.ensure_single_task_catalog(uow)
            workflow_id = int(next(b for b in installed.bindings if b.role_key == "analyst").workflow_id)
            active = editor.read_active(uow, workflow_id)
            saved = editor.save_draft(uow, workflow_id, CatalogDraft(
                expected_version=1, expected_sha256=active["content_sha256"], modes=active["modes"]))
            if publish:
                saved = editor.publish(uow, workflow_id, saved["catalog_version"], CatalogPublish(
                    expected_version=1, expected_sha256=active["content_sha256"],
                    draft_sha256=saved["content_sha256"], operation_key="operator-save"), publisher_subject="qa-admin")
            old_rows = {mode.id: [p.id for p in uow.phases.list(workflow_id, mode_id=mode.id)]
                        for mode in uow.workflows.list_modes(workflow_id, catalog_version=2)}
    ensure_migrated(database)
    ensure_migrated(database)
    with SAUnitOfWork(database) as uow:
        active = editor.read_active(uow, workflow_id)
        assert active["catalog_version"] == 5 and len(active["modes"][0]["phases"]) == 12
        for mode_id, phase_ids in old_rows.items():
            assert [p.id for p in uow.phases.list(workflow_id, mode_id=mode_id)] == phase_ids
        old_revision = editor.read_draft(uow, workflow_id, 2)
        assert old_revision["modes"] == saved["modes"]
        assert old_revision["content_sha256"] == saved["content_sha256"]
        assert old_revision["published"] is publish
        if publish:
            assert editor.read_operation(uow, workflow_id, "operator-save")["modes"] == saved["modes"]
        else:
            assert editor.read_pending_draft(uow, workflow_id)["catalog_version"] == 2
        new_modes = deepcopy(active["modes"])
        new_modes[0]["name"] += " next edit"
        next_draft = editor.save_draft(uow, workflow_id, CatalogDraft(
            expected_version=active["catalog_version"], expected_sha256=active["content_sha256"], modes=new_modes))
        assert next_draft["catalog_version"] == active["catalog_version"] + 1 == 6


@pytest.mark.parametrize("rollback", [1, 2])
def test_selected_pointer_drift_never_relabels_installation_as_an_older_family(database, rollback):
    ensure_migrated(database)
    with SAUnitOfWork(database) as uow:
        installed = catalog.ensure_single_task_catalog(uow)
        workflow_id = int(next(b for b in installed.bindings if b.role_key == "analyst").workflow_id)
        if rollback == 2:
            base = editor.read_active(uow, workflow_id)
            saved = editor.save_draft(uow, workflow_id, CatalogDraft(
                expected_version=base["catalog_version"], expected_sha256=base["content_sha256"], modes=base["modes"]))
            editor.publish(uow, workflow_id, saved["catalog_version"], CatalogPublish(
                expected_version=base["catalog_version"], expected_sha256=base["content_sha256"],
                draft_sha256=saved["content_sha256"], operation_key="after-baseline"), publisher_subject="qa-admin")
        uow.workflows.update(workflow_id, {"active_catalog_version": rollback})
    with SAUnitOfWork(database) as uow:
        with pytest.raises(ValueError, match="pointer changed"):
            catalog.observe_installation(uow)
        with pytest.raises(ValueError, match="pointer changed"):
            editor.read_active(uow, workflow_id)


@pytest.mark.parametrize("field", ["request_sha256", "content_sha256", "content"])
def test_baseline_receipt_is_validated_against_source_not_only_its_saved_hash(database, field):
    ensure_migrated(database)
    with SAUnitOfWork(database) as uow:
        installed = catalog.ensure_single_task_catalog(uow)
        workflow_id = int(next(b for b in installed.bindings if b.role_key == "analyst").workflow_id)
        receipt = uow.session.scalar(select(m.WorkflowCatalogPublication).where(
            m.WorkflowCatalogPublication.workflow_id == workflow_id))
        setattr(receipt, field, "[]" if field == "content" else "0" * 64)
    with SAUnitOfWork(database) as uow:
        with pytest.raises(ConflictError, match="baseline receipt changed"):
            editor.read_active(uow, workflow_id)


def test_replacing_rows_with_an_exact_historical_recipe_cannot_change_the_selected_family(database):
    ensure_migrated(database)
    old = catalog.load_profile("7aa0e6c758e2c31cd1dd69ce30826aecaf565e25e4f5fcedcdf9215fcddd1075")[0]
    old_phase = next(w for w in old["workflows"] if w["role_key"] == "analyst")["modes"][0]["phases"][3]
    with SAUnitOfWork(database) as uow:
        installed = catalog.ensure_single_task_catalog(uow)
        binding = next(b for b in installed.bindings if b.role_key == "analyst")
        phase_id = int(binding.modes[0].phase_ids[3])
        for row, original in zip(uow.phase_instructions.list(phase_id), old_phase["instructions"], strict=True):
            uow.phase_instructions.update(row["id"], {"description": original["description"]})
        for table, field in [(m.PhaseCheck, "checks"), (m.PhaseEvidenceRequirement, "evidence")]:
            rows = uow.session.scalars(select(table).where(table.phase_id == phase_id).order_by(table.id)).all()
            for row, original in zip(rows, old_phase[field], strict=True):
                uow.session.execute(update(table).where(table.id == row.id).values(description=original))
    with SAUnitOfWork(database) as uow:
        with pytest.raises(ValueError):
            catalog.observe_installation(uow)


def test_publication_cannot_forge_a_bootstrap_operation():
    # The existing public key grammar excludes the private source-operation namespace.
    with pytest.raises(ValidationError, match="operation_key"):
        CatalogPublish(expected_version=1, expected_sha256="a" * 64,
                       draft_sha256="b" * 64, operation_key="@catalog-baseline:1:source")


def test_replaying_a_source_baseline_never_resets_a_newer_operator_publication(database):
    ensure_migrated(database)
    with SAUnitOfWork(database) as uow:
        installed = catalog.ensure_single_task_catalog(uow)
        workflow_id = int(next(b for b in installed.bindings if b.role_key == "analyst").workflow_id)
        base = editor.read_active(uow, workflow_id)
        saved = editor.save_draft(uow, workflow_id, CatalogDraft(
            expected_version=2, expected_sha256=base["content_sha256"], modes=base["modes"]))
        published = editor.publish(uow, workflow_id, saved["catalog_version"], CatalogPublish(
            expected_version=2, expected_sha256=base["content_sha256"],
            draft_sha256=saved["content_sha256"], operation_key="newer-publication"), publisher_subject="qa-admin")
        assert editor.publish_baseline(uow, uow.workflows.get_by_id(workflow_id), catalog.MANIFEST_SHA256) == 2
        assert editor.read_active(uow, workflow_id)["catalog_version"] == published["catalog_version"] == 3


@pytest.mark.parametrize("drift", [False, True])
def test_already_applied_0029_is_sealed_without_rewriting_its_modes(database, monkeypatch, drift):
    run_alembic_command("upgrade", database, "0028_analyst_read_sources")
    reader = catalog.load_profile
    old = reader(PREVIOUS)
    with monkeypatch.context() as patch:
        patch.setattr(catalog, "load_profile", lambda digest=None: reader(digest) if digest else old)
        with SAUnitOfWork(database) as uow:
            installed = catalog.ensure_single_task_catalog(uow)
            workflow_id = int(next(b for b in installed.bindings if b.role_key == "analyst").workflow_id)
    run_alembic_command("upgrade", database, "0029_analyst_twelve_phases")
    with SAUnitOfWork(database) as uow:
        # The previously published 0029 had these modes but no baseline receipt.
        uow.session.execute(delete(m.WorkflowCatalogPublication).where(
            m.WorkflowCatalogPublication.workflow_id == workflow_id))
        mode = uow.workflows.list_modes(workflow_id, catalog_version=2)[0]
        old_ids = [p.id for p in uow.phases.list(workflow_id, mode_id=mode.id)]
        if drift:
            instruction = uow.phase_instructions.list(old_ids[0])[0]
            uow.phase_instructions.update(instruction["id"], {"description": "unrecognized mutation"})
    if drift:
        with pytest.raises(ValueError, match="different|diverg|mismatch"):
            ensure_migrated(database)
        with SAUnitOfWork(database) as uow:
            assert uow.session.scalar(select(m.WorkflowCatalogPublication).where(
                m.WorkflowCatalogPublication.workflow_id == workflow_id)) is None
    else:
        ensure_migrated(database)
        ensure_migrated(database)
        with SAUnitOfWork(database) as uow:
            assert [p.id for p in uow.phases.list(workflow_id, mode_id=mode.id)] == old_ids
            assert editor.read_active(uow, workflow_id)["catalog_version"] == 4
            assert len(editor.read_revision(uow, uow.workflows.get_by_id(workflow_id), 2)["modes"][0]["phases"]) == 12
