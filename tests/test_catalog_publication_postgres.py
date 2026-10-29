"""Synthetic PostgreSQL publication gates; authorities remain explicit test peers."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from project_workflow.domain.single_task_profile import ROLE_MODES
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests import test_catalog_publication as publication
from tests.test_catalog_publication import verified_catalog_administrator as verified_catalog_administrator
from tests.test_configured_postgres import configured as configured
from tests.test_configured_postgres import pg_url as pg_url

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("configured", [(role, mode) for role, modes in ROLE_MODES.items() for mode in modes],
                         indirect=True)
def test_publication_adopts_new_snapshot_without_rewriting_active_execution(configured):
    publication.test_saved_draft_is_not_activation_and_publication_only_changes_new_executions(configured)


@pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
def test_published_revisions_preserve_completed_history_and_terminal_replay(configured, supervisor_llm):
    publication.test_completed_history_and_active_phase_survive_multiple_publications(configured, supervisor_llm)


def test_unfinished_recovery_keeps_its_instruction_revision(configured):
    publication.test_unfinished_assignment_recovery_keeps_its_snapshot_after_publication(configured)


def test_original_publication_replay_after_newer_revision_keeps_pointer_and_receipt(configured):
    publication.test_republish_after_newer_publication_returns_original_without_pointer_rollback(configured)


def test_startup_keeps_published_revision_and_old_execution_snapshot(configured):
    publication.test_startup_restart_keeps_v2_and_old_assigned_execution(configured)


def test_pending_draft_readback_and_dedup_retain_saved_content(configured):
    publication.test_draft_reload_readback_and_save_dedup_do_not_activate_or_append_duplicates(configured)


def test_concurrent_identical_saves_reuse_one_unpublished_version(configured):
    client, _ = configured
    base = publication.active(client, publication.enroll(configured)["workflow_id"])
    barrier = Barrier(2)
    command = {"expected_version": 1, "expected_sha256": base["content_sha256"], "modes": base["modes"]}

    def save(_index):
        barrier.wait(timeout=15)
        return client.post(f"/api/workflows/{base['workflow_id']}/catalog/drafts", json=command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(save, (0, 1)))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    with SAUnitOfWork() as uow:
        assert sorted(uow.session.scalars(select(m.WorkflowMode.catalog_version).where(
            m.WorkflowMode.workflow_id == base["workflow_id"]))) == [1, 2]
        assert uow.session.scalar(select(func.count()).select_from(m.WorkflowCatalogPublication)) == 0


@pytest.mark.parametrize("same_operation", [False, True])
def test_publication_catalog_lock_serializes_cas_and_exact_replay(configured, same_operation):
    client, _ = configured
    base = publication.active(client, publication.enroll(configured)["workflow_id"])
    drafts = [publication.draft(client, base)[0],
              publication.draft(client, base, text="Second distinct concurrent draft.")[0]]
    barrier = Barrier(2)

    def publish(index):
        barrier.wait(timeout=15)
        return publication.publication(client, base, drafts[0 if same_operation else index])

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(publish, (0, 1)))
    assert sorted(response.status_code for response in responses) == ([200, 200] if same_operation else [200, 409])
    if same_operation:
        assert responses[0].json() == responses[1].json()
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.WorkflowCatalogPublication)) == 1
