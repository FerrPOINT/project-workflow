"""Fixtures for catalog producers from before baseline receipts existed."""

from contextlib import contextmanager
from unittest.mock import patch

from project_workflow.application import catalog_publication as editor
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.managed_catalog import ManagedMode, _persist_mode


@contextmanager
def historical_publication_writer():
    """Seed accepted native-era editions before exercising the current read/migration contract."""
    with patch.object(editor, "_editable_baseline", lambda uow, workflow: editor.sealed_baseline(uow, workflow)[0]):
        yield


@contextmanager
def historical_catalog(digest):
    load = catalog.load_profile
    profile = load(digest)

    def seed_baseline(uow, workflow, manifest):
        assert manifest == digest
        definition = editor._definition(workflow.key, manifest)
        for mode in definition["modes"]:
            _persist_mode(uow, workflow_id=workflow.id, role_key=definition["role_key"],
                          mode=ManagedMode.model_validate(mode), catalog_version=1)

    with (
        patch.object(catalog, "load_profile", lambda manifest=digest: load(manifest)),
        patch.object(catalog, "observe_installation", lambda uow: catalog._observe_profile(uow, *profile)),
        patch.object(editor, "publish_baseline", seed_baseline),
        historical_publication_writer(),
    ):
        yield
