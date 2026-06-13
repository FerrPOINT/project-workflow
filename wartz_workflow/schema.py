"""Schema loader — reads Phase models from SQLite DB with YAML fallback.

Все данные — только из БД (phases, instructions, checks, evidence).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

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
        rollback_target=row.get("rollback_target"),
        execution_type=row.get("execution_type", "sync"),
    )


def load_phases_from_db(wdb: WorkflowDB, workflow_id: int | str | None = None) -> List[Phase]:
    """Load all phases from a WorkflowDB instance (already initialised)."""
    rows = wdb.get_phases(workflow_id=workflow_id)
    return [_build_phase_from_db(r, wdb) for r in rows]


def get_phase_from_db(wdb: WorkflowDB, phase_code: str, workflow_id: int | str | None = None) -> Optional[Phase]:
    """Find a single phase by code in a WorkflowDB instance."""
    rows = wdb.get_phases(workflow_id=workflow_id)
    for r in rows:
        if r.get("code", r["id"]) == phase_code:
            return _build_phase_from_db(r, wdb)
    return None


def load_phases(workflow_id: int | str | None = None) -> List[Phase]:
    """Load all phases from DB ordered by phase_order."""
    wdb = WorkflowDB()
    wdb.init()
    ensure_phase_catalog(wdb)
    rows = wdb.get_phases(workflow_id=workflow_id)
    return [_build_phase_from_db(r, wdb) for r in rows]


# ── JSON Seed fallback ───────────

_SEED_PATH = Path(__file__).parent / "references" / "seed.json"
_SMOKE_SEED_PATH = Path(__file__).parent / "references" / "smoke_seed.json"


def _read_seed_items_from_path(seed_path: Path, allowed_codes: Sequence[str] | None = None) -> List[dict]:
    if not seed_path.exists():
        return []

    with open(seed_path, encoding="utf-8") as f:
        raw = json.load(f)

    filtered: list[dict] = []
    allowed_lookup = list(allowed_codes) if allowed_codes is not None else None
    allowed_set = set(allowed_lookup) if allowed_lookup is not None else None
    for item in raw:
        code = item.get("code", item.get("id", ""))
        if not code:
            continue
        if allowed_set is not None and code not in allowed_set:
            continue
        normalized = dict(item)
        normalized["code"] = code
        filtered.append(normalized)

    if allowed_lookup is not None:
        filtered.sort(key=lambda item: allowed_lookup.index(item["code"]))
    return filtered


def _read_seed_items() -> List[dict]:
    return _read_seed_items_from_path(_SEED_PATH, config.PHASE_ORDER)


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
    if not (
        relevant_top_level_fields.intersection(body)
        or relevant_collection_fields.intersection(body)
        or "agent_id" in body
    ):
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

    if "agent_id" in body:
        agent_name = None
        if phase.get("agent_id"):
            agent = wdb.get_agent(phase["agent_id"])
            if agent:
                agent_name = str(agent.get("name") or "").strip() or None
        seed_item["selected_agent"] = agent_name

    if "instructions" in body:
        seed_item["instructions"] = _serialize_seed_instructions(body.get("instructions") or [])
    if "checks" in body:
        seed_item["checks"] = _serialize_seed_checks(body.get("checks") or [])
    if "evidence" in body:
        seed_item["evidence"] = _serialize_seed_evidence(body.get("evidence") or [])

    raw[item_index] = seed_item
    _write_seed_document(raw)


def persist_phase_order_to_seed(wdb: WorkflowDB, ordered_phase_ids: Sequence[int | str]) -> None:
    if not ordered_phase_ids:
        return
    if not _SEED_PATH.exists():
        return

    with open(_SEED_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    seed_codes = [
        str(item.get("code", item.get("id", ""))).strip()
        for item in raw
        if str(item.get("code", item.get("id", ""))).strip()
    ]
    if not seed_codes:
        return

    ordered_seed_codes: list[str] = []
    for phase_id in ordered_phase_ids:
        phase = wdb.get_phase(phase_id)
        if not phase:
            return
        if not phase.get("workflow_is_default") or not phase.get("is_seed_managed"):
            continue
        code = str(phase.get("code", phase_id)).strip()
        if code in seed_codes:
            ordered_seed_codes.append(code)

    if set(ordered_seed_codes) != set(seed_codes):
        return

    order_index = {code: idx for idx, code in enumerate(ordered_seed_codes)}
    raw.sort(
        key=lambda item: order_index.get(
            str(item.get("code", item.get("id", ""))).strip(),
            len(order_index),
        )
    )
    _write_seed_document(raw)


def ensure_phase_catalog(wdb: WorkflowDB) -> None:
    default_seed_items = _read_seed_items()
    default_workflow = wdb.get_default_workflow()
    if default_seed_items and default_workflow:
        wdb.sync_phase_catalog(
            default_seed_items,
            config.PHASE_ORDER,
            config.LEGACY_PHASE_REDIRECTS,
            workflow_id=default_workflow["id"],
        )

    smoke_seed_items = _read_seed_items_from_path(_SMOKE_SEED_PATH)
    smoke_workflow = wdb.get_workflow_by_name(config.SMOKE_WORKFLOW_NAME)
    if smoke_seed_items and smoke_workflow:
        smoke_phase_order = [item["code"] for item in smoke_seed_items]
        wdb.sync_phase_catalog(
            smoke_seed_items,
            smoke_phase_order,
            {},
            workflow_id=smoke_workflow["id"],
        )


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


def generate_progress_json(task_key: str, task_id: str, title: str, sprint: str) -> str:
    """Генерация progress.json template.  Kept for test_runtime_cleanup compat."""
    phases_data = [
        {"phase": "-1", "name": "Task Intake", "status": "pending", "min_time_min": 1},
        {"phase": "0.0a", "name": "Suite Verification", "status": "pending", "min_time_min": 2},
        {"phase": "0.01", "name": "Task Docs Setup", "status": "pending", "min_time_min": 2},
        {"phase": "0.000", "name": "Workspace", "status": "pending", "min_time_min": 1},
        {"phase": "0.00", "name": "Git Identity", "status": "pending", "min_time_min": 1},
        {"phase": "0.7", "name": "Repo Sync", "status": "pending", "min_time_min": 2},
        {"phase": "0.9", "name": "CriticGate-PreFlight", "status": "pending", "min_time_min": 2},
        {"phase": "0.5", "name": "Jira Transition", "status": "pending", "min_time_min": 1},
        {"phase": "0.6", "name": "Researcher #1", "status": "pending", "min_time_min": 5},
        {"phase": "1", "name": "Preflight", "status": "pending", "min_time_min": 10},
        {"phase": "1.5", "name": "Deep Research", "status": "pending", "min_time_min": 5},
        {"phase": "2", "name": "Research Synthesis", "status": "pending", "min_time_min": 10},
        {"phase": "3", "name": "Plan", "status": "pending", "min_time_min": 15},
        {"phase": "3.5", "name": "CriticGate-PrePlan", "status": "pending", "min_time_min": 5},
        {"phase": "4", "name": "Implement", "status": "pending", "min_time_min": 30},
        {"phase": "4.5", "name": "CriticGate-PreCommit", "status": "pending", "min_time_min": 5},
        {"phase": "5", "name": "Validate", "status": "pending", "min_time_min": 10},
        {"phase": "5.5", "name": "Self-Test", "status": "pending", "min_time_min": 15},
        {"phase": "6", "name": "Commit", "status": "pending", "min_time_min": 3},
        {"phase": "7", "name": "MR Draft", "status": "pending", "min_time_min": 5},
        {"phase": "7.5", "name": "Code Review", "status": "pending", "min_time_min": 10},
        {"phase": "7.6", "name": "QA Testing", "status": "pending", "min_time_min": 10},
        {"phase": "7.6.R", "name": "DVR", "status": "pending", "min_time_min": 5},
        {"phase": "7.7", "name": "CriticGate-PostQA", "status": "pending", "min_time_min": 5},
        {"phase": "8", "name": "Jira Done", "status": "pending", "min_time_min": 2},
        {"phase": "9", "name": "Retro", "status": "pending", "min_time_min": 10},
        {"phase": "10", "name": "Auto-Improve", "status": "pending", "min_time_min": 10},
    ]

    data = {
        "task_key": task_key,
        "task_id": task_id,
        "title": title,
        "sprint": sprint,
        "version": "1.0.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "phases": phases_data,
    }

    return json.dumps(data, indent=2, ensure_ascii=False)
