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
    phase_code = row.get("code", "")
    inst_rows = wdb.get_phase_instructions(phase_id)

    instructions = [
        PhaseInstruction(
            step=ir["description"],
            example=ir.get("example"),
            execution_type=ir.get("execution_type", "sync"),
            skills=json.loads(ir["skills"]) if ir.get("skills") else [],
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

    delegate = None
    if row.get("agent_id"):
        agent = wdb.get_agent(row["agent_id"])
        if agent:
            delegate = PhaseDelegate(
                agent=agent["name"],
                prompt_template=f"Phase {phase_code}",
                toolsets=json.loads(agent["toolsets"]) if agent.get("toolsets") else [],
                timeout_min=agent.get("timeout") or 10,
                max_cycles=agent.get("max_cycles") or 3,
            )

    return Phase(
        id=phase_id,
        code=phase_code,
        name=row["name"],
        description=row.get("description") or "",
        min_time_min=row.get("min_time_min") or 0,
        is_blocker=phase_code in config.BLOCKER_PHASES,
        is_delegated=bool(delegate),
        is_critic=phase_code in config.CRITIC_PHASES,
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


def get_phase_from_db(wdb: WorkflowDB, phase_code: str) -> Optional[Phase]:
    """Find a single phase by code in a WorkflowDB instance."""
    rows = wdb.get_phases()
    for r in rows:
        if r.get("code", r["id"]) == phase_code:
            return _build_phase_from_db(r, wdb)
    return None


def load_phases() -> List[Phase]:
    """Load all phases from DB ordered by phase_order."""
    wdb = WorkflowDB()
    wdb.init()
    if wdb.is_empty():
        return _load_phases_seed()
    rows = wdb.get_phases()
    return [_build_phase_from_db(r, wdb) for r in rows]


# ── JSON Seed fallback ───────────

_SEED_PATH = Path(__file__).parent / "references" / "seed.json"


def _load_phases_seed() -> List[Phase]:
    """Load phases from JSON seed and import into DB if empty."""
    if not _SEED_PATH.exists():
        return []
    import json
    with open(_SEED_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    _check_keys = {"description", "path", "expected", "fail_msg", "optional"}
    _evidence_keys = {"item", "validator"}
    _inst_keys = {"step", "example", "execution_type", "skills"}

    # Ensure phases have code
    for item in raw:
        if "code" not in item:
            item["code"] = item.get("id", "")

    wdb = WorkflowDB()
    wdb.init()
    rows = wdb.get_phases()
    if not rows:
        # Import into DB so they get integer IDs and code
        wdb.import_phases(raw)
        rows = wdb.get_phases()

    return [_build_phase_from_db(r, wdb) for r in rows]


def _parse_old_yaml(item: dict) -> Phase:
    """Parse a seed JSON phase item."""
    _check_keys = {"description", "path", "expected", "fail_msg", "optional"}
    _evidence_keys = {"item", "validator"}
    _inst_keys = {"step", "example", "execution_type", "skills"}

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
    code = item.get("code", item.get("id", ""))
    return Phase(
        id=0,
        code=code,
        name=item["name"],
        description=item.get("description", ""),
        min_time_min=item.get("min_time_min", 0),
        is_blocker=code in config.BLOCKER_PHASES,
        is_delegated=bool(delegate),
        is_critic=code in config.CRITIC_PHASES,
        checks=checks,
        evidence=evidence,
        instructions=instructions,
        delegate=delegate,
        next_recommendation=item.get("next_recommendation", ""),
        parallel_with=item.get("parallel_with"),
        gate_after=item.get("gate_after"),
        rollback_target=item.get("rollback_target"),
        execution_type=item.get("execution_type", "sync"),
    )


def get_phase(phase_code: str, phases: Optional[List[Phase]] = None) -> Optional[Phase]:
    """Найти фазу по code."""
    plist = phases or load_phases()
    for ph in plist:
        if ph.code == phase_code:
            return ph
    return None


def get_phase_order(phases: Optional[List[Phase]] = None) -> List[str]:
    """Вернуть список code фаз в порядке следования."""
    plist = phases or load_phases()
    return [p.code for p in plist]
