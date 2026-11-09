"""Append the current source family without reinterpreting saved executions."""

from alembic import op
from sqlalchemy import select

from project_workflow.application.catalog_publication import (
    BASELINE_OPERATION,
    _normalize,
    publish_baseline,
    read_revision,
    sealed_baseline,
)
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import (
    _observe_profile,
    load_profile,
    observe_installation,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork

revision = "0032_current_source_baseline"
down_revision = "0031_explicit_stage_start"
branch_labels = None
depends_on = None
PREVIOUS = "852e0647ad8645c9c6280b21c1595b9efa6ff87754d07df8dcc92bcb04f76381"
TARGET = "d035a0ddb06436714b76e40bc8cb68084203011f53dd52436732367690940e85"


def upgrade() -> None:
    uow = SAUnitOfWork(op.get_bind())
    try:
        uow.lock_catalog_state()
        if not any(w.key and w.key.startswith("single-task-v1:") for w in uow.workflows.list()):
            return
        installed = observe_installation(uow)
        family = installed.instruction_manifest_sha256
        if family not in (PREVIOUS, TARGET):
            raise ValueError("Current source cutover requires the exact sealed 852 predecessor")
        workflows = []
        for binding in installed.bindings:
            workflow = uow.workflows.get_by_id(int(binding.workflow_id))
            _, version = sealed_baseline(uow, workflow)
            operation = uow.session.scalar(select(m.WorkflowCatalogPublication.operation_key).where(
                m.WorkflowCatalogPublication.workflow_id == workflow.id,
                m.WorkflowCatalogPublication.catalog_version == version,
            ))
            if operation != f"{BASELINE_OPERATION}{workflow.id}:{family}":
                raise ValueError("Current source cutover requires one exact sealed receipt family")
            workflows.append((workflow, version))
        if family == TARGET:
            return
        target = load_profile(TARGET)
        target_modes = {definition["key"]: _normalize(definition["modes"]) for definition in target[0]["workflows"]}
        for workflow, version in workflows:
            if (workflow.active_catalog_version != version
                    and read_revision(uow, workflow, workflow.active_catalog_version, selected=True)["modes"]
                    != target_modes[workflow.key]):
                raise ValueError(
                    "Explicit current source cutover publication required for active operator catalog "
                    "(publish the exact canonical target through the catalog API before upgrade): "
                    f"{workflow.key}; no defaults were changed"
                )
        for workflow, _ in workflows:
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
