"""A legitimate published PM must never be rewritten by a catalog upgrade."""

from copy import deepcopy
from traceback import extract_tb

import pytest
import sqlalchemy as sa

from project_workflow.application import catalog_publication as editor
from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.session import (
    database_revisions,
    ensure_migrated,
    get_engine,
    initialization_transaction,
    run_alembic_command,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._report_helpers import report_json
from tests.test_postgres_integration import pg_url as pg_url

PREDECESSOR = "0023_catalog_publication_author"
PROFILE = "e0cde0c044fe1a38b6fa0f387cc30e0da6e89dedb35b89a893263fd7d2558a40"
TARGETS = (
    "332cfd4fb3419d5765008e196cffb508540462ddd89b798ab4e89379ac5b1796",
    "d76ecbb632b1ceebf33bf78e8e0dedaec278538227d653aa9fd3c998e19ea694",
)


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    """These cases own historical schemas, not the shared current seed."""
    yield


def test_published_pm_upgrade_refuses_without_mutating_history(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'published-pm.db'}")
    assert_published_pm_upgrade_refuses_without_mutating_history(engine, monkeypatch)


@pytest.mark.integration
def test_published_pm_upgrade_refuses_without_mutating_history_on_postgres(pg_url, monkeypatch):
    assert_published_pm_upgrade_refuses_without_mutating_history(get_engine(pg_url), monkeypatch)


def assert_published_pm_upgrade_refuses_without_mutating_history(engine, monkeypatch):
    try:
        run_alembic_command("upgrade", engine, PREDECESSOR)
        reader = catalog.load_profile
        predecessor = reader(PROFILE)
        with monkeypatch.context() as patch:
            patch.setattr(catalog, "load_profile", lambda digest=None: reader(digest) if digest else predecessor)
            with SAUnitOfWork(engine) as uow:
                installed = catalog.ensure_single_task_catalog(uow)
                workflow_id = int(next(b for b in installed.bindings if b.role_key == "project_manager").workflow_id)
                for version in range(2, 14):
                    active = editor.read_active(uow, workflow_id)
                    modes = deepcopy(active["modes"])
                    modes[0]["phases"][0]["instructions"][0]["description"] += f" Published PM clarification {version}."
                    saved = editor.save_draft(uow, workflow_id, CatalogDraft(
                        expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
                        modes=modes,
                    ))
                    published = editor.publish(uow, workflow_id, saved["catalog_version"], CatalogPublish(
                        expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
                        draft_sha256=saved["content_sha256"], operation_key=f"published-pm-{version}",
                    ), publisher_subject="verified-test-admin")
                    assert published["catalog_version"] == version

        with SAUnitOfWork(engine) as uow:
            catalog._observe_profile(uow, *predecessor)
            assert editor.read_active(uow, workflow_id)["catalog_version"] == 13
            assert all(w.active_catalog_version == (13 if w.id == workflow_id else 1) for w in uow.workflows.list())
            for digest in TARGETS:
                with pytest.raises(ValueError):
                    catalog._observe_profile(uow, *reader(digest))
            mode = uow.workflows.list_modes(workflow_id)[0]
            assert mode.catalog_version == 13
            phase = uow.phases.list(workflow_id, mode_id=mode.id)[0]
            binding = next(b for b in installed.bindings if b.role_key == "project_manager")
            task_id = uow.tasks.create({
                "project_id": int(binding.namespace_id), "workflow_id": workflow_id,
                "mode_id": mode.id, "task_key": "PUBLISHED-PM-13",
                "title": "Unfinished work on the published PM revision",
                "current_phase_id": phase.id, "status": "active",
            })
            history_id = uow.record_step(
                task_id=task_id, phase_id=phase.id, mode_id=mode.id, cycle_number=1,
                verdict="partial", worker_report=report_json("Original incomplete business document"),
                covered_item_ids=[], missing_item_ids=["saved-required-item"], blocker_messages=[],
                evaluation_snapshot={"fixture": "Original saved assessment before catalog upgrade"},
                supervisor_response={"verdict": "PARTIAL", "complete": False},
            )

        tables = sa.MetaData()
        tables.reflect(bind=engine)

        def snapshot():
            with engine.connect() as connection:
                return {
                    table.name: connection.execute(
                        sa.select(table).order_by(*table.primary_key.columns),
                    ).mappings().all()
                    for table in tables.sorted_tables
                }

        before = snapshot()
        assert len(before["tasks"]) == len(before["task_step_history"]) == 1
        assert before["tasks"][0]["id"] == task_id
        assert before["tasks"][0]["mode_id"] == mode.id
        assert before["task_step_history"][0]["id"] == history_id
        assert before["task_step_history"][0]["task_id"] == task_id
        assert before["task_step_history"][0]["mode_id"] == mode.id
        # Document the current deployment blocker, not acceptance of this upgrade.
        with pytest.raises(ValueError) as failure:
            with initialization_transaction(engine) as connection:
                ensure_migrated(connection)
        assert str(failure.value) == (
            "Managed phase 'single-task-v1:project_manager'/'draft'/'PM-DRAFT-01' "
            "has different instructions/checks/evidence"
        )
        assert any(
            frame.name == "upgrade" and frame.filename.endswith("0024_analyst_research_catalog.py")
            for frame in extract_tb(failure.value.__traceback__)
        )
        assert database_revisions(engine) == {PREDECESSOR}
        assert snapshot() == before
        with SAUnitOfWork(engine) as uow:
            catalog._observe_profile(uow, *predecessor)
            assert editor.read_active(uow, workflow_id)["catalog_version"] == 13
            assert editor.read_operation(uow, workflow_id, "published-pm-13") == published
    finally:
        engine.dispose()
