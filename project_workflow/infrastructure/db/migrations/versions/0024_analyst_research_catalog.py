"""Refresh sealed phase instructions, retaining task IDs, phase IDs and reports."""

from alembic import op
from sqlalchemy import select

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import ManagedMode
from project_workflow.infrastructure.db.schema import _phase_item_to_supervisor
from project_workflow.infrastructure.db.single_task_catalog import _observe_profile, load_profile
from project_workflow.infrastructure.db.uow import SAUnitOfWork

revision = "0024_analyst_research_catalog"
down_revision = "0023_catalog_publication_author"
branch_labels = None
depends_on = None
TARGET = "332cfd4fb3419d5765008e196cffb508540462ddd89b798ab4e89379ac5b1796"
PREVIOUS = ("e0cde0c044fe1a38b6fa0f387cc30e0da6e89dedb35b89a893263fd7d2558a40",)


def upgrade() -> None:
    uow = SAUnitOfWork(op.get_bind())
    try:
        if not any(w.key and w.key.startswith("single-task-v1:") for w in uow.workflows.list()):
            return  # A fresh database receives the current catalog through its normal seed.
        uow.lock_catalog_state()
        target, manifest = load_profile(TARGET)
        try:
            _observe_profile(uow, target, manifest)
            return
        except ValueError:
            pass
        for digest in PREVIOUS:
            try:
                installed = _observe_profile(uow, *load_profile(digest))
                break
            except ValueError:
                continue
        else:
            raise ValueError("Cannot replace a partial or customized single-task catalog")
        for definition in target["workflows"]:
            binding = next(b for b in installed.bindings if b.workflow_key == definition["key"])
            modes = {mode.key: mode for mode in binding.modes}
            for source_mode in definition["modes"]:
                mode = modes[source_mode["key"]]
                phases = {
                    p.code: p for p in uow.phases.list(
                        workflow_id=int(binding.workflow_id), mode_id=int(mode.mode_id),
                    )
                }
                for phase_model in ManagedMode.model_validate(source_mode).phases:
                    canonical = _phase_item_to_supervisor(phase_model)
                    source_phase = {
                        "code": canonical.code,
                        "name": canonical.name,
                        "description": canonical.description,
                        "instructions": [{"description": i.step, "skills": i.skills} for i in canonical.instructions],
                        "checks": [c.description for c in canonical.checks],
                        "evidence": [e.item for e in canonical.evidence],
                    }
                    phase = phases[source_phase["code"]]
                    uow.phases.update(phase.id, {k: source_phase[k] for k in ("name", "description")})
                    instructions = list(uow.phase_instructions.list(phase.id))
                    for index, item in enumerate(source_phase["instructions"]):
                        data = {"description": item["description"], "skills": item["skills"], "execution_type": "sync"}
                        if index < len(instructions):
                            uow.phase_instructions.update(instructions[index]["id"], data)
                        else:
                            uow.phase_instructions.create(phase.id, {**data, "step_num": index + 1})
                    for item in instructions[len(source_phase["instructions"]) :]:
                        uow.phase_instructions.delete(item["id"])
                    for model, values in (
                        (m.PhaseCheck, source_phase["checks"]),
                        (m.PhaseEvidenceRequirement, source_phase["evidence"]),
                    ):
                        rows = list(
                            uow.session.scalars(select(model).where(model.phase_id == phase.id).order_by(model.id))
                        )
                        for index, description in enumerate(values):
                            if index < len(rows):
                                rows[index].description = description
                            else:
                                uow.session.add(model(phase_id=phase.id, description=description))
                        for row in rows[len(values) :]:
                            uow.session.delete(row)
                    uow.session.flush()
        _observe_profile(uow, target, manifest)
        uow.session.flush()
    finally:
        uow.close()


def downgrade() -> None:
    # An unseeded schema has no instruction state to restore. Materialized catalogs
    # remain forward-only so a rollback cannot rewrite active or historical rules.
    installed = op.get_bind().execute(
        select(m.Workflow.id).where(m.Workflow.key.like("single-task-v1:%")).limit(1)
    ).first()
    if installed:
        raise RuntimeError("Configured catalog is forward-only")
