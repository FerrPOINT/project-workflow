"""HTML page routes for the workflow UI."""

from __future__ import annotations

from fastapi import Query, Request
from fastapi.responses import HTMLResponse

from project_workflow import config
from project_workflow.infrastructure.db.legacy import PhaseService
from project_workflow.interfaces.ui.services import (
    _build_parallel_phase_blocks,
    _get_task_detail,
    _load_cli_reference,
    _load_dashboard,
    _load_phase_detail,
    _load_phases,
    _load_projects,
    _load_tasks,
    _load_workflows,
)
from project_workflow.interfaces.ui.skills import _load_skills_catalog as _load_skills_catalog_direct
from project_workflow.interfaces.ui.state import _app_state
from project_workflow.interfaces.ui.templates import templates


async def index(request: Request) -> HTMLResponse:
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


async def phases_page(
    request: Request, workflow_id: int | None = Query(default=None)
) -> HTMLResponse:
    workflows = _load_workflows()
    selected_workflow = next((item for item in workflows if item["id"] == workflow_id), None)
    if selected_workflow is None and workflows:
        selected_workflow = workflows[0]
    selected_workflow_id = selected_workflow["id"] if selected_workflow else None
    phases = _load_phases(selected_workflow_id)
    phase_blocks = _build_parallel_phase_blocks(phases)
    return templates.TemplateResponse(
        request=request,
        name="phases.html",
        context={
            "request": request,
            "phases": phases,
            "phase_blocks": phase_blocks,
            "phase_count": len(phases),
            "workflows": workflows,
            "selected_workflow": selected_workflow,
            "selected_workflow_id": selected_workflow_id,
            "page": "phases",
            "ui_port": config.UI_PORT,
        },
    )


async def phase_detail(request: Request, phase_id: str) -> HTMLResponse:
    phase = _load_phase_detail(phase_id)
    if not phase:
        return HTMLResponse("<h1>Phase not found</h1>", status_code=404)
    wdb = _app_state.get_db()
    agents = wdb.get_agents()
    skills_catalog = _load_skills_catalog_direct()
    for instruction in phase.get("instructions", []):
        selected_skills = PhaseService.normalize_skills(instruction.get("skills"))
        instruction["skills"] = selected_skills
        selected_names = set(selected_skills)
        instruction["available_skills"] = [
            dict(skill)
            for skill in skills_catalog
            if str(skill.get("name") or "") not in selected_names
        ]
    return templates.TemplateResponse(
        request=request,
        name="phase_detail.html",
        context={
            "request": request,
            "page": "phases",
            "ui_port": config.UI_PORT,
            "phase": phase,
            "agents": agents,
            "skills_catalog": skills_catalog,
        },
    )


async def tasks_page(request: Request) -> HTMLResponse:
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


async def projects_page(request: Request) -> HTMLResponse:
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


async def workflows_page(request: Request) -> HTMLResponse:
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


async def task_detail_page(request: Request, task_key: str) -> HTMLResponse:
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
            "phase_history_blocks": task.get("phase_history_blocks", []),
            "supervisor_runs": task.get("supervisor_runs", []),
        },
    )


async def settings_page(request: Request) -> HTMLResponse:
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


async def skills_page(request: Request, refresh: int = Query(default=0)) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="skills.html",
        context={
            "request": request,
            "page": "skills",
            "ui_port": config.UI_PORT,
            "skills": _load_skills_catalog_direct(refresh=bool(refresh)),
        },
    )


async def agents_page(request: Request) -> HTMLResponse:
    """Список агентов."""
    wdb = _app_state.get_db()
    agents = wdb.get_agents()
    return templates.TemplateResponse(
        request=request,
        name="agents.html",
        context={
            "request": request,
            "agents": agents,
            "page": "agents",
            "ui_port": config.UI_PORT,
        },
    )
