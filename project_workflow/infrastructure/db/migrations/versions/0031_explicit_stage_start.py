"""Append the coordinated Start/Completed defaults without rebinding saved work."""

from alembic import op
from sqlalchemy import select

from project_workflow.application.catalog_publication import (
    _normalize,
    publish_baseline,
    read_revision,
    sealed_baseline,
)
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import _observe_profile, load_profile
from project_workflow.infrastructure.db.uow import SAUnitOfWork

revision = "0031_explicit_stage_start"
down_revision = "0030_analyst_baseline_ledger"
branch_labels = None
depends_on = None
PREVIOUS = "2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64"
TARGET = "852e0647ad8645c9c6280b21c1595b9efa6ff87754d07df8dcc92bcb04f76381"


def upgrade() -> None:
    uow = SAUnitOfWork(op.get_bind())
    try:
        uow.lock_catalog_state()
        if not any(w.key and w.key.startswith("single-task-v1:") for w in uow.workflows.list()):
            return
        target = load_profile(TARGET)
        try:
            _observe_profile(uow, *target)
            return
        except ValueError:
            pass
        # The catalog lock and exact source/publication readback are the CAS.
        installed = _observe_profile(uow, *load_profile(PREVIOUS))
        target_modes = {definition["key"]: _normalize(definition["modes"]) for definition in target[0]["workflows"]}
        workflows = [uow.workflows.get_by_id(int(binding.workflow_id)) for binding in installed.bindings]
        for workflow in workflows:
            _, version = sealed_baseline(uow, workflow)
            if (workflow.active_catalog_version != version
                    and read_revision(uow, workflow, workflow.active_catalog_version, selected=True)["modes"]
                    != target_modes[workflow.key]):
                raise ValueError(
                    "Explicit Start cutover publication required for active operator catalog "
                    "(publish the exact canonical target through the catalog API): "
                    f"{workflow.key}; no defaults were changed"
                )
        for workflow in workflows:
            publish_baseline(uow, workflow, TARGET)
        uow.session.flush()
        _observe_profile(uow, *target)
    finally:
        uow.close()


def downgrade() -> None:
    if op.get_bind().execute(
        select(m.Workflow.id).where(m.Workflow.key.startswith("single-task-v1:")).limit(1)
    ).first():
        raise RuntimeError("Configured catalog is forward-only")
