"""WARTZ Workflow UI v2 — шаблонный FastAPI + Jinja2 viewer.

Сервер:
    python -m wartz_workflow.ui [--port N] [--host H]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from . import schema, config, db

# ── Constants ───────────────────────────────────────────────────────────
DEFAULT_UI_PORT = config.UI_PORT
BASE_DIR = Path(__file__).parent

# ── Jinja2 templates (v2/ под base.html + extends) ──────────────────────
templates = Jinja2Templates(directory=str(BASE_DIR / "templates" / "v2"))

_db: db.WorkflowDB | None = None


def _get_db() -> db.WorkflowDB:
    global _db
    if _db is None:
        _db = db.WorkflowDB()
        _db.init()
        if _db.is_empty():
            _yaml_to_sqlite()
    return _db


def _yaml_to_sqlite() -> None:
    """Разовый импорт phases.yaml → SQLite."""
    yaml_phases = schema.load_phases()
    _phase_order = config.PHASE_ORDER
    batch = []
    for p in yaml_phases:
        # Полные данные фазы для шаблона
        extra = {
            "delegate_agent": p.delegate.agent if p.delegate else None,
            "delegate_timeout": p.delegate.timeout_min if p.delegate else None,
            "delegate_max_cycles": p.delegate.max_cycles if p.delegate else None,
            "delegate_toolsets": json.dumps(p.delegate.toolsets) if p.delegate and p.delegate.toolsets else None,
            "parallel_with": p.parallel_with,
            "rollback_target": p.rollback_target,
            "next_recommendation": p.next_recommendation,
        }
        batch.append(
            {
                "id": p.id,
                "name": p.name,
                "description": p.description or "",
                "phase_order": _phase_order.index(p.id) + 1 if p.id in _phase_order else 0,
                "skills": json.dumps(p.skills) if p.skills else None,
                "instructions": [
                    {
                        "step_num": idx + 1,
                        "description": instr.step,
                        "execution_type": "parallel" if p.is_delegated else "sync",
                        "tool": instr.tool,
                    }
                    for idx, instr in enumerate(p.instructions)
                ],
                "checks": [
                    {"description": c.description, "command": c.command}
                    for c in p.checks
                ],
                "evidence": [
                    {"description": e.item, "validator": e.validator}
                    for e in p.evidence
                ],
                "checkups": [
                    {
                        "name": f"Check {cu}",
                        "check_type": "jira_status",
                        "target": "",
                        "interval_min": 0,
                        "last_status": "unknown",
                        "fail_action": "warn",
                    }
                    for cu in p.checks
                ],
                **extra,
            }
        )
    _db.import_phases(batch)


def _build_execution_batches(phases: list[dict]) -> list[dict]:
    """Разбить фазы на sync/parallel batches для визуализации workflow.

    Синхронные — последовательно, параллельные — объединены в группы по parallel_with.
    """
    phases_by_id = {p["id"]: p for p in phases}
    
    # Найти bidirectional parallel группы (по parallel_with)
    parallel_targets = {}
    for p in phases:
        target = p.get("parallel_with")
        if target and target in phases_by_id:
            key = tuple(sorted([p["id"], target]))
            if key not in parallel_targets:
                parallel_targets[key] = set()
            parallel_targets[key].add(p["id"])
            parallel_targets[key].add(target)
    
    parallel_groups = [
        sorted(list(g), key=lambda x: config.PHASE_ORDER.index(x))
        for g in parallel_targets.values()
    ]
    all_parallel_ids = set()
    for g in parallel_groups:
        all_parallel_ids.update(g)
    
    batches = []
    used = set()
    
    for pid in config.PHASE_ORDER:
        if pid in used:
            continue
        if pid in all_parallel_ids:
            for group in parallel_groups:
                if pid in group:
                    batch_phases = [phases_by_id[g] for g in group if g in phases_by_id]
                    if batch_phases:
                        batches.append({
                            "type": "parallel",
                            "phases": batch_phases,
                            "title": " + ".join(p["name"] for p in batch_phases),
                        })
                    used.update(group)
                    break
        else:
            if pid in phases_by_id:
                batches.append({
                    "type": "sync",
                    "phases": [phases_by_id[pid]],
                    "title": phases_by_id[pid]["name"],
                })
                used.add(pid)
    
    return batches


def _mermaid_from_batches(batches: list[dict]) -> str:
    """Генерация Mermaid flowchart из batches."""
    lines = ["flowchart TD"]
    nodes = []
    edges = []
    prev_node = None
    
    for batch in batches:
        if len(batch["phases"]) == 1:
            p = batch["phases"][0]
            node = f"{p['id']}".replace(".", "_").replace("-", "neg")
            label = f"P{p['phase_num']}:{p['name'][:20]}"
            nodes.append(f"    {node}[{label}]")
            if prev_node:
                edges.append(f"    {prev_node} --> {node}")
            prev_node = node
        else:
            # Parallel group
            first = batch["phases"][0]
            join_node = f"JOIN_{first['id']}".replace(".", "_").replace("-", "neg")
            parallel_nodes = []
            for p in batch["phases"]:
                node = f"{p['id']}".replace(".", "_").replace("-", "neg")
                label = f"P{p['phase_num']}:{p['name'][:20]}"
                nodes.append(f"    {node}[{label}]")
                parallel_nodes.append(node)
            
            # Join node
            nodes.append(f"    {join_node}{{🔄}}")
            
            if prev_node:
                edges.append(f"    {prev_node} --> {parallel_nodes[0]}")
            for node in parallel_nodes:
                edges.append(f"    {node} --> {join_node}")
            prev_node = join_node
    
    return "\n".join(lines + nodes + edges)


app = FastAPI(title="wartz-workflow UI", version="2.0.0")


# ═══════════════════════════════════════════════════════════════════════
#  PHASE GROUPS (for Kanban)
# ═══════════════════════════════════════════════════════════════════════

PHASE_GROUP_NAMES = {
    "setup": "🔧 Setup",
    "research": "🔬 Research",
    "plan": "📋 Plan",
    "dev": "💻 Dev",
    "qa": "🧪 QA",
    "closure": "🏁 Closure",
}

PHASE_TO_GROUP = {
    "-1": "setup", "0.0a": "setup", "0.01": "setup", "0.01a": "setup", "0.01b": "setup",
    "0": "setup", "0.00": "setup", "0.000": "setup", "0.7": "setup",
    "0.5": "research", "0.6": "research", "0.9": "research", "1": "research", "1.5": "research", "2": "research",
    "3": "plan", "3.5": "plan",
    "4": "dev", "4.5": "dev", "5": "dev", "5.5": "dev",
    "7": "qa", "7.5": "qa", "7.6": "qa", "7.6.R": "qa", "7.7": "qa",
    "6": "closure", "8": "closure", "9": "closure", "10": "closure",
}


def _group_phases(phases: list[dict]) -> dict[str, list[dict]]:
    groups = {k: [] for k in PHASE_GROUP_NAMES}
    for p in phases:
        group = PHASE_TO_GROUP.get(p["id"], "setup")
        # Add instruction count from DB
        wdb = _get_db()
        insts = wdb.get_phase_instructions(p["id"])
        p["instruction_count"] = len(insts)
        groups[group].append(p)
    return groups


# ═══════════════════════════════════════════════════════════════════════
#  DATA
# ═══════════════════════════════════════════════════════════════════════

def _load_phases() -> list[dict]:
    wdb = _get_db()
    rows = wdb.get_phases()
    result = []
    for p in rows:
        skills = json.loads(p["skills"]) if p["skills"] else []
        delegate_agent = p.get("delegate_agent")
        result.append(
            {
                "id": p["id"],
                "phase_num": p["phase_order"],
                "name": p["name"],
                "description": p["description"],
                "skills": skills,
                "delegate_agent": delegate_agent,
                "is_delegated": bool(delegate_agent),
                "parallel_with": p.get("parallel_with"),
                "rollback_target": p.get("rollback_target"),
                "delegate_timeout": p.get("delegate_timeout"),
            }
        )
    return result


def _load_phase_detail(phase_id: str) -> dict | None:
    wdb = _get_db()
    phase = wdb.get_phase(phase_id)
    if not phase:
        return None
    phase["phase_num"] = phase["phase_order"]
    phase["skills"] = json.loads(phase["skills"]) if phase["skills"] else []
    # Доп поля из БД
    for key in (
        "delegate_agent", "delegate_timeout", "delegate_max_cycles",
        "delegate_toolsets", "parallel_with", "rollback_target", "next_recommendation",
    ):
        if key not in phase:
            phase[key] = None
    phase["instructions"] = wdb.get_phase_instructions(phase_id)
    phase["checks"] = wdb.get_phase_checks(phase_id)
    phase["evidence"] = wdb.get_phase_evidence(phase_id)
    phase["checkups"] = wdb.get_phase_checkups(phase_id)
    return phase


def _load_tasks() -> list[dict]:
    """Загрузить задачи из state/*.json"""
    tasks = []
    try:
        state_dir = Path(f"{config.WARTZ_DIR}/state")
        if not state_dir.exists():
            return tasks
        for f in sorted(state_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                jira_key = data.get("jira_key", f.stem)
                completed = data.get("phases_completed", [])
                current_phase = data.get("current_phase", "-1")
                phase_map = {p["id"]: p for p in _load_phases()}
                current = phase_map.get(current_phase, {})
                tasks.append(
                    {
                        "jira_key": jira_key,
                        "phase_id": current_phase,
                        "phase_num": current.get("phase_num", "?"),
                        "phase_name": current.get("name", current_phase),
                        "completed": len(completed),
                        "status": "active" if data.get("status") != "done" else "done",
                        "status_label": "В работе" if data.get("status") != "done" else "Завершена",
                    }
                )
            except Exception:
                pass
    except Exception:
        pass
    return tasks


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Pages
# ═══════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    tasks = _load_tasks()
    return templates.TemplateResponse(
        request=request, name="dashboard.html", context={
            "request": request,
            "page": "dashboard",
            "ui_port": config.UI_PORT,
            "task_count": len(tasks),
            "job_count": 0,
            "coverage": "87",
            "completed_phases": sum(t["completed"] for t in tasks),
            "tasks": tasks[:5],
        }
    )


@app.get("/phases", response_class=HTMLResponse)
def phases_page(request: Request):
    phases = _load_phases()
    grouped = _group_phases(phases)
    return templates.TemplateResponse(
        request=request, name="phases.html",
        context={"request": request, "grouped": grouped, "groups": PHASE_GROUP_NAMES, "grouped_phases": grouped, "page": "phases", "ui_port": config.UI_PORT}
    )


@app.get("/execution", response_class=HTMLResponse)
def execution_page(request: Request):
    """Визуальный граф выполнения фаз: sync = последовательно, parallel = ветвления."""
    phases = _load_phases()
    batches = _build_execution_batches(phases)
    mermaid = _mermaid_from_batches(batches)
    return templates.TemplateResponse(
        request=request, name="execution.html",
        context={"request": request, "batches": batches, "mermaid": mermaid, "page": "execution", "ui_port": config.UI_PORT}
    )


@app.get("/phase/{phase_id}", response_class=HTMLResponse)
def phase_detail(request: Request, phase_id: str):
    phase = _load_phase_detail(phase_id)
    if not phase:
        return HTMLResponse("<h1>Phase not found</h1>", status_code=404)
    return templates.TemplateResponse(
        request=request, name="phase_detail.html", context={
            "request": request, "page": "phases", "ui_port": config.UI_PORT, "phase": phase
        }
    )


@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    tasks = _load_tasks()
    return templates.TemplateResponse(
        request=request, name="tasks.html", context={
            "request": request, "page": "tasks", "ui_port": config.UI_PORT, "tasks": tasks,
        }
    )


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="jobs.html", context={
            "request": request, "page": "jobs", "ui_port": config.UI_PORT, "jobs": [],
        }
    )


@app.get("/wizard", response_class=HTMLResponse)
def wizard_page(request: Request):
    return templates.TemplateResponse(
        request=request, name="wizard.html", context={
            "request": request, "page": "tasks", "ui_port": config.UI_PORT, "tasks": _load_tasks(),
        }
    )


# ═══════════════════════════════════════════════════════════════════════
#  API
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/phases")
def api_phases():
    return {"ok": True, "phases": _load_phases()}


@app.get("/api/phases/{phase_id}")
def api_phase_detail(phase_id: str):
    phase = _load_phase_detail(phase_id)
    if not phase:
        return JSONResponse({"ok": False, "error": "Phase not found"}, status_code=404)
    return {"ok": True, "phase": phase}


@app.put("/api/phases/{phase_id}")
def api_phase_update(phase_id: str, body: dict[str, Any]):
    wdb = _get_db()
    phase = wdb.get_phase(phase_id)
    if not phase:
        return JSONResponse({"ok": False, "error": "Phase not found"}, status_code=404)

    # Phase settings — only valid fields
    PHASE_FIELDS = {
        "name", "description", "skills", "delegate_agent",
        "delegate_timeout", "delegate_max_cycles", "delegate_toolsets",
        "parallel_with", "rollback_target", "next_recommendation",
    }
    phase_data = {k: v for k, v in body.items() if k in PHASE_FIELDS}
    if phase_data:
        wdb.update_phase(phase_id, phase_data)

    # Instructions
    for i in body.get("instructions", []):
        # Only valid instruction fields
        inst_data = {k: v for k, v in i.items() if k in {"step_num", "description", "execution_type", "tool"}}
        if i.get("id"):
            wdb.update_instruction(i["id"], inst_data)
        else:
            wdb.create_instruction({"phase_id": phase_id, **inst_data})

    # Checks
    for c in body.get("checks", []):
        check_data = {k: v for k, v in c.items() if k in {"description", "command"}}
        if c.get("id"):
            wdb.update_check(c["id"], check_data)
        else:
            wdb.create_check({"phase_id": phase_id, **check_data})

    # Evidence
    for e in body.get("evidence", []):
        ev_data = {k: v for k, v in e.items() if k in {"description", "validator"}}
        if e.get("id"):
            wdb.update_evidence(e["id"], ev_data)
        else:
            wdb.create_evidence({"phase_id": phase_id, **ev_data})

    return {"ok": True}


@app.delete("/api/instructions/{inst_id}")
def api_delete_instruction(inst_id: int):
    wdb = _get_db()
    wdb.delete_instruction(inst_id)
    return {"ok": True}


@app.delete("/api/checks/{check_id}")
def api_delete_check(check_id: int):
    wdb = _get_db()
    wdb.delete_check(check_id)
    return {"ok": True}


@app.delete("/api/evidence/{ev_id}")
def api_delete_evidence(ev_id: int):
    wdb = _get_db()
    wdb.delete_evidence(ev_id)
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="WARTZ Workflow UI v2")
    parser.add_argument("--port", type=int, default=DEFAULT_UI_PORT, help="Port (default: %(default)s)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: %(default)s)")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
