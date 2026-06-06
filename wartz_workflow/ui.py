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
from fastapi import FastAPI, Request
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
    "-1": "setup", "0.0a": "setup", "0.01": "setup", "0.00": "setup", "0.000": "setup", "0.7": "setup",
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
    agents_by_id = {agent["id"]: agent for agent in wdb.get_agents()}
    result = []
    for p in rows:
        delegate_agent = p.get("delegate_agent")
        selected_agent = agents_by_id.get(p.get("agent_id")) if p.get("agent_id") else None
        result.append(
            {
                "id": p["id"],
                "code": p["code"],
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
    return {
        "code": code,
        "name": name or code,
        "key_patterns": _parse_key_patterns(body.get("key_patterns", [])),
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
def phases_page(request: Request):
    phases = _load_phases()
    phase_blocks = _build_parallel_phase_blocks(phases)
    return templates.TemplateResponse(
        request=request, name="phases.html",
        context={
            "request": request,
            "phases": phases,
            "phase_blocks": phase_blocks,
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
    groups = wdb.get_phase_groups()
    agents = wdb.get_agents()
    return templates.TemplateResponse(
        request=request, name="phase_detail.html", context={
            "request": request, "page": "phases", "ui_port": config.UI_PORT, "phase": phase,
            "groups": groups, "agents": agents,
        }
    )



@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    """Список задач workflow."""
    tasks = _load_tasks()
    page_num = 1
    per_page = 20
    filter_status = ""
    search = ""
    total_count = len(tasks)
    active_count = sum(1 for t in tasks if t.get("status") == "active")
    done_count = sum(1 for t in tasks if t.get("status") == "done")
    total_pages = max(1, (len(tasks) + per_page - 1) // per_page) if tasks else 1
    return templates.TemplateResponse(
        request=request, name="tasks.html",
        context={
            "request": request, "tasks": tasks, "page": "tasks", "ui_port": config.UI_PORT,
            "page_num": page_num, "total_pages": total_pages, "filter_status": filter_status,
            "search": search, "per_page": per_page,
            "total_count": total_count, "active_count": active_count, "done_count": done_count,
        }
    )


@app.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request):
    """CRUD-страница проектов и их regex-правил."""
    projects = _load_projects()
    return templates.TemplateResponse(
        request=request,
        name="projects.html",
        context={
            "request": request,
            "page": "projects",
            "ui_port": config.UI_PORT,
            "projects": projects,
            "selected_project": projects[0] if projects else None,
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


@app.post("/api/wizard/{phase_id}")
def api_wizard_submit(phase_id: str, body: dict[str, Any]):
    """Проверка ответов wizard: возвращает PASS/FAIL."""
    wdb = _get_db()
    
    # Load phase questions from DB only
    questions = wdb.get_questions(phase_id)

    # Get answers from body
    user_answers = body.get("answers", {})
    checks = body.get("checks", {})
    
    covered = []
    missing = []
    
    # Check questions
    for q in questions:
        qid = f"q_{q['id']}"
        answer = user_answers.get(qid, "").strip()

        if q.get("required") and not answer:
            missing.append(q["qtext"])
            continue

        # Check keywords
        import json
        keywords = json.loads(q.get("expected_keywords", "[]")) if q.get("expected_keywords") else []
        if keywords and answer:
            ans_lower = answer.lower()
            matched = any(k.lower() in ans_lower for k in keywords)
            if not matched and q.get("required"):
                missing.append(f"{q['qtext']} (keywords: {', '.join(keywords)})")
            elif matched:
                covered.append(q["qtext"])
        elif answer:
            covered.append(q["qtext"])
    
    # Check checklist items
    checklist_items = body.get("checklist", {})
    for key, checked in checklist_items.items():
        if not checked:
            missing.append(f"Чеклист: пункт {key}")
    
    # Evaluate verdict
    if not missing:
        from . import phases as phases_mod
        next_phase = phases_mod.get_next_phase(phase_id)
        next_phase_row = wdb.get_phase(next_phase) if next_phase else None
        next_name = next_phase_row["name"] if next_phase_row else None

        return {
            "verdict": "PASS",
            "phase": phase_id,
            "covered": covered,
            "missing": [],
            "message": f"Фаза {phase_id} пройдена. Переходим к {next_phase} — {next_name}" if next_phase else "Все фазы выполнены!",
            "next_phase": next_phase,
            "next_phase_name": next_name,
        }
    else:
        return {
            "verdict": "FAIL",
            "phase": phase_id,
            "covered": covered,
            "missing": missing,
            "message": f"Не выполнено {len(missing)} пунктов. Доработай и пришли новый отчёт.",
            "next_phase": None,
            "next_phase_name": None,
        }

@app.get("/api/wizard/{task_key}/context")
def api_wizard_context(task_key: str):
    """Полный контекст для агента-визарда."""
    from . import wizard as wizard_mod
    engine = wizard_mod.WizardEngine(task_key)
    return engine.get_full_context()


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


# ── Groups ─────────────────────────────────────────────────────────────

@app.get("/groups", response_class=HTMLResponse)
def groups_page(request: Request):
    """Список групп фаз."""
    wdb = _get_db()
    groups = wdb.get_phase_groups()
    return templates.TemplateResponse(
        request=request, name="groups.html",
        context={"request": request, "groups": groups, "page": "groups", "ui_port": config.UI_PORT}
    )


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
def api_phases():
    return {"ok": True, "phases": _load_phases()}


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


@app.get("/api/tasks/{task_key}")
def api_task_detail(task_key: str):
    """Детали одной задачи."""
    task = _get_task_detail(task_key)
    if not task:
        return JSONResponse({"ok": False, "error": "Task not found"}, status_code=404)
    return {"ok": True, "task": task}


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


@app.get("/api/groups")
def api_groups():
    """Получить все группы фаз."""
    wdb = _get_db()
    wdb.seed_default_groups()
    groups = wdb.get_phase_groups()
    return {"ok": True, "groups": groups}


@app.post("/api/groups")
def api_group_create(body: dict[str, Any]):
    """Создать группу фаз."""
    group_id = body.get("id", "").strip().lower()
    name = body.get("name", "").strip()
    if not group_id or not name:
        return JSONResponse({"ok": False, "error": "id and name required"}, status_code=400)
    wdb = _get_db()
    existing = wdb.get_phase_group_by_code(group_id)
    if existing:
        return JSONResponse({"ok": False, "error": f"Group {group_id} already exists"}, status_code=409)
    try:
        wdb.create_phase_group({
            "id": group_id, "name": name, "icon": body.get("icon"),
            "sort_order": body.get("sort_order", 0),
        })
    except sqlite3.IntegrityError:
        return JSONResponse({"ok": False, "error": f"Group {group_id} already exists"}, status_code=409)
    return {"ok": True, "group_id": group_id}


@app.put("/api/groups/order")
def api_groups_order(body: dict[str, Any]):
    """Обновить порядок групп (DND колонок)."""
    orders = body.get("orders", [])
    if not orders:
        return JSONResponse({"ok": False, "error": "No orders provided"}, status_code=400)
    wdb = _get_db()
    batch = [(o["group_id"], o["sort_order"]) for o in orders]
    wdb.batch_update_group_orders(batch)
    return {"ok": True, "updated": len(batch)}


@app.put("/api/groups/{group_id}")
def api_group_update(group_id: str, body: dict[str, Any]):
    """Обновить группу."""
    wdb = _get_db()
    existing = wdb.get_phase_group_by_code(group_id)
    if not existing:
        return JSONResponse({"ok": False, "error": "Group not found"}, status_code=404)
    update_data = {}
    if "name" in body: update_data["name"] = body["name"]
    if "icon" in body: update_data["icon"] = body["icon"]
    if "sort_order" in body: update_data["sort_order"] = body["sort_order"]
    if update_data:
        wdb.update_phase_group(group_id, update_data)
    return {"ok": True}


@app.delete("/api/groups/{group_id}")
def api_group_delete(group_id: str):
    """Удалить группу. Фазы переходят в setup."""
    wdb = _get_db()
    existing = wdb.get_phase_group_by_code(group_id)
    if not existing:
        return JSONResponse({"ok": False, "error": "Group not found"}, status_code=404)
    try:
        wdb.delete_phase_group(group_id)
    except sqlite3.IntegrityError:
        return JSONResponse({"ok": False, "error": "Group has linked phases and cannot be deleted"}, status_code=409)
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


@app.put("/api/phases/{phase_id}/group")
def api_phase_group_assign(phase_id: str, body: dict[str, Any]):
    """Назначить фазу в группу."""
    group_id = body.get("group_id")
    if not group_id:
        return JSONResponse({"ok": False, "error": "group_id required"}, status_code=400)
    wdb = _get_db()
    resolved_phase_id = _coerce_phase_db_id(phase_id)
    if resolved_phase_id is None or not wdb.get_phase(resolved_phase_id):
        return JSONResponse({"ok": False, "error": "Phase not found"}, status_code=404)
    if not wdb.get_phase_group_by_code(group_id):
        return JSONResponse({"ok": False, "error": "Group not found"}, status_code=404)
    wdb.update_phase_group_assignment(resolved_phase_id, group_id)
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


@app.put("/api/phases/parallel")
def api_update_parallel(body: dict[str, Any]):
    """Batch update parallel_with связей после drag в графе.

    Body: {"groups": [["4.5", "5"], ["7.5", "7.6"]], "clear": ["3.5"]}
    """
    groups = body.get("groups", [])
    clear = body.get("clear", [])

    wdb = _get_db()

    # Collect ALL phase IDs that will be in new groups → must have old links wiped
    all_group_ids = set()
    for group in groups:
        if len(group) >= 2:
            all_group_ids.update(group)

    # Clear old parallel links for anyone entering a new group or explicitly cleared
    to_clear = all_group_ids | set(clear)
    for phase_id in to_clear:
        wdb.update_phase_parallel(phase_id, None)

    # Set new bidirectional links (cycle for groups >=2)
    group_map: dict[str, str] = {}
    for group in groups:
        if len(group) >= 2:
            for i, phase_id in enumerate(group):
                target = group[(i + 1) % len(group)]
                group_map[phase_id] = target

    if group_map:
        wdb.batch_update_groups(group_map)

    return {"ok": True, "groups_set": len(group_map), "cleared": len(to_clear)}


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
        "group_id", "agent_id", "execution_type",
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


@app.put("/api/phases/{phase_id}/order")
def api_single_phase_order(phase_id: str, body: dict[str, Any]):
    """Обновить порядок одной фазы (перетаскивание в графе)."""
    new_order = body.get("phase_order")
    if new_order is None:
        return JSONResponse({"ok": False, "error": "phase_order required"}, status_code=400)

    wdb = _get_db()
    resolved_phase_id = _coerce_phase_db_id(phase_id)
    if resolved_phase_id is None or not wdb.get_phase(resolved_phase_id):
        return JSONResponse({"ok": False, "error": "Phase not found"}, status_code=404)
    new_order = int(new_order)
    wdb.update_phase_order(resolved_phase_id, new_order)

    # Rebuild config order
    _update_config_phase_order()

    return {"ok": True, "phase_id": resolved_phase_id, "phase_order": new_order}


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