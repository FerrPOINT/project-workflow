"""Refresh sealed phase instructions, retaining task IDs, phase IDs and reports."""

from alembic import op
from sqlalchemy import select

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import ManagedMode
from project_workflow.infrastructure.db.schema import _phase_item_to_supervisor
from project_workflow.infrastructure.db.single_task_catalog import _observe_profile, load_profile
from project_workflow.infrastructure.db.uow import SAUnitOfWork

revision = "0020_configured_cli_catalog"
down_revision = "0019_pm_terminal_resume_retry"
branch_labels = None
depends_on = None
TARGET = "e0cde0c044fe1a38b6fa0f387cc30e0da6e89dedb35b89a893263fd7d2558a40"
PREVIOUS = (
    "1535516545520eb5ea489cf1583cfaebc458e5729a94762751515841078671c3",
    "652a38c0f7bdb48a569aa3fcd5c2e81e153db6e22b5201cfb6ce15c988dd57f3",
    "19d3228270bc76959f91a06f3b946a39b4509b14a2c29b62acc8762dd5cc3fe2",
)


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
                _observe_profile(uow, *load_profile(digest))
                break
            except ValueError:
                continue
        else:
            raise ValueError("Cannot replace a partial or customized single-task catalog")
        for definition in target["workflows"]:
            workflow = next((w for w in uow.workflows.list() if w.key == definition["key"]), None)
            assert workflow is not None
            modes = {mode.key: mode for mode in uow.workflows.list_modes(workflow.id)}
            for source_mode in definition["modes"]:
                mode = modes[source_mode["key"]]
                phases = {p.code: p for p in uow.phases.list(workflow_id=workflow.id, mode_id=mode.id)}
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
    raise RuntimeError("Configured phase history is forward-only")
