"""Schema loader — reads Phase models from SQLite DB with YAML fallback."""

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
    PhaseQuestion,
)
from wartz_workflow.db import WorkflowDB


def _build_phase_from_db(row: dict, wdb: WorkflowDB) -> Phase:
    """Assemble a Phase dataclass from DB rows."""
    phase_id = row["id"]

    inst_rows = wdb.get_phase_instructions(phase_id)
    instructions = [
        PhaseInstruction(
            step=ir["description"],
            tool=ir.get("tool"),
            execution_type=ir.get("execution_type", "sync"),
        )
        for ir in inst_rows
    ]

    check_rows = wdb.get_phase_checks(phase_id)
    checks = [
        PhaseCheck(
            type=cr.get("check_type") or "script_pass",
            description=cr["description"],
            command=cr.get("command"),
        )
        for cr in check_rows
    ]

    ev_rows = wdb.get_phase_evidence(phase_id)
    evidence = [
        PhaseEvidence(
            item=er["description"],
            validator=er.get("validator"),
        )
        for er in ev_rows
    ]

    q_rows = wdb.get_questions(phase_id)
    questions = [
        PhaseQuestion(
            text=qr["qtext"],
            required=bool(qr.get("required", 1)),
            expected_keywords=json.loads(qr["expected_keywords"]) if qr.get("expected_keywords") else [],
            hint=qr.get("hint"),
            auto_command=qr.get("auto_command"),
            validate_fn=qr.get("validate_fn"),
            min_evidence_lines=1,
        )
        for qr in q_rows
    ]

    delegate = None
    if row.get("delegate_agent"):
        delegate = PhaseDelegate(
            agent=row["delegate_agent"],
            prompt_template="",
            toolsets=json.loads(row["delegate_toolsets"]) if row.get("delegate_toolsets") else [],
            timeout_min=row.get("delegate_timeout") or 10,
            max_cycles=row.get("delegate_max_cycles") or 3,
        )

    skills = json.loads(row["skills"]) if row.get("skills") else []

    return Phase(
        id=phase_id,
        name=row["name"],
        description=row.get("description") or "",
        min_time_min=row.get("min_time_min") or 0,
        is_blocker=phase_id in config.BLOCKER_PHASES,
        is_delegated=bool(row.get("delegate_agent")),
        is_critic=phase_id in config.CRITIC_PHASES,
        skills=skills,
        checks=checks,
        evidence=evidence,
        instructions=instructions,
        questions=questions,
        delegate=delegate,
        next_recommendation=row.get("next_recommendation") or "",
        parallel_with=row.get("parallel_with"),
        gate_after=None,
        rollback_target=row.get("rollback_target"),
        execution_mode=row.get("execution_mode", "sync"),
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
    """Load all phases from DB ordered by phase_order, with YAML fallback."""
    wdb = WorkflowDB()
    wdb.init()
    if wdb.is_empty():
        return _load_phases_yaml()
    rows = wdb.get_phases()
    return [_build_phase_from_db(r, wdb) for r in rows]


# ── YAML fallback (kept for backward compatibility) ────────────────────

_YAML_PATH = Path(__file__).parent / "references" / "phases.yaml"


def _load_phases_yaml() -> List[Phase]:
    """Fallback YAML loader (returns empty list if YAML missing)."""
    if not _YAML_PATH.exists():
        return []
    with open(_YAML_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    phases: List[Phase] = []
    for item in raw.get("phases", []):
        checks = [PhaseCheck(**c) for c in item.get("checks", [])]
        evidence = [PhaseEvidence(**e) for e in item.get("evidence", [])]
        instructions = [PhaseInstruction(**i) for i in item.get("instructions", [])]
        questions = [PhaseQuestion(**q) for q in item.get("questions", [])]
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
            questions=questions,
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
