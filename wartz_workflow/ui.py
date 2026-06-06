"""WARTZ Workflow UI v2 — шаблонный FastAPI + Jinja2 viewer.

Сервер:
    python -m wartz_workflow.ui [--port N] [--host H]
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

import click
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from . import schema, config, db, service

# ── Constants ───────────────────────────────────────────────────────────
DEFAULT_UI_PORT = config.UI_PORT
BASE_DIR = Path(__file__).parent

# ── Jinja2 templates (v2/ под base.html + extends) ──────────────────────
templates = Jinja2Templates(directory=str(BASE_DIR / "templates" / "v2"))

def _group_instructions(instructions):
    """Группирует инструкции по runs: parallel примыкает к предыдущей sync и идёт с ней рядом."""
    if not instructions:
        return []
    groups = []
    current = [instructions[0]]
    for i in instructions[1:]:
        if i.get('execution_type') == 'parallel':
            current.append(i)          # parallel → в ту же группу (параллельно предыдущей)
        else:
            groups.append(current)      # sync → новый run
            current = [i]
    groups.append(current)
    return groups

templates.env.filters['group_instructions'] = _group_instructions


def _build_parallel_phase_blocks(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Группирует фазы по execution_type-run: parallel примыкает к текущему sync-run."""
    if not phases:
        return []

    runs: list[list[dict[str, Any]]] = []
    current_run: list[dict[str, Any]] = [phases[0]]

    for phase in phases[1:]:
        if phase.get("execution_type") == "parallel":
            current_run.append(phase)
        else:
            runs.append(current_run)
            current_run = [phase]
    runs.append(current_run)

    blocks: list[dict[str, Any]] = []
    for run in runs:
        if len(run) > 1:
            group_key = run[0]["code"]
            for phase in run:
                phase["parallel_group"] = group_key
            blocks.append({"kind": "parallel", "phases": run})
        else:
            run[0]["parallel_group"] = None
            blocks.append({"kind": "single", "phases": run})

    return blocks


_db: db.WorkflowDB | None = None
_srv: service.PhaseService | None = None

def _get_db() -> db.WorkflowDB:
    """Singleton + lazy init."""
    global _db
    if _db is None:
        _db = db.WorkflowDB()
        _db.init()
    schema.ensure_phase_catalog(_db)
    return _db

def _get_service() -> service.PhaseService:
    """Service singleton."""
    global _srv
    if _srv is None:
        _srv = service.PhaseService(_get_db())
    return _srv


def _load_cli_reference() -> list[dict[str, Any]]:
    """Авто-обнаружение пользовательских CLI-команд для справки UI."""
    from .cli.core import cli as workflow_cli

    commands: list[dict[str, Any]] = []
    for name, command in workflow_cli.commands.items():
        if name == "ui" or getattr(command, "hidden", False):
            continue

        help_text = (command.help or command.short_help or "").strip()
        summary = help_text.splitlines()[0].strip() if help_text else ""
        options = []
        for param in command.params:
            if not isinstance(param, click.Option):
                continue
            flags = [flag for flag in [*param.opts, *param.secondary_opts] if flag]
            if not flags:
                continue

            option_payload = {
                "flags": ", ".join(flags),
                "help": (param.help or "").strip(),
                "required": bool(param.required),
            }
            default_value = param.default
            has_meaningful_default = (
                default_value is not None
                and default_value != ""
                and not (isinstance(default_value, bool) and default_value is False)
                and not param.required
            )
            if has_meaningful_default:
                option_payload["default"] = default_value

            options.append(option_payload)

        commands.append(
            {
                "name": name,
                "summary": summary,
                "usage": f"wartz-workflow {name}",
                "help": help_text,
                "options": options,
            }
        )

    return commands


def _seed_to_sqlite() -> None:
    """Разовый импорт seed.json → SQLite."""
    if _db is not None:
        schema.ensure_phase_catalog(_db)




app = FastAPI(title="wartz-workflow UI", version="2.0.0")


# ═══════════════════════════════════════════════════════════════════════
#  DATA
# ═══════════════════════════════════════════════════════════════════════

