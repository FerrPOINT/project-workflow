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
        is_blocker=False,
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
    ensure_phase_catalog(wdb)
    rows = wdb.get_phases()
    return [_build_phase_from_db(r, wdb) for r in rows]


# ── JSON Seed fallback ───────────

_SEED_PATH = Path(__file__).parent / "references" / "seed.json"


def _read_seed_items() -> List[dict]:
    if not _SEED_PATH.exists():
        return []

    with open(_SEED_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    allowed_codes = set(config.PHASE_ORDER)
    filtered: list[dict] = []
    for item in raw:
        code = item.get("code", item.get("id", ""))
        if not code:
            continue
        if code not in allowed_codes:
            continue
        normalized = dict(item)
        normalized["code"] = code
        filtered.append(normalized)

    filtered.sort(key=lambda item: config.PHASE_ORDER.index(item["code"]))
    return filtered


def _write_seed_document(items: List[dict]) -> None:
    _SEED_PATH.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _serialize_seed_instructions(items: list[dict]) -> List[dict]:
    serialized: list[dict] = []
    for idx, item in enumerate(items, start=1):
        payload = {
            "step_num": item.get("step_num", idx),
            "description": item["description"],
            "execution_type": item.get("execution_type", "sync"),
        }
        skills = item.get("skills")
        if skills not in (None, [], ""):
            payload["skills"] = skills
        tool = item.get("tool")
        if tool is not None:
            payload["tool"] = tool
        serialized.append(payload)
    return serialized


def _serialize_seed_checks(items: list[dict]) -> List[dict]:
    return [{"description": item["description"]} for item in items]


def _serialize_seed_evidence(items: list[dict]) -> List[dict]:
    return [{"description": item.get("description", item.get("item", ""))} for item in items]


def persist_phase_update_to_seed(wdb: WorkflowDB, phase_id: int | str, body: dict) -> None:
    relevant_top_level_fields = {
        "name",
        "description",
        "delegate_agent",
        "delegate_timeout",
        "parallel_with",
        "rollback_target",
        "next_recommendation",
        "execution_type",
    }
    relevant_collection_fields = {"instructions", "checks", "evidence"}
    if not (relevant_top_level_fields.intersection(body) or relevant_collection_fields.intersection(body)):
        return
    if not _SEED_PATH.exists():
        return

    with open(_SEED_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    phase = wdb.get_phase(phase_id)
    if not phase:
        return
    code = str(phase.get("code", phase_id))

    item_index = next(
        (
            idx
            for idx, item in enumerate(raw)
            if str(item.get("code", item.get("id", ""))).strip() == code
        ),
        None,
    )
    if item_index is None:
        return

    seed_item = dict(raw[item_index])
    seed_item["code"] = code

    for field in relevant_top_level_fields:
        if field in body:
            seed_item[field] = phase.get(field)

    if "instructions" in body:
        seed_item["instructions"] = _serialize_seed_instructions(body.get("instructions") or [])
    if "checks" in body:
        seed_item["checks"] = _serialize_seed_checks(body.get("checks") or [])
    if "evidence" in body:
        seed_item["evidence"] = _serialize_seed_evidence(body.get("evidence") or [])

    raw[item_index] = seed_item
    _write_seed_document(raw)


def ensure_phase_catalog(wdb: WorkflowDB) -> None:
    seed_items = _read_seed_items()
    if not seed_items:
        return
    wdb.sync_phase_catalog(seed_items, config.PHASE_ORDER, config.LEGACY_PHASE_REDIRECTS)


def _load_phases_seed() -> List[Phase]:
    """Load phases from JSON seed and import into DB if empty."""
    raw = _read_seed_items()
    if not raw:
        return []
    wdb = WorkflowDB()
    wdb.init()
    ensure_phase_catalog(wdb)
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
        is_blocker=False,
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
