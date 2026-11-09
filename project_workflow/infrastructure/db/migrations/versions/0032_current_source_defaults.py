"""Append approved source defaults without overwriting selected operator content."""

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

revision = "0032_current_source_defaults"
down_revision = "0031_explicit_stage_start"
branch_labels = None
depends_on = None
PREVIOUS = "852e0647ad8645c9c6280b21c1595b9efa6ff87754d07df8dcc92bcb04f76381"
TARGET = "920379c0c86455148e6fae35e2007037595c2d1cc82116c392c575c4625ffd28"


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
        installed = _observe_profile(uow, *load_profile(PREVIOUS))
        definitions = {item["key"]: _normalize(item["modes"]) for item in target[0]["workflows"]}
        changed = []
        for binding in installed.bindings:
            workflow = uow.workflows.get_by_id(int(binding.workflow_id))
            baseline, version = sealed_baseline(uow, workflow)
            if _normalize(baseline["modes"]) == definitions[workflow.key]:
                continue
            selected = read_revision(uow, workflow, workflow.active_catalog_version, selected=True)
            if (workflow.active_catalog_version != version
                    and selected["modes"] != definitions[workflow.key]):
                raise ValueError(
                    "Current source-default cutover publication required for active operator catalog: "
                    f"{workflow.key}; no defaults were changed"
                )
            changed.append(workflow)
        # Check every selected revision before appending any source rows. Retained
        # drafts, accepted reports and unrelated operator publications stay intact.
        for workflow in changed:
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