def _parse_optional_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _load_workflows() -> list[dict]:
    wdb = _get_db()
    workflows = wdb.get_workflows()
    phases = wdb.get_phases()
    projects = wdb.get_projects()
    phase_counts: dict[int, int] = {}
    project_counts: dict[int, int] = {}
    for phase in phases:
        wid = phase.get("workflow_id")
        if isinstance(wid, int):
            phase_counts[wid] = phase_counts.get(wid, 0) + 1
    for project in projects:
        wid = project.get("workflow_id")
        if isinstance(wid, int):
            project_counts[wid] = project_counts.get(wid, 0) + 1

    result = []
    for workflow in workflows:
        result.append(
            {
                **workflow,
                "phase_count": phase_counts.get(workflow["id"], 0),
                "project_count": project_counts.get(workflow["id"], 0),
            }
        )
    return result


def _load_phases(workflow_id: int | None = None) -> list[dict]:
    wdb = _get_db()
    rows = wdb.get_phases(workflow_id=workflow_id)
    agents_by_id = {agent["id"]: agent for agent in wdb.get_agents()}
    result = []
    for p in rows:
        delegate_agent = p.get("delegate_agent")
        selected_agent = agents_by_id.get(p.get("agent_id")) if p.get("agent_id") else None
        result.append(
            {
                "id": p["id"],
                "code": p["code"],
                "workflow_id": p.get("workflow_id"),
                "workflow_code": p.get("workflow_code"),
                "workflow_name": p.get("workflow_name"),
                "phase_num": p["phase_order"],
                "name": p["name"],
                "description": p["description"],
                "delegate_agent": delegate_agent,
                "is_delegated": bool(delegate_agent),
                "agent_id": p.get("agent_id"),
                "agent_name": selected_agent.get("name") if selected_agent else None,
                "rollback_target": p.get("rollback_target"),
                "delegate_timeout": p.get("delegate_timeout"),
                "execution_type": p.get("execution_type", "sync"),
                "parallel_with": p.get("parallel_with"),
            }
        )
    return result


def _coerce_phase_db_id(raw_phase_id: int | str | None) -> int | None:
    if isinstance(raw_phase_id, int):
        return raw_phase_id if raw_phase_id > 0 else None
    if raw_phase_id is None:
        return None
    token = str(raw_phase_id).strip()
    if not token.isdigit():
        return None
    phase_id = int(token)
    return phase_id if phase_id > 0 else None


def _load_phase_detail(phase_id: int | str) -> dict | None:
    resolved_phase_id = _coerce_phase_db_id(phase_id)
    if resolved_phase_id is None:
        return None
    phase = _get_service().get_phase_detail(resolved_phase_id)
    if not phase:
        return None
    phase = dict(phase)
    phase["phase_num"] = phase.get("phase_num", phase.get("phase_order"))
    return phase


def _resolve_task_phase(current_phase: Any, wdb: db.WorkflowDB) -> tuple[str, dict | None]:
    token = str(current_phase if current_phase is not None else "-1")
    phase = wdb.get_phase(token)
    if phase:
        return token, phase
    redirected = config.LEGACY_PHASE_REDIRECTS.get(token)
    if redirected:
        redirected_phase = wdb.get_phase(redirected)
        if redirected_phase:
            return redirected, redirected_phase
    try:
        numeric = int(token)
    except (TypeError, ValueError):
        return token, None
    return token, wdb.get_phase(numeric)


def _load_tasks() -> list[dict]:
    """Загрузить задачи из SQLite."""
    wdb = _get_db()
    tasks = wdb.get_tasks()
    result = []
    
    for t in tasks:
        # Count completed phases
        task_history = wdb.get_task_history(t["id"])
        completed = sum(1 for tp in task_history if tp["status"] == "done")
        
        # Get current phase info
        current_phase_id, current = _resolve_task_phase(t.get("current_phase", "-1"), wdb)
        current = current or {}
        project_code = t.get("project_code") or "—"
        project_name = t.get("project_name") or project_code
        
        result.append(
            {
                "id": t["id"],
                "task_key": t["task_key"],
                "title": t.get("title", ""),
                "project_id": t.get("project_id"),
                "project_code": project_code,
                "project_name": project_name,
                "project_label": project_name if project_name == project_code else f"{project_code} — {project_name}",
                "phase_id": current.get("code", current_phase_id),
                "phase_num": current.get("phase_num", "?"),
                "phase_name": current.get("name", current_phase_id),
                "current_phase_name": current.get("name", current_phase_id),
                "completed": completed,
                "total_phases": len(config.PHASE_ORDER),
                "status": t.get("status", "active"),
                "status_label": "В работе" if t.get("status") != "done" else "Завершена",
                "created_at": t.get("created_at", ""),
            }
        )
    
    return result


