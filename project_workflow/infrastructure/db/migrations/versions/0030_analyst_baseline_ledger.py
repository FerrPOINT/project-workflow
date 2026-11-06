"""Seal source revisions in the existing ledger, preserving operator publications."""

from alembic import op
from sqlalchemy import select

from project_workflow.application.catalog_publication import publish_baseline, sealed_baseline
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import _observe_profile, load_profile
from project_workflow.infrastructure.db.uow import SAUnitOfWork

revision = "0030_analyst_baseline_ledger"
down_revision = "0029_analyst_twelve_phases"
branch_labels = None
depends_on = None
PREVIOUS = "7aa0e6c758e2c31cd1dd69ce30826aecaf565e25e4f5fcedcdf9215fcddd1075"
TARGET = "2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64"


def upgrade() -> None:
    uow = SAUnitOfWork(op.get_bind())
    try:
        workflow = next((w for w in uow.workflows.list() if w.key == "single-task-v1:analyst"), None)
        if workflow is None:
            return
        uow.lock_catalog_state()
        target, manifest = load_profile(TARGET)
        try:
            _observe_profile(uow, target, manifest)
            return
        except ValueError:
            pass
        # Published 0029 installed revision2 before source provenance had a receipt.
        # Validate and seal those exact rows; never infer a replacement from drift.
        if sealed_baseline(uow, workflow)[1] == 1:
            publish_baseline(uow, workflow, PREVIOUS, existing_version=2)
        _observe_profile(uow, *load_profile(PREVIOUS))
        publish_baseline(uow, workflow, TARGET)
        uow.session.flush()
        _observe_profile(uow, target, manifest)
    finally:
        uow.close()


def downgrade() -> None:
    if op.get_bind().execute(select(m.Workflow.id).where(m.Workflow.key == "single-task-v1:analyst")).first():
        raise RuntimeError("Configured catalog is forward-only")
