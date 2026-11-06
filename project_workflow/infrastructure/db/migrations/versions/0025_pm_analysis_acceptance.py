"""Align the final PM condition with automatic analysis, preserving past proofs."""

from alembic import op
from sqlalchemy import select

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import _observe_profile, load_profile
from project_workflow.infrastructure.db.uow import SAUnitOfWork

revision = "0025_pm_analysis_acceptance"
down_revision = "0024_analyst_research_catalog"
branch_labels = None
depends_on = None
TARGET = "d76ecbb632b1ceebf33bf78e8e0dedaec278538227d653aa9fd3c998e19ea694"
PREVIOUS = "332cfd4fb3419d5765008e196cffb508540462ddd89b798ab4e89379ac5b1796"


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
        binding = next(b for b in installed.bindings if b.role_key == "project_manager")
        definition = next(w for w in target["workflows"] if w["role_key"] == "project_manager")
        phase_id = int(binding.modes[0].phase_ids[-1])
        checks = list(uow.session.scalars(
            select(m.PhaseCheck).where(m.PhaseCheck.phase_id == phase_id).order_by(m.PhaseCheck.id)
        ))
        # Update only the present-tense acceptance condition. Historical reports,
        # frozen evaluations and publication receipts keep their original contract.
        checks[-1].description = definition["modes"][0]["phases"][-1]["checks"][-1]
        uow.session.flush()
        _observe_profile(uow, target, manifest)
    finally:
        uow.close()


def downgrade() -> None:
    if op.get_bind().execute(
        select(m.Workflow.id).where(m.Workflow.key.like("single-task-v1:%")).limit(1)
    ).first():
        raise RuntimeError("Configured catalog is forward-only")
