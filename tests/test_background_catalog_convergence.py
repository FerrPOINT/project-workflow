"""Both released 0032 histories retain published operator content on convergence."""

from contextlib import contextmanager
from copy import deepcopy

import pytest
import sqlalchemy as sa

from project_workflow.application import catalog_publication as editor
from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.background_professions import ensure_background_professions
from project_workflow.infrastructure.db.session import (
    DatabaseRecreateRequired,
    database_revisions,
    ensure_migrated,
    run_alembic_command,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork

TARGET = "0033_background_convergence"


def snapshot(engine):
    metadata = sa.MetaData()
    metadata.reflect(bind=engine)
    with engine.connect() as connection:
        return {
            table.name: connection.execute(sa.select(table).order_by(*table.primary_key.columns)).mappings().all()
            for table in metadata.sorted_tables if table.name != "alembic_version"
        }


def publish_operator_content(uow, workflow_id):
    active = editor.read_active(uow, workflow_id)
    modes = deepcopy(active["modes"])
    modes[0]["phases"][0]["instructions"][0]["description"] += " Operator research boundary."
    draft = editor.save_draft(uow, workflow_id, CatalogDraft(
        expected_version=active["catalog_version"], expected_sha256=active["content_sha256"], modes=modes,
    ))
    return editor.publish(uow, workflow_id, draft["catalog_version"], CatalogPublish(
        expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
        draft_sha256=draft["content_sha256"], operation_key=f"operator-content:{workflow_id}",
    ), publisher_subject="test-owner")


HISTORIES = [
    ("0032_current_source_baseline", "d035a0ddb06436714b76e40bc8cb68084203011f53dd52436732367690940e85", False),
    ("0032_current_source_defaults", "920379c0c86455148e6fae35e2007037595c2d1cc82116c392c575c4625ffd28", False),
    ("0032_current_source_defaults", "852e0647ad8645c9c6280b21c1595b9efa6ff87754d07df8dcc92bcb04f76381", True),
]


@contextmanager
def published_catalog_history(engine, monkeypatch, history):
    predecessor, manifest, mixed = history
    run_alembic_command("upgrade", engine, "0031_explicit_stage_start" if mixed else predecessor)
    load = catalog.load_profile
    with monkeypatch.context() as historical:
        historical.setattr(catalog, "load_profile", lambda digest=None: load(digest or manifest))
        with SAUnitOfWork(engine) as uow:
            installed = catalog.ensure_single_task_catalog(uow)
            professions = ensure_background_professions(uow)
            pm = next(int(item.workflow_id) for item in installed.bindings if item.role_key == "project_manager")
            bug = uow.projects.get_by_id(professions["BUG_SEARCHER"]).workflow_id
            publications = {workflow_id: publish_operator_content(uow, workflow_id) for workflow_id in (pm, bug)}
    if mixed:
        run_alembic_command("upgrade", engine, predecessor)
        manifest = "920379c0c86455148e6fae35e2007037595c2d1cc82116c392c575c4625ffd28"
    yield engine, predecessor, manifest, publications, mixed


@pytest.fixture(params=HISTORIES)
def published_predecessor(tmp_path, monkeypatch, request):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'background-convergence.db'}")
    try:
        with published_catalog_history(engine, monkeypatch, request.param) as history:
            yield history
    finally:
        engine.dispose()


def test_convergence_preserves_both_published_catalog_histories(published_predecessor):
    engine, _, manifest, publications, mixed = published_predecessor
    before = snapshot(engine)

    ensure_migrated(engine)

    assert database_revisions(engine) == {TARGET}
    after = snapshot(engine)
    if mixed:
        additive = {"workflows", "workflow_modes", "phases", "phase_instructions", "phase_checks",
                    "phase_evidence_requirements", "workflow_catalog_publications"}
        for table in before.keys() - additive:
            assert after[table] == before[table], table
        for table in additive - {"workflows"}:
            assert all(row in after[table] for row in before[table]), table
        assert [{k: v for k, v in row.items() if k != "active_catalog_version"} for row in after["workflows"]] == [
            {k: v for k, v in row.items() if k != "active_catalog_version"} for row in before["workflows"]
        ]
    else:
        assert after == before
    with SAUnitOfWork(engine) as uow:
        assert catalog.observe_installation(uow).instruction_manifest_sha256 == manifest
        for workflow_id, publication in publications.items():
            assert editor.read_active(uow, workflow_id)["content_sha256"] == publication["content_sha256"]
            assert editor.read_operation(uow, workflow_id, f"operator-content:{workflow_id}") == publication
    ensure_migrated(engine)
    assert snapshot(engine) == after


@pytest.mark.parametrize("invalid", ["schema", "publication"])
def test_convergence_refuses_incompatible_schema_or_publication_without_stamping(published_predecessor, invalid):
    engine, predecessor, _, publications, _ = published_predecessor
    with engine.begin() as connection:
        if invalid == "schema":
            connection.execute(sa.text("ALTER TABLE projects ADD COLUMN unsupported_history TEXT"))
        else:
            connection.execute(sa.text(
                "UPDATE workflows SET active_catalog_version=active_catalog_version+1 WHERE id=:id"
            ), {"id": next(iter(publications))})
    before = snapshot(engine)

    with pytest.raises(DatabaseRecreateRequired if invalid == "schema" else (ValueError, ConflictError)):
        ensure_migrated(engine)

    assert database_revisions(engine) == {predecessor}
    assert snapshot(engine) == before
