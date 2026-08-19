"""Bootstrap helpers for SAUnitOfWork."""

from __future__ import annotations

from typing import TYPE_CHECKING

from project_workflow.infrastructure.db import schema

if TYPE_CHECKING:
    from .uow import SAUnitOfWork


def bootstrap_smoke_project_and_workflow(uow: SAUnitOfWork) -> None:
    from project_workflow import config

    smoke_wf = uow.workflows.get_by_name(config.SMOKE_WORKFLOW_NAME)
    if smoke_wf:
        smoke_wf_id = smoke_wf.id
    else:
        smoke_wf_id = uow.workflows.create(
            {
                "name": config.SMOKE_WORKFLOW_NAME,
                "description": "Smoke test workflow",
                "_skip_default_phase": True,
            }
        )
    smoke_project = uow.projects.get_by_code(config.SMOKE_PROJECT_CODE)
    if smoke_project is None:
        uow.projects.create(
            {
                "workflow_id": smoke_wf_id,
                "code": config.SMOKE_PROJECT_CODE,
                "name": config.SMOKE_PROJECT_NAME,
                "key_prefixes": list(config.SMOKE_TASK_KEY_PREFIXES),
                "workflow_name": config.SMOKE_WORKFLOW_NAME,
            }
        )
        uow.commit()
    ensure_smoke_phases(uow)


def ensure_smoke_phases(uow: SAUnitOfWork) -> None:
    from project_workflow import config

    smoke_wf = uow.workflows.get_by_name(config.SMOKE_WORKFLOW_NAME)
    if not smoke_wf:
        return
    if uow.phases.list(workflow_id=smoke_wf.id):
        return
    seed_phases = schema.load_phases_from_seed(config.SMOKE_SEED_PATH)
    # Ensure agents referenced by selected_agent exist first.
    for phase in seed_phases:
        agent_name = phase.delegate.agent if phase.delegate else ""
        if agent_name and not uow.agents.get_by_name(agent_name):
            uow.agents.create({"name": agent_name, "description": f"Smoke seed agent for {phase.code}"})
    uow.commit()

    for order, phase in enumerate(seed_phases, start=1):
        data = {
            "workflow_id": smoke_wf.id,
            "code": phase.code,
            "name": phase.name,
            "description": phase.description,
            "min_time_min": phase.min_time_min,
            "phase_order": order,
            "next_recommendation": phase.next_recommendation,
            "parallel_with": phase.parallel_with,
            "rollback_target": phase.rollback_target,
            "execution_type": phase.execution_type,
            "is_seed_managed": True,
        }
        if phase.delegate:
            agent = uow.agents.get_by_name(phase.delegate.agent)
            if agent:
                data["agent_id"] = agent.id
        phase_id = uow.phases.create(data)

        assert phase_id is not None
        # Populate content for this newly created catalog phase.
        uow.instructions.delete_for_phase(int(phase_id))
        for idx, instr in enumerate(phase.instructions, start=1):
            uow.instructions.create(
                int(phase_id),
                {
                    "step_num": idx,
                    "description": instr.step,
                    "example": instr.example,
                    "execution_type": instr.execution_type,
                    "skills": instr.skills,
                },
            )
        uow.phases.set_checks(
            int(phase_id),
            [{"description": c.description} for c in phase.checks],
        )
        uow.phases.set_evidence(
            int(phase_id),
            [{"description": e.item} for e in phase.evidence],
        )
    uow.commit()


def bootstrap_default_project(uow: SAUnitOfWork) -> None:
    from project_workflow import config

    code = "TASK"
    if uow.projects.get_by_code(code) is None:
        default_wf = uow.workflows.ensure_default_exists()
        uow.projects.create(
            {
                "workflow_id": default_wf.id,
                "code": code,
                "name": "Default Project",
                "key_prefixes": list(config.DEFAULT_TASK_KEY_PREFIXES),
            }
        )
        uow.commit()
