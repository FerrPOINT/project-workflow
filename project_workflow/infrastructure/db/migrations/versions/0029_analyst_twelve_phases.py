"""Select the twelve-phase Analyst baseline without rewriting enrolled work."""

from alembic import op
from sqlalchemy import select

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import ManagedMode, _persist_mode
from project_workflow.infrastructure.db.single_task_catalog import _observe_profile, load_profile
from project_workflow.infrastructure.db.uow import SAUnitOfWork

revision = "0029_analyst_twelve_phases"
down_revision = "0028_analyst_read_sources"
branch_labels = None
depends_on = None
PREVIOUS = "62762bf58f337d9e063226aef58ea6c89cdfb2e87159056f1a6b2b6c4d1ddf3a"
TARGET = "7aa0e6c758e2c31cd1dd69ce30826aecaf565e25e4f5fcedcdf9215fcddd1075"


def upgrade() -> None:
    uow = SAUnitOfWork(op.get_bind())
    try:
        if not any(w.key and w.key.startswith("single-task-v1:") for w in uow.workflows.list()):
            return
        uow.lock_catalog_state()
        target, manifest = load_profile(TARGET)
        try:
            _observe_profile(uow, target, manifest)
            return
        except ValueError:
            pass
        try:
            installed = _observe_profile(uow, *load_profile(PREVIOUS))
        except ValueError:
            raise ValueError("Cannot replace a partial or customized single-task catalog") from None
        binding = next(b for b in installed.bindings if b.role_key == "analyst")
        workflow_id = int(binding.workflow_id)
        versions = uow.session.scalars(select(m.WorkflowMode.catalog_version).where(
            m.WorkflowMode.workflow_id == workflow_id)).all()
        if any(version != 1 for version in versions):
            raise ValueError("Cannot replace customized Analyst publications or drafts")
        definition = next(w for w in target["workflows"] if w["role_key"] == "analyst")
        baseline_version = definition["baseline_catalog_version"]
        for mode in definition["modes"]:
            _persist_mode(uow, workflow_id=workflow_id, role_key="analyst",
                          mode=ManagedMode.model_validate(mode), catalog_version=baseline_version)
        uow.workflows.update(workflow_id, {"active_catalog_version": baseline_version})
        uow.session.flush()
        _observe_profile(uow, target, manifest)
    finally:
        uow.close()


def downgrade() -> None:
    if op.get_bind().execute(
        select(m.Workflow.id).where(m.Workflow.key == "single-task-v1:analyst").limit(1)
    ).first():
        raise RuntimeError("Configured catalog is forward-only")
