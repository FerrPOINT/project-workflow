"""Schema loader — reads Phase models from SQLite DB with YAML fallback.

Все данные — только из БД (phases, instructions, checks, evidence).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import yaml

from . import config
from wartz_workflow.models import (
    Phase,
    PhaseCheck,
    PhaseDelegate,
    PhaseEvidence,
    PhaseInstruction,
)
from wartz_workflow.db import WorkflowDB


# ── DB Load ─────────────────────────────────────────────────────

def _build_phase_from_db(row: dict, wdb: WorkflowDB) -> Phase:
    """Assemble a Phase dataclass from DB rows."""
    phase_id = row["id"]

    inst_rows = wdb.get_phase_instructions(phase_id)
    instructions = [
        PhaseInstruction(
            step=ir["description"],
            execution_type=ir.get("execution_type", "sync"),
        )
        for ir in inst_rows
    ]

    check_rows = wdb.get_phase_checks(phase_id)
    checks = [
        PhaseCheck(
            description=cr["description"],
        )
        for cr in check_rows
    ]

    ev_rows = wdb.get_phase_evidence(phase_id)
    evidence = [
        PhaseEvidence(
            item=er["description"],
        )
        for er in ev_rows
    ]

    skills = json.loads(row["skills"]) if row.get("skills") else []

    delegate = None
    if row.get("agent_id"):
        agent = wdb.get_agent(row["agent_id"])
        if agent:
            delegate = PhaseDelegate(
                agent=agent["name"],
                prompt_template=f"Phase {phase_id}",
                toolsets=json.loads(agent["toolsets"]) if agent.get("toolsets") else [],
                timeout_min=agent.get("timeout") or 10,
                max_cycles=agent.get("max_cycles") or 3,
            )

    return Phase(
        id=phase_id,
        name=row["name"],
        description=row.get("description") or "",
        min_time_min=row.get("min_time_min") or 0,
        is_blocker=phase_id in config.BLOCKER_PHASES,
        is_delegated=bool(delegate),
        is_critic=phase_id in config.CRITIC_PHASES,
        skills=skills,
        checks=checks,
        evidence=evidence,
        instructions=instructions,
        delegate=delegate,
        next_recommendation=row.get("next_recommendation") or "",
        parallel_with=row.get("parallel_with"),
        gate_after=None,
        rollback_target=row.get("rollback_target"),
        execution_type=row.get("execution_type", "sync"),
    )


def load_phases_from_db(wdb: WorkflowDB) -> List[Phase]:
    """Load all phases from a WorkflowDB instance (already initialised)."""
    rows = wdb.get_phases()
    return [_build_phase_from_db(r, wdb) for r in rows]


def get_phase_from_db(wdb: WorkflowDB, phase_id: str) -> Optional[Phase]:
    """Find a single phase by ID in a WorkflowDB instance."""
    rows = wdb.get_phases()
    for r in rows:
        if r["id"] == phase_id:
            return _build_phase_from_db(r, wdb)
    return None


def load_phases() -> List[Phase]:
    """Load all phases from DB ordered by phase_order."""
    wdb = WorkflowDB()
    wdb.init()
    if wdb.is_empty():
        return _load_phases_yaml()
    rows = wdb.get_phases()
    return [_build_phase_from_db(r, wdb) for r in rows]


# ── YAML fallback (legacy, kept for initial import only) ───────────

_YAML_PATH = Path(__file__).parent / "references" / "phases.yaml"


def _load_phases_yaml() -> List[Phase]:
    """Fallback YAML loader (returns empty list if YAML missing)."""
    if not _YAML_PATH.exists():
        return []
    with open(_YAML_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    _check_keys = {"description", "path", "expected", "fail_msg", "optional"}
    _evidence_keys = {"item", "validator"}
    _inst_keys = {"step", "example", "execution_type"}

    phases: List[Phase] = []
    for item in raw.get("phases", []):
        checks = [
            PhaseCheck(**{k: v for k, v in c.items() if k in _check_keys})
            for c in item.get("checks", [])
        ]
        evidence = [
            PhaseEvidence(**{k: v for k, v in e.items() if k in _evidence_keys})
            for e in item.get("evidence", [])
        ]
        instructions = [
            PhaseInstruction(**{k: v for k, v in i.items() if k in _inst_keys})
            for i in item.get("instructions", [])
        ]
        delegate = None
        if "delegate" in item:
            d = item["delegate"]
            delegate = PhaseDelegate(
                agent=d["agent"],
                prompt_template=d.get("prompt_template", ""),
                context=d.get("context", []),
                toolsets=d.get("toolsets", []),
                timeout_min=d.get("timeout_min", 10),
                max_cycles=d.get("max_cycles", 3),
            )
        phases.append(Phase(
            id=item["id"],
            name=item["name"],
            description=item.get("description", ""),
            min_time_min=item.get("min_time_min", 0),
            is_blocker=item.get("is_blocker", False),
            is_delegated=item.get("is_delegated", False),
            is_critic=item.get("is_critic", False),
            skills=item.get("skills", []),
            checks=checks,
            evidence=evidence,
            instructions=instructions,
            delegate=delegate,
            next_recommendation=item.get("next_recommendation", ""),
            parallel_with=item.get("parallel_with"),
            gate_after=item.get("gate_after"),
            rollback_target=item.get("rollback_target"),
            execution_type=item.get("execution_type", "sync"),
        ))
    return phases


def get_phase(phase_id: str, phases: Optional[List[Phase]] = None) -> Optional[Phase]:
    """Найти фазу по ID."""
    plist = phases or load_phases()
    for ph in plist:
        if ph.id == phase_id:
            return ph
    return None


def get_phase_order(phases: Optional[List[Phase]] = None) -> List[str]:
    """Вернуть список ID фаз в порядке следования."""
    plist = phases or load_phases()
    return [p.id for p in plist]