def _load_projects() -> list[dict]:
    """Список проектов для UI."""
    wdb = _get_db()
    projects = wdb.get_projects()
    tasks = wdb.get_tasks()
    task_counts: dict[int, int] = {}
    for task in tasks:
        pid = task.get("project_id")
        if isinstance(pid, int):
            task_counts[pid] = task_counts.get(pid, 0) + 1

    result = []
    for project in projects:
        patterns = project.get("key_patterns") or []
        result.append(
            {
                **project,
                "task_count": task_counts.get(project["id"], 0),
                "patterns_count": len(patterns),
            }
        )
    return result


def _parse_key_patterns(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [line.strip() for line in raw.splitlines() if line.strip()]
    return []


def _project_form_payload(body: dict[str, Any]) -> dict[str, Any]:
    code = str(body.get("code", "")).strip()
    name = str(body.get("name", "")).strip()
    workflow_id = _parse_optional_int(body.get("workflow_id"))
    return {
        "code": code,
        "name": name or code,
        "workflow_id": workflow_id,
        "key_patterns": _parse_key_patterns(body.get("key_patterns", [])),
    }


def _workflow_form_payload(body: dict[str, Any]) -> dict[str, Any]:
    code = str(body.get("code", body.get("id", ""))).strip()
    name = str(body.get("name", "")).strip()
    description = str(body.get("description", "")).strip()
    return {
        "code": code,
        "name": name or code,
        "description": description,
    }


def _load_dashboard() -> dict[str, Any]:
    tasks = _load_tasks()
    projects = _load_projects()

    active_tasks = [task for task in tasks if task.get("status") == "active"]
    done_tasks = [task for task in tasks if task.get("status") == "done"]

    return {
        "stats": {
            "projects": len(projects),
            "tasks": len(tasks),
            "active": len(active_tasks),
            "done": len(done_tasks),
        },
        "active_tasks": active_tasks[:8],
        "projects": sorted(projects, key=lambda item: (-item.get("task_count", 0), item.get("name", "")))[:8],
    }


def _get_task_detail(task_key: str) -> dict | None:
    """Загрузить деталку задачи: метаданные + история фаз (линейно, без FORK/JOIN)."""
    wdb = _get_db()
    task = wdb.get_task_by_key(task_key)
    if not task:
        return None

    task = dict(task)
    task["project_code"] = task.get("project_code") or "—"
    task["project_name"] = task.get("project_name") or task["project_code"]
    task["project_label"] = (
        task["project_name"] if task["project_name"] == task["project_code"]
        else f"{task['project_code']} — {task['project_name']}"
    )

    current_phase_id, current_phase = _resolve_task_phase(task.get("current_phase", "-1"), wdb)
    task["current_phase_name"] = current_phase["name"] if current_phase else task.get("current_phase", "")
    task["current_phase_order"] = current_phase["phase_order"] if current_phase else 0

    task["status_label"] = {"active": "В работе", "done": "Завершена", "blocked": "Заблокирована"}.get(task.get("status", ""), "—")
    task["status_class"] = {"active": "active", "done": "done", "blocked": "blocked"}.get(task.get("status", ""), "wait")

    history = wdb.get_task_history(task["id"])
    phase_history = []
    for h in history:
        phase = wdb.get_phase(h["phase_id"])
        if not phase:
            continue
        history_status = h.get("status", "pending")
        phase_history.append(
            {
                "phase_order": phase["phase_order"],
                "phase_name": phase["name"],
                "phase_description": phase.get("description", ""),
                "status": "done" if history_status == "done" else ("current" if current_phase and phase["id"] == current_phase["id"] else "wait"),
                "completed_at": h.get("completed_at", ""),
            }
        )

    task["phase_history"] = phase_history
    task["completed"] = sum(1 for h in phase_history if h.get("status") == "done")
    task["total_phases"] = len(config.PHASE_ORDER)
    task["progress_done"] = task["completed"]
    task["progress_total"] = task["total_phases"]
    task["work_time"] = None

    return task


# ═══════════════════════════════════════════════════════════════════════
#  ROUTES — Pages
# ═══════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Минимальный dashboard без заглушек."""
    dashboard = _load_dashboard()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "request": request,
            "page": "dashboard",
            "ui_port": config.UI_PORT,
            **dashboard,
        },
    )


