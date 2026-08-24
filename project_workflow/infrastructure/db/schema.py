"""Phase catalog loading and empty-database bootstrap.

Все данные — только из БД (phases, instructions, checks, evidence).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_workflow.domain.repositories import UnitOfWork

from ... import config
from ...supervisor.models import (
    Phase,
    PhaseCheck,
    PhaseDelegate,
    PhaseEvidence,
    PhaseInstruction,
)

# ── DB Load ─────────────────────────────────────────────────────


def _build_phase_from_db(
    phase_row: Any,
    uow: UnitOfWork,
) -> Phase:
    """Assemble a supervisor Phase dataclass from a domain Phase + repositories."""
    phase_id = phase_row.id
    phase_code = phase_row.code or ""
    inst_rows = uow.instructions.list(phase_id)

    instructions = [
        PhaseInstruction(
            step=ir["description"],
            example=ir.get("example"),
            execution_type=ir.get("execution_type", "sync"),
            skills=ir.get("skills") or [],
        )
        for ir in inst_rows
    ]

    check_rows = uow.phases.get_checks(phase_id)
    checks = [
        PhaseCheck(
            description=cr["description"],
            id=cr.get("id"),
        )
        for cr in check_rows
    ]

    ev_rows = uow.phases.get_evidence(phase_id)
    evidence = [
        PhaseEvidence(
            item=er["description"],
            id=er.get("id"),
        )
        for er in ev_rows
    ]

    delegate = None
    if phase_row.agent_id:
        agent = uow.agents.get_by_id(phase_row.agent_id)
        if agent:
            delegate = PhaseDelegate(
                agent=agent.name,
                hermes_profile=agent.hermes_profile,
                prompt_template=f"Phase {phase_code}",
                toolsets=[],  # domain Agent does not store toolsets in this schema
                timeout_min=10,
                max_cycles=3,
            )

    return Phase(
        id=phase_id,
        code=phase_code,
        name=phase_row.name,
        description=phase_row.description or "",
        min_time_min=phase_row.min_time_min or 0,
        is_blocker=phase_row.is_blocker,
        is_delegated=phase_row.is_delegated,
        is_critic=phase_row.is_critic,
        checks=checks,
        evidence=evidence,
        instructions=instructions,
        delegate=delegate,
        next_recommendation=phase_row.next_recommendation or "",
        parallel_with=phase_row.parallel_with,
        rollback_target=phase_row.rollback_target,
        execution_type=phase_row.execution_type or "sync",
    )


def load_phases_from_db(
    uow: UnitOfWork,
    workflow_id: int | str | None = None,
) -> list[Phase]:
    """Load all supervisor phases from a UnitOfWork instance."""
    if isinstance(workflow_id, str):
        workflow_id = int(workflow_id) if workflow_id.isdigit() else None
    rows = uow.phases.list(workflow_id)
    return [_build_phase_from_db(r, uow) for r in rows]


def get_phase_from_db(
    uow: UnitOfWork,
    phase_code: str,
    workflow_id: int,
) -> Phase | None:
    """Find a phase by its workflow-scoped code."""
    row = uow.phases.get_by_code(workflow_id, phase_code)
    return _build_phase_from_db(row, uow) if row else None


# ── Bootstrap seed ───────────


def _load_seed(path: Path | str | None = None) -> list[dict[str, Any]]:
    seed_path = Path(path) if path else config.SEED_PATH
    if not seed_path.exists():
        raise FileNotFoundError(f"Seed catalog not found: {seed_path}")
    if seed_path.suffix.lower() != ".json":
        raise ValueError("Seed catalog must be JSON")
    with seed_path.open(encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed seed catalog: {seed_path}") from exc
    if not isinstance(data, list):
        raise ValueError("Seed catalog root must be a list")
    if not all(isinstance(item, dict) for item in data):
        raise ValueError("Every seed catalog item must be an object")
    return data


def _phase_item_to_supervisor(item: dict[str, Any]) -> Phase:
    """Convert a raw seed dict into a supervisor Phase dataclass."""

    def _text(val: Any) -> str:
        if isinstance(val, dict):
            return str(val.get("description", val.get("item", val.get("step", "")))).strip()
        return str(val).strip()

    instructions = [
        PhaseInstruction(
            step=_text(ir),
            example=ir.get("example") if isinstance(ir, dict) else None,
            execution_type=ir.get("execution_type", "sync") if isinstance(ir, dict) else "sync",
            skills=ir.get("skills", []) if isinstance(ir, dict) else [],
        )
        for ir in item.get("instructions", [])
        if _text(ir)
    ]
    checks = [PhaseCheck(description=_text(cr)) for cr in item.get("checks", []) if _text(cr)]
    evidence = [PhaseEvidence(item=_text(er)) for er in item.get("evidence", []) if _text(er)]

    delegate: PhaseDelegate | None = None
    if item.get("delegate"):
        d = item["delegate"]
        delegate = PhaseDelegate(
            agent=d.get("agent", ""),
            hermes_profile=d.get("hermes_profile") or None,
            prompt_template=d.get("prompt_template", f"Phase {item.get('code', '')}"),
            toolsets=d.get("toolsets", []),
            timeout_min=d.get("timeout_min", 10),
            max_cycles=d.get("max_cycles", 3),
        )
    return Phase(
        id=None,
        code=item.get("code", ""),
        name=item.get("name", ""),
        description=item.get("description", ""),
        min_time_min=item.get("min_time_min", 0),
        is_blocker=bool(item.get("is_blocker", False)),
        is_delegated=bool(delegate),
        is_critic=bool(item.get("is_critic", False)),
        checks=checks,
        evidence=evidence,
        instructions=instructions,
        delegate=delegate,
        next_recommendation=str(item.get("next_recommendation", "")),
        parallel_with=str(item.get("parallel_with")) if item.get("parallel_with") else None,
        rollback_target=str(item.get("rollback_target")) if item.get("rollback_target") else None,
        execution_type=str(item.get("execution_type", "sync")),
    )


def load_phases_from_seed(
    path: Path | str | None = None,
) -> list[Phase]:
    """Load phases from the packaged JSON seed for initial bootstrap."""
    items = _load_seed(path)
    return [_phase_item_to_supervisor(item) for item in items]


# ── Catalog bootstrap ─────────────────────────────────────────────


def ensure_phase_catalog(
    uow: UnitOfWork,
    seed_path: Path | str | None = None,
) -> None:
    """Bootstrap the packaged phase catalog only for a new empty database."""
    if uow.workflows.list():
        return
    default_workflow = uow.workflows.ensure_default_exists(config.DEFAULT_WORKFLOW_NAME)
    workflow_id = default_workflow.id
    assert workflow_id is not None

    seed_path = Path(seed_path) if seed_path else config.SEED_PATH
    seed_phases = load_phases_from_seed(seed_path)
    for phase in seed_phases:
        delegate = phase.delegate
        agent_name = (delegate.agent or "") if delegate else ""
        if agent_name and not uow.agents.get_by_name(agent_name):
            uow.agents.create(
                {
                    "name": agent_name,
                    "description": f"Seed agent for {agent_name}",
                    "hermes_profile": delegate.hermes_profile if delegate else None,
                }
            )

    for order, phase in enumerate(seed_phases, start=1):
        assigned_agent_name = phase.delegate.agent if phase.delegate else ""
        agent_id = None
        if assigned_agent_name:
            agent_id = next(
                (agent.id for agent in uow.agents.list() if agent.name == assigned_agent_name),
                None,
            )
        phase_id = uow.phases.create(
            {
                "workflow_id": workflow_id,
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
                "is_blocker": phase.is_blocker,
                "is_delegated": phase.is_delegated,
                "is_critic": phase.is_critic,
                "agent_id": agent_id,
            }
        )
        for idx, instr in enumerate(phase.instructions, start=1):
            uow.instructions.create(
                int(phase_id),
                {
                    "step_num": idx,
                    "description": instr.step,
                    "execution_type": instr.execution_type,
                    "skills": instr.skills,
                },
            )
        uow.phases.set_checks(
            int(phase_id),
            [{"description": check.description} for check in phase.checks],
        )
        uow.phases.set_evidence(
            int(phase_id),
            [{"description": item.item} for item in phase.evidence],
        )
