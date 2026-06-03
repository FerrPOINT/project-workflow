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
        result.append(
            {
                "id": p["id"],
                "phase_num": p["phase_order"],
                "name": p["name"],
                "description": p["description"],
                "skills": json.loads(p["skills"]) if p["skills"] else [],
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
    state_dir = Path(f"{config.WARTZ_DIR}/state")
    if not state_dir.exists():
        return tasks
    for f in sorted(state_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            jira_key = data.get("jira_key", f.stem)
            completed = data.get("phases_completed", [])
            current_phase = data.get("current_phase", "-1")
            # Найти имя фазы
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
        request=request, name="phases.html", context={
            "request": request, "page": "phases", "ui_port": config.UI_PORT,
            "groups": PHASE_GROUP_NAMES, "grouped_phases": grouped,
        }
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
        "tasks.html",
        {"request": request, "page": "tasks", "ui_port": config.UI_PORT, "tasks": tasks},
    )


@app.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request):
    return templates.TemplateResponse(
        "jobs.html",
        {"request": request, "page": "jobs", "ui_port": config.UI_PORT, "jobs": []},
    )


@app.get("/wizard", response_class=HTMLResponse)
def wizard_page(request: Request):
    return templates.TemplateResponse(
        "wizard.html",
        {"request": request, "page": "tasks", "ui_port": config.UI_PORT, "tasks": _load_tasks()},
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
    # Update settings
    wdb.update_phase(phase_id, body)
    # Update instructions
    for i in body.get("instructions", []):
        if i.get("id"):
            wdb.update_instruction(i["id"], i)
        else:
            wdb.create_instruction(phase_id, i)
    # Update checks
    for c in body.get("checks", []):
        if c.get("id"):
            wdb.update_check(c["id"], c)
        else:
            wdb.create_check(phase_id, c)
    # Update evidence
    for e in body.get("evidence", []):
        if e.get("id"):
            wdb.update_evidence(e["id"], e)
        else:
            wdb.create_evidence(phase_id, e)
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