@app.get("/phases", response_class=HTMLResponse)
def phases_page(request: Request, workflow_id: int | None = Query(default=None)):
    workflows = _load_workflows()
    selected_workflow = next((item for item in workflows if item["id"] == workflow_id), None)
    if selected_workflow is None and workflows:
        selected_workflow = workflows[0]
    selected_workflow_id = selected_workflow["id"] if selected_workflow else None
    phases = _load_phases(selected_workflow_id)
    phase_blocks = _build_parallel_phase_blocks(phases)
    return templates.TemplateResponse(
        request=request, name="phases.html",
        context={
            "request": request,
            "phases": phases,
            "phase_blocks": phase_blocks,
            "workflows": workflows,
            "selected_workflow": selected_workflow,
            "selected_workflow_id": selected_workflow_id,
            "page": "phases",
            "ui_port": config.UI_PORT,
        }
    )


@app.get("/phase/{phase_id}", response_class=HTMLResponse)
def phase_detail(request: Request, phase_id: str):
    phase = _load_phase_detail(phase_id)
    if not phase:
        return HTMLResponse("<h1>Phase not found</h1>", status_code=404)
    wdb = _get_db()
    agents = wdb.get_agents()
    return templates.TemplateResponse(
        request=request, name="phase_detail.html", context={
            "request": request, "page": "phases", "ui_port": config.UI_PORT, "phase": phase,
            "agents": agents,
        }
    )



@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    """Список задач workflow."""
    tasks = _load_tasks()
    return templates.TemplateResponse(
        request=request,
        name="tasks.html",
        context={
            "request": request,
            "tasks": tasks,
            "page": "tasks",
            "ui_port": config.UI_PORT,
        },
    )


@app.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request):
    """CRUD-страница проектов и их regex-правил."""
    projects = _load_projects()
    workflows = _load_workflows()
    return templates.TemplateResponse(
        request=request,
        name="projects.html",
        context={
            "request": request,
            "page": "projects",
            "ui_port": config.UI_PORT,
            "projects": projects,
            "workflows": workflows,
            "selected_project": projects[0] if projects else None,
        },
    )


@app.get("/workflows", response_class=HTMLResponse)
def workflows_page(request: Request):
    workflows = _load_workflows()
    return templates.TemplateResponse(
        request=request,
        name="workflows.html",
        context={
            "request": request,
            "page": "workflows",
            "ui_port": config.UI_PORT,
            "workflows": workflows,
            "selected_workflow": workflows[0] if workflows else None,
        },
    )


@app.get("/task/{task_key}", response_class=HTMLResponse)
def task_detail_page(request: Request, task_key: str):
    """Деталка задачи — линейная история фаз."""
    task = _get_task_detail(task_key)
    if not task:
        return HTMLResponse("<h1>Task not found</h1>", status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="task_detail.html",
        context={
            "request": request,
            "task": task,
            "page": "tasks",
            "ui_port": config.UI_PORT,
            "current_phase_name": task.get("current_phase_name"),
            "progress_done": task.get("progress_done", 0),
            "progress_total": task.get("progress_total", 0),
            "work_time": task.get("work_time"),
            "phase_history": task.get("phase_history", []),
        },
    )


# ── Settings ─────────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    """Read-only справка по реальным CLI-командам workflow."""
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "request": request,
            "page": "settings",
            "ui_port": config.UI_PORT,
            "commands": _load_cli_reference(),
        },
    )


@app.get("/api/settings")
def api_settings_get():
    """Вернуть реестр CLI-команд для UI/интеграций."""
    return {"ok": True, "commands": _load_cli_reference()}


@app.get("/agents", response_class=HTMLResponse)
def agents_page(request: Request):
    """Список агентов."""
    wdb = _get_db()
    agents = wdb.get_agents()
    return templates.TemplateResponse(
        request=request, name="agents.html",
        context={"request": request, "agents": agents, "page": "agents", "ui_port": config.UI_PORT}
    )


# ═══════════════════════════════════════════════════════════════════════
#  API
# ═══════════════════════════════════════════════════════════════════════

@app.get("/api/phases")
def api_phases(workflow_id: int | None = Query(default=None)):
    workflows = _load_workflows()
    selected_workflow = next((item for item in workflows if item["id"] == workflow_id), None)
    if selected_workflow is None and workflow_id is None and workflows:
        selected_workflow = workflows[0]
    return {"ok": True, "workflow": selected_workflow, "phases": _load_phases(workflow_id)}


@app.get("/api/phases/{phase_id}")
def api_phase_detail(phase_id: str):
    phase = _load_phase_detail(phase_id)
    if not phase:
        return JSONResponse({"ok": False, "error": "Phase not found"}, status_code=404)
    return {"ok": True, "phase": phase}


