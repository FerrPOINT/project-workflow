"""The released background sibling preserves its original append-only cutover."""

from copy import deepcopy

import pytest
import sqlalchemy as sa

from project_workflow.application import catalog_publication as editor
from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.session import ensure_migrated, run_alembic_command
from project_workflow.infrastructure.db.uow import SAUnitOfWork

PREVIOUS = "852e0647ad8645c9c6280b21c1595b9efa6ff87754d07df8dcc92bcb04f76381"
TARGET = "920379c0c86455148e6fae35e2007037595c2d1cc82116c392c575c4625ffd28"


@pytest.fixture
def predecessor(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'source-defaults.db'}")
    run_alembic_command("upgrade", engine, "0031_explicit_stage_start")
    reader = catalog.load_profile
    with monkeypatch.context() as old:
        old.setattr(catalog, "load_profile", lambda digest=None: reader(digest) if digest else reader(PREVIOUS))
        with SAUnitOfWork(engine) as uow:
            installed = catalog.ensure_single_task_catalog(uow)
            workflows = {binding.role_key: int(binding.workflow_id) for binding in installed.bindings}
    yield engine, workflows, reader
    engine.dispose()


def snapshot(engine):
    tables = sa.MetaData()
    tables.reflect(bind=engine)
    with engine.connect() as connection:
        return {table.name: connection.execute(sa.select(table)).mappings().all()
                for table in tables.sorted_tables}


def test_upgrade_is_append_only_idempotent_and_preserves_unrelated_publication(predecessor, monkeypatch):
    engine, workflows, reader = predecessor
    with monkeypatch.context() as old:
        old.setattr(catalog, "load_profile", lambda digest=None: reader(digest) if digest else reader(PREVIOUS))
        with SAUnitOfWork(engine) as uow:
            active = editor.read_active(uow, workflows["project_manager"])
            modes = deepcopy(active["modes"])
            modes[0]["name"] += " Operator wording"
            draft = editor.save_draft(uow, active["workflow_id"], CatalogDraft(
                expected_version=active["catalog_version"], expected_sha256=active["content_sha256"], modes=modes))
            published = editor.publish(uow, active["workflow_id"], draft["catalog_version"], CatalogPublish(
                expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
                draft_sha256=draft["content_sha256"], operation_key="unrelated-human-publication"),
                publisher_subject="controlled-owner")
    before = snapshot(engine)
    run_alembic_command("upgrade", engine, "0032_current_source_defaults")
    with SAUnitOfWork(engine) as uow:
        # The historical sibling sealed only changed roles. The forward
        # convergence must retain this material while completing its receipts.
        assert catalog._observe_profile(uow, *reader(TARGET)).instruction_manifest_sha256 == TARGET
        workflow = uow.workflows.get_by_id(workflows["project_manager"])
        retained = editor.read_revision(uow, workflow, published["catalog_version"], selected=True)
        assert {**retained, "published": True} == published
        with pytest.raises(ValueError, match="Sealed baseline manifest differs"):
            editor.read_operation(uow, workflows["project_manager"], "unrelated-human-publication")
    after = snapshot(engine)
    for table in ("phases", "phase_instructions", "phase_checks", "phase_evidence_requirements",
                  "workflow_modes", "workflow_catalog_publications", "tasks", "task_step_history"):
        assert all(row in after[table] for row in before[table]), table
    ensure_migrated(engine)
    converged = snapshot(engine)
    for table in ("phases", "phase_instructions", "phase_checks", "phase_evidence_requirements",
                  "workflow_modes", "workflow_catalog_publications", "tasks", "task_step_history"):
        assert all(row in converged[table] for row in after[table]), table
    with SAUnitOfWork(engine) as uow:
        assert catalog.observe_installation(uow).instruction_manifest_sha256 == TARGET
        assert editor.read_active(uow, workflows["project_manager"])["content_sha256"] == published["content_sha256"]
        assert editor.read_operation(uow, workflows["project_manager"], "unrelated-human-publication") == published
    ensure_migrated(engine)
    assert snapshot(engine) == converged


@pytest.mark.parametrize("role", ["analyst", "architect"])
def test_selected_custom_content_blocks_upgrade_before_any_write(predecessor, monkeypatch, role):
    engine, workflows, reader = predecessor
    with monkeypatch.context() as old:
        old.setattr(catalog, "load_profile", lambda digest=None: reader(digest) if digest else reader(PREVIOUS))
        with SAUnitOfWork(engine) as uow:
            active = editor.read_active(uow, workflows[role])
            modes = deepcopy(active["modes"])
            modes[0]["phases"][0]["name"] += " Human decision"
            draft = editor.save_draft(uow, active["workflow_id"], CatalogDraft(
                expected_version=active["catalog_version"], expected_sha256=active["content_sha256"], modes=modes))
            editor.publish(uow, active["workflow_id"], draft["catalog_version"], CatalogPublish(
                expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
                draft_sha256=draft["content_sha256"], operation_key="selected-human-publication"),
                publisher_subject="controlled-owner")
    before = snapshot(engine)
    with pytest.raises(ValueError, match="source-default cutover publication required"):
        run_alembic_command("upgrade", engine, "0032_current_source_defaults")
    assert snapshot(engine) == before
