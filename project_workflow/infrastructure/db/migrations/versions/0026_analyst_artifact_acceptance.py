"""Keep final Analyst evidence before the guarded Tracker handoff."""

from alembic import op
from sqlalchemy import select

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import _observe_profile, load_profile
from project_workflow.infrastructure.db.uow import SAUnitOfWork

revision = "0026_analyst_artifact_acceptance"
down_revision = "0025_pm_analysis_acceptance"
branch_labels = None
depends_on = None
TARGET = "ab182b9bc6f7182c6250ba20cc322749f6fbae28ddc183765fbd888a658900e6"
PREVIOUS = "d76ecbb632b1ceebf33bf78e8e0dedaec278538227d653aa9fd3c998e19ea694"


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
        definition = next(w for w in target["workflows"] if w["role_key"] == "analyst")
        phase_id = int(binding.modes[0].phase_ids[-1])
        rows = list(uow.session.scalars(select(m.PhaseEvidenceRequirement)
            .where(m.PhaseEvidenceRequirement.phase_id == phase_id).order_by(m.PhaseEvidenceRequirement.id)))
        # The artifact exists before evaluation. Tracker still requires the later
        # final comment and accepted Workflow receipt before it can hand off.
        rows[-1].description = definition["modes"][0]["phases"][-1]["evidence"][-1]
        uow.session.flush()
        _observe_profile(uow, target, manifest)
    finally:
        uow.close()


def downgrade() -> None:
    if op.get_bind().execute(
        select(m.Workflow.id).where(m.Workflow.key.like("single-task-v1:%")).limit(1)
    ).first():
        raise RuntimeError("Configured catalog is forward-only")