@app.get("/api/tasks")
def api_tasks():
    """Все задачи."""
    return {"ok": True, "tasks": _load_tasks()}


@app.get("/api/workflows")
def api_workflows():
    return {"ok": True, "workflows": _load_workflows()}


@app.post("/api/workflows")
def api_workflow_create(body: dict[str, Any]):
    payload = _workflow_form_payload(body)
    if not payload["code"]:
        return JSONResponse({"ok": False, "error": "code required"}, status_code=400)
    wdb = _get_db()
    if wdb.get_workflow_by_code(payload["code"]):
        return JSONResponse({"ok": False, "error": "Workflow already exists"}, status_code=409)
    try:
        workflow_id = wdb.create_workflow(payload)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True, "workflow_id": workflow_id}


@app.put("/api/workflows/{workflow_id}")
def api_workflow_update(workflow_id: int, body: dict[str, Any]):
    wdb = _get_db()
    existing = wdb.get_workflow(workflow_id)
    if not existing:
        return JSONResponse({"ok": False, "error": "Workflow not found"}, status_code=404)

    update_data: dict[str, Any] = {}
    if "code" in body:
        code = str(body.get("code", "")).strip()
        if not code:
            return JSONResponse({"ok": False, "error": "code required"}, status_code=400)
        conflict = wdb.get_workflow_by_code(code)
        if conflict and conflict["id"] != workflow_id:
            return JSONResponse({"ok": False, "error": "Workflow code already exists"}, status_code=409)
        update_data["code"] = code
    if "name" in body:
        update_data["name"] = str(body.get("name", "")).strip() or update_data.get("code") or existing["name"]
    if "description" in body:
        update_data["description"] = str(body.get("description", "")).strip()

    if update_data:
        wdb.update_workflow(workflow_id, update_data)
    return {"ok": True}


@app.delete("/api/workflows/{workflow_id}")
def api_workflow_delete(workflow_id: int):
    wdb = _get_db()
    existing = wdb.get_workflow(workflow_id)
    if not existing:
        return JSONResponse({"ok": False, "error": "Workflow not found"}, status_code=404)
    try:
        wdb.delete_workflow(workflow_id)
    except sqlite3.IntegrityError:
        return JSONResponse({"ok": False, "error": "Workflow has linked projects or phases and cannot be deleted"}, status_code=409)
    return {"ok": True}


@app.get("/api/projects")
def api_projects():
    return {"ok": True, "projects": _load_projects()}


@app.post("/api/projects")
def api_project_create(body: dict[str, Any]):
    payload = _project_form_payload(body)
    if not payload["code"]:
        return JSONResponse({"ok": False, "error": "code required"}, status_code=400)
    wdb = _get_db()
    if wdb.get_project_by_code(payload["code"]):
        return JSONResponse({"ok": False, "error": "Project already exists"}, status_code=409)
    try:
        project_id = wdb.create_project(payload)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True, "project_id": project_id}


@app.put("/api/projects/{project_id}")
def api_project_update(project_id: int, body: dict[str, Any]):
    wdb = _get_db()
    existing = wdb.get_project(project_id)
    if not existing:
        return JSONResponse({"ok": False, "error": "Project not found"}, status_code=404)

    update_data: dict[str, Any] = {}
    if "code" in body:
        code = str(body.get("code", "")).strip()
        if not code:
            return JSONResponse({"ok": False, "error": "code required"}, status_code=400)
        conflict = wdb.get_project_by_code(code)
        if conflict and conflict["id"] != project_id:
            return JSONResponse({"ok": False, "error": "Project code already exists"}, status_code=409)
        update_data["code"] = code
    if "name" in body:
        update_data["name"] = str(body.get("name", "")).strip() or update_data.get("code") or existing["name"]
    if "key_patterns" in body:
        update_data["key_patterns"] = _parse_key_patterns(body.get("key_patterns", []))

    if update_data:
        wdb.update_project(project_id, update_data)
    return {"ok": True}


@app.delete("/api/projects/{project_id}")
def api_project_delete(project_id: int):
    wdb = _get_db()
    existing = wdb.get_project(project_id)
    if not existing:
        return JSONResponse({"ok": False, "error": "Project not found"}, status_code=404)
    try:
        wdb.delete_project(project_id)
    except sqlite3.IntegrityError:
        return JSONResponse({"ok": False, "error": "Project has linked tasks and cannot be deleted"}, status_code=409)
    return {"ok": True}


