"""Analyst reads pinned sources without building a delivery workspace."""

from alembic import op
from sqlalchemy import select

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import ManagedMode
from project_workflow.infrastructure.db.schema import _phase_item_to_supervisor
from project_workflow.infrastructure.db.single_task_catalog import _observe_profile, load_profile
from project_workflow.infrastructure.db.uow import SAUnitOfWork

revision = "0028_analyst_read_sources"
down_revision = "0027_analyst_no_pm_return"
branch_labels = None
depends_on = None
TARGET = "62762bf58f337d9e063226aef58ea6c89cdfb2e87159056f1a6b2b6c4d1ddf3a"
PREVIOUS = "9384121a0c1bc9c869a25fcdf11cab4064a0491ebcf329a6310229874ab835d0"


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
        for mode, source_mode in zip(binding.modes, definition["modes"], strict=True):
            for phase_id, phase in zip(mode.phase_ids, ManagedMode.model_validate(source_mode).phases, strict=True):
                rows = uow.phase_instructions.list(int(phase_id))
                instructions = _phase_item_to_supervisor(phase).instructions
                for row, instruction in zip(rows, instructions, strict=True):
                    uow.phase_instructions.update(
                        row["id"], {"description": instruction.step, "skills": instruction.skills}
                    )
        uow.session.flush()
        _observe_profile(uow, target, manifest)
    finally:
        uow.close()


def downgrade() -> None:
    if op.get_bind().execute(
        select(m.Workflow.id).where(m.Workflow.key.like("single-task-v1:%")).limit(1)
    ).first():
        raise RuntimeError("Configured catalog is forward-only")
