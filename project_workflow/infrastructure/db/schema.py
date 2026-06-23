"""Schema loader — reads Phase models from SQLite DB with YAML fallback.

Все данные — только из БД (phases, instructions, checks, evidence).
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

import yaml

from project_workflow.domain.repositories import UnitOfWork
from ... import config
from ...wizard.models import (
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
    """Assemble a wizard Phase dataclass from a domain Phase + repositories."""
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
        )
        for cr in check_rows
    ]

    ev_rows = uow.phases.get_evidence(phase_id)
    evidence = [
        PhaseEvidence(
            item=er["description"],
        )
        for er in ev_rows
    ]

    delegate = None
    if phase_row.agent_id:
        agent = uow.agents.get_by_id(phase_row.agent_id)
        if agent:
            delegate = PhaseDelegate(
                agent=agent.name,
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
        is_blocker=False,
        is_delegated=bool(delegate),
        is_critic=phase_code in config.CRITIC_PHASES,
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
) -> List[Phase]:
    """Load all wizard phases from a UnitOfWork instance."""
    if isinstance(workflow_id, str):
        workflow_id = int(workflow_id) if workflow_id.isdigit() else None
    rows = uow.phases.list(workflow_id)
    phases = [_build_phase_from_db(r, uow) for r in rows]
    if not phases:
        # Fallback intake phase so the wizard always has a current phase.
        phases = [Phase(
            id=None,
            code="-1",
            name="Task Intake",
            description="Initial task intake before workflow catalog is configured.",
            min_time_min=0,
            is_blocker=False,
            is_delegated=False,
            is_critic=False,
            checks=[],
            evidence=[],
            instructions=[],
            delegate=None,
            next_recommendation="",
            parallel_with=None,
            rollback_target=None,
            execution_type="sync",
        )]
    return phases


def get_phase_from_db(
    uow: UnitOfWork,
    phase_code: str,
    workflow_id: int | str | None = None,
) -> Optional[Phase]:
    """Find a single phase by code using a UnitOfWork."""
    if isinstance(workflow_id, str):
        workflow_id = int(workflow_id) if workflow_id.isdigit() else None
    for r in uow.phases.list(workflow_id):
        if r.code == phase_code:
            return _build_phase_from_db(r, uow)
    return None


def load_phases(workflow_id: int | str | None = None) -> List[Phase]:
    """Load all phases from DB ordered by phase_order."""
    from .uow import SAUnitOfWork
    uow = SAUnitOfWork()
    with uow:
        uow.create_all()
        ensure_phase_catalog(uow)
        return load_phases_from_db(uow, workflow_id=workflow_id)


# ── JSON Seed fallback ───────────


def _load_seed(path: Path | str | None = None) -> list[dict[str, Any]]:
    seed_path = Path(path) if path else config.SEED_PATH
    if not seed_path.exists():
        return []
    with seed_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list):
        return []
    return data


def _phase_item_to_wizard(item: dict[str, Any]) -> Phase:
    """Convert a raw seed dict into a wizard Phase dataclass."""
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
    selected_agent = str(item.get("selected_agent", "")).strip()
    if item.get("delegate"):
        d = item["delegate"]
        delegate = PhaseDelegate(
            agent=d.get("agent", ""),
            prompt_template=d.get("prompt_template", f"Phase {item.get('code', '')}"),
            toolsets=d.get("toolsets", []),
            timeout_min=d.get("timeout_min", 10),
            max_cycles=d.get("max_cycles", 3),
        )
    elif selected_agent:
        delegate = PhaseDelegate(
            agent=selected_agent,
            prompt_template=item.get("delegate_prompt", f"Phase {item.get('code', '')}: {item.get('description', '')}"),
            context=item.get("delegate_context", []),
            toolsets=item.get("delegate_toolsets", []),
            timeout_min=int(item.get("delegate_timeout_min", 10) or 10),
            max_cycles=int(item.get("delegate_max_cycles", 3) or 3),
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
    workflow_id: int | str | None = None,
) -> List[Phase]:
    """Load phases from a YAML/JSON seed file (used for catalog sync)."""
    items = _load_seed(path)
    phases = [_phase_item_to_wizard(item) for item in items]
    if workflow_id is not None:
        # Seed items currently do not carry workflow_id, so this filter is a no-op.
        pass
    return phases


# ── Catalog sync ─────────────────────────────────────────────────


def _phase_to_seed_dict(phase: Phase) -> dict[str, Any]:
    """Convert a wizard Phase back to a seed-friendly dict."""
    result: dict[str, Any] = {
        "code": phase.code,
        "name": phase.name,
        "description": phase.description,
        "min_time_min": phase.min_time_min,
        "is_blocker": phase.is_blocker,
        "is_critic": phase.is_critic,
        "next_recommendation": phase.next_recommendation,
        "parallel_with": phase.parallel_with,
        "rollback_target": phase.rollback_target,
        "execution_type": phase.execution_type,
    }
    if phase.instructions:
        result["instructions"] = [
            {
                "step": inst.step,
                "example": inst.example,
                "execution_type": inst.execution_type,
                "skills": inst.skills,
            }
            for inst in phase.instructions
        ]
    if phase.checks:
        result["checks"] = [{"description": chk.description} for chk in phase.checks]
    if phase.evidence:
        result["evidence"] = [{"description": ev.item} for ev in phase.evidence]
    if phase.delegate:
        result["delegate"] = {
            "agent": phase.delegate.agent,
            "prompt_template": phase.delegate.prompt_template,
            "toolsets": phase.delegate.toolsets,
            "timeout_min": phase.delegate.timeout_min,
            "max_cycles": phase.delegate.max_cycles,
        }
    return result


def ensure_phase_catalog(
    uow: UnitOfWork,
    seed_path: Path | str | None = None,
) -> None:
    """Ensure DB phases match the seed file.

    Uses idempotent upsert: inserts missing phases and reorders existing ones
    to match seed order.  Safe to call repeatedly.
    """
    seed_path = Path(seed_path) if seed_path else config.SEED_PATH
    seed_phases = load_phases_from_seed(seed_path)

    # Create agents referenced by selected_agent from seed.
    for phase in seed_phases:
        delegate = getattr(phase, "delegate", None)
        agent_name = (delegate.agent or "") if delegate else ""
        if agent_name and not uow.agents.get_by_name(agent_name):
            uow.agents.create({"name": agent_name, "description": f"Seed agent for {phase.code}"})

    with uow:
        default_workflow = uow.workflows.ensure_default_exists()
        workflow_id = default_workflow.id
        assert workflow_id is not None

        existing_by_code: dict[str, Any] = {p.code: p for p in uow.phases.list(workflow_id)}

        for order, phase in enumerate(seed_phases, start=1):
            existing = existing_by_code.get(phase.code)
            # Resolve selected agent to an agent_id when seed provides one.
            selected_agent_name = ""
            if getattr(phase, "delegate", None):
                selected_agent_name = (phase.delegate.agent or "") if phase.delegate else ""
            agent_id = None
            if selected_agent_name:
                for agent in uow.agents.list():
                    if agent.name == selected_agent_name:
                        agent_id = agent.id
                        break
            data = {
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
                "agent_id": agent_id,
            }
            if existing:
                uow.phases.update(existing.id, data)
                phase_id = existing.id
            else:
                phase_id = uow.phases.create(data)

            # Sync instructions, checks, evidence from seed
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


def persist_phase_order_to_seed(
    uow: UnitOfWork,
    ordered_phase_codes: list[str],
    seed_path: Path | str | None = None,
) -> None:
    """Persist current DB phase order into the seed file."""
    seed_path = Path(seed_path) if seed_path else config.SEED_PATH
    with uow:
        default_workflow = uow.workflows.get_default()
        if default_workflow:
            workflow_id = default_workflow.id
            load_phases_from_db(uow, workflow_id=workflow_id)

        # Reorder seed entries to match DB order; drop unknown codes.
    code_to_entry: dict[str, dict[str, Any]] = {p["code"]: p for p in _load_seed(seed_path) if isinstance(p, dict)}
    ordered_entries = [code_to_entry[code] for code in ordered_phase_codes if code in code_to_entry]
    for code in code_to_entry:
        if code not in ordered_phase_codes:
            ordered_entries.append(code_to_entry[code])

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".json", delete=False
    ) as tmp:
        json.dump(ordered_entries, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)
    tmp_path.replace(seed_path)


def persist_phase_update_to_seed(
    uow: UnitOfWork,
    updated_phase_code: str,
    data: dict[str, Any],
    seed_path: Path | str | None = None,
) -> None:
    """Update a single phase's metadata in the seed file."""
    seed_path = Path(seed_path) if seed_path else config.SEED_PATH
    if not seed_path.exists():
        return

    with seed_path.open(encoding="utf-8") as f:
        seed_data = yaml.safe_load(f) or []

    for item in seed_data:
        if isinstance(item, dict) and item.get("code") == updated_phase_code:
            for key, value in data.items():
                if key in ("code", "id"):
                    continue
                item[key] = value
            break
    else:
        return

    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".json", delete=False
    ) as tmp:
        json.dump(seed_data, tmp, ensure_ascii=False, indent=2)
        tmp_path = Path(tmp.name)
    tmp_path.replace(seed_path)


def seed_is_stale(seed_path: Path | str | None = None) -> bool:
    """Return True if seed file modification time is older than DB records."""
    seed_path = Path(seed_path) if seed_path else config.SEED_PATH
    if not seed_path.exists():
        return True
    seed_mtime = seed_path.stat().st_mtime
    db_path = Path(config.get_settings().WORKFLOW_DIR) / "workflow.db"
    if not db_path.exists():
        return True
    db_mtime = db_path.stat().st_mtime
    return seed_mtime < db_mtime


def get_seed_mtime(seed_path: Path | str | None = None) -> str:
    """ISO timestamp of the seed file's last modification."""
    seed_path = Path(seed_path) if seed_path else config.SEED_PATH
    if not seed_path.exists():
        return ""
    return datetime.fromtimestamp(seed_path.stat().st_mtime, tz=timezone.utc).isoformat()


# Backward-compatible alias used by a few scripts and smoke tests.
load_phases_from_yaml = load_phases_from_seed