@app.get("/api/agents")
def api_agents():
    """Получить всех агентов."""
    wdb = _get_db()
    agents = wdb.get_agents()
    return {"ok": True, "agents": agents}


@app.post("/api/agents")
def api_agent_create(body: dict[str, Any]):
    """Создать агента."""
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "name required"}, status_code=400)
    wdb = _get_db()
    agent_id = wdb.create_agent({
        "name": name,
        "description": str(body.get("description", "")).strip(),
    })
    return {"ok": True, "agent_id": agent_id}


@app.put("/api/agents/{agent_id}")
def api_agent_update(agent_id: int, body: dict[str, Any]):
    """Обновить агента."""
    wdb = _get_db()
    existing = wdb.get_agent(agent_id)
    if not existing:
        return JSONResponse({"ok": False, "error": "Agent not found"}, status_code=404)
    update_data = {}
    if "name" in body:
        update_data["name"] = str(body["name"]).strip()
    if "description" in body:
        update_data["description"] = str(body["description"]).strip()
    if update_data:
        wdb.update_agent(agent_id, update_data)
    return {"ok": True}


@app.delete("/api/agents/{agent_id}")
def api_agent_delete(agent_id: int):
    """Удалить агента."""
    wdb = _get_db()
    existing = wdb.get_agent(agent_id)
    if not existing:
        return JSONResponse({"ok": False, "error": "Agent not found"}, status_code=404)
    wdb.delete_agent(agent_id)
    return {"ok": True}


@app.put("/api/phases/order")
def api_update_order(body: dict[str, Any]):
    """Batch update phase_order после drag-and-drop на Kanban.

    Body: {"orders": [{"phase_id": "4", "phase_order": 8}, ...]}
    """
    orders = body.get("orders", [])
    if not orders:
        return JSONResponse({"ok": False, "error": "No orders provided"}, status_code=400)

    wdb = _get_db()
    batch: list[tuple[int, int]] = []
    for item in orders:
        resolved_phase_id = _coerce_phase_db_id(item.get("phase_id"))
        if resolved_phase_id is None:
            return JSONResponse({"ok": False, "error": "Invalid phase_id in orders"}, status_code=400)
        batch.append((resolved_phase_id, int(item["phase_order"])))
    wdb.batch_update_orders(batch)

    # Rebuild PHASE_ORDER in config (volatile for this process)
    _update_config_phase_order()

    return {"ok": True, "updated": len(batch)}


@app.put("/api/phases/{phase_id}")
def api_phase_update(phase_id: str, body: dict[str, Any]):
    srv = _get_service()
    resolved_phase_id = _coerce_phase_db_id(phase_id)
    if resolved_phase_id is None or not srv.get_phase_detail(resolved_phase_id):
        return JSONResponse({"ok": False, "error": "Phase not found"}, status_code=404)

    forbidden_fields = [field for field in ("code", "phase_num", "phase_order") if field in body]
    if forbidden_fields:
        fields = ", ".join(forbidden_fields)
        return JSONResponse(
            {
                "ok": False,
                "error": f"{fields} cannot be updated from phase detail; manage phase identity/order on /phases",
            },
            status_code=400,
        )

    # Phase metadata
    PHASE_FIELDS = {
        "name", "description",
        "delegate_agent", "delegate_timeout", "parallel_with", "rollback_target", "next_recommendation",
        "agent_id", "execution_type",
    }
    phase_data = {k: v for k, v in body.items() if k in PHASE_FIELDS}
    if phase_data:
        srv.update_phase(resolved_phase_id, phase_data)

    # Bulk replace instructions / checks / evidence only when explicitly provided
    inst_ids: list[int] = []
    check_ids: list[int] = []
    ev_ids: list[int] = []
    if "instructions" in body:
        inst_ids = srv.save_instructions(resolved_phase_id, body.get("instructions", []))
    if "checks" in body:
        check_ids = srv.save_checks(resolved_phase_id, body.get("checks", []))
    if "evidence" in body:
        ev_ids = srv.save_evidence(resolved_phase_id, body.get("evidence", []))

    schema.persist_phase_update_to_seed(srv._db, resolved_phase_id, body)

    return {"ok": True, "ids": {"instructions": inst_ids, "checks": check_ids, "evidence": ev_ids}}


def _update_config_phase_order():
    """Пересобрать PHASE_ORDER из актуального DB state."""
    phases = _load_phases()
    sorted_phases = sorted(phases, key=lambda p: p["phase_num"])
    config.PHASE_ORDER[:] = [p["code"] for p in sorted_phases]


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