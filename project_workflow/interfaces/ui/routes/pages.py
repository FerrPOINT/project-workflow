"""HTML page routes for the workflow UI."""

from __future__ import annotations

from typing import Any

from fastapi import Query, Request
from fastapi.responses import HTMLResponse

from project_workflow.application.phase_service import PhaseService
from project_workflow.config import get_settings
from project_workflow.domain.exceptions import ConflictError
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
from project_workflow.interfaces.ui.state import _app_state
from project_workflow.interfaces.ui.templates import _group_instructions, templates


def _theme_context(project: dict[str, Any] | None) -> dict[str, Any]:
    return {"theme_project": project}


def _error_page(
    request: Request,
    *,
    title: str,
    message: str,
    status_code: int,
    back_url: str,
    back_label: str,
    page: str,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        status_code=status_code,
        context={
            "request": request,
            "title": title,
            "message": message,
            "status_code": status_code,
            "back_url": back_url,
            "back_label": back_label,
            "page": page,
            "ui_port": get_settings().UI_PORT,
        },
    )


async def index(request: Request) -> HTMLResponse:
    """Минимальный dashboard без заглушек."""
    dashboard = _load_dashboard()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "request": request,
            "page": "dashboard",
            "ui_port": get_settings().UI_PORT,
            **_theme_context(None),
            **dashboard,
        },
    )


async def phases_page(request: Request, workflow_id: int | None = Query(default=None)) -> HTMLResponse:
    workflows = _load_workflows()
    selected_workflow = next((item for item in workflows if item["id"] == workflow_id), None)
    if selected_workflow is None and workflows:
        selected_workflow = workflows[0]
    selected_workflow_id = selected_workflow["id"] if selected_workflow else None
    phases = _load_phases(int(selected_workflow_id)) if selected_workflow_id is not None else []
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
            "ui_port": get_settings().UI_PORT,
            **_theme_context(None),
        },
    )


async def phase_detail(request: Request, phase_id: int) -> HTMLResponse:
    phase = _load_phase_detail(phase_id)
    if not phase:
        return _error_page(
            request,
            title="Фаза не найдена",
            message="Проверьте выбранный воркфлоу или вернитесь к каталогу фаз.",
            status_code=404,
            back_url="/phases",
            back_label="К фазам",
            page="phases",
        )
    agents = _app_state.agent_service().list_agents()
    workflow_phases = _app_state.phase_service().list_phases(phase.get("workflow_id"))
    current_index = next(
        (index for index, item in enumerate(workflow_phases) if item.get("id") == phase.get("id")),
        None,
    )
    parallel_candidates = []
    rollback_target_phase = next(
        (
            item
            for item in workflow_phases
            if item.get("id") == phase.get("rollback_target_phase_id")
        ),
        None,
    )
    if current_index is not None:
        left = current_index - 1
        right = current_index + 1
        while left >= 0 and workflow_phases[left].get("execution_type") == "parallel":
            left -= 1
        while right < len(workflow_phases) and workflow_phases[right].get("execution_type") == "parallel":
            right += 1
        parallel_candidates = [
            item
            for index, item in enumerate(workflow_phases)
            if left < index < right
            and index != current_index
            and item.get("execution_type") == "parallel"
        ]
    for instruction in phase.get("instructions", []):
        instruction["skills"] = PhaseService.normalize_skills(instruction.get("skills"))
    return templates.TemplateResponse(
        request=request,
        name="phase_detail.html",
        context={
            "request": request,
            "page": "phases",
            "ui_port": get_settings().UI_PORT,
            "phase": phase,
            "agents": agents,
            "workflow_phases": workflow_phases,
            "parallel_candidates": parallel_candidates,
            "rollback_target_phase": rollback_target_phase,
            **_theme_context(None),
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
            "ui_port": get_settings().UI_PORT,
            **_theme_context(None),
        },
    )


async def projects_page(request: Request) -> HTMLResponse:
    """CRUD page for workflow contexts and their task key prefixes."""
    projects = _load_projects()
    workflows = _load_workflows()
    return templates.TemplateResponse(
        request=request,
        name="projects.html",
        context={
            "request": request,
            "page": "contexts",
            "ui_port": get_settings().UI_PORT,
            "projects": projects,
            "workflows": workflows,
            "selected_project": projects[0] if projects else None,
            **_theme_context(projects[0] if projects else None),
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
            "ui_port": get_settings().UI_PORT,
            "workflows": workflows,
            "selected_workflow": workflows[0] if workflows else None,
            **_theme_context(None),
        },
    )


async def task_detail_page(
    request: Request,
    task_key: str,
    context_id: int | None = Query(default=None),
    project_id: int | None = Query(default=None, include_in_schema=False),
) -> HTMLResponse:
    """Деталка задачи — линейная история фаз."""
    selected_context_id = context_id if context_id is not None else project_id
    try:
        task = _get_task_detail(task_key, project_id=selected_context_id)
    except ConflictError as exc:
        return _error_page(
            request,
            title="Задача неоднозначна",
            message=str(exc),
            status_code=409,
            back_url="/tasks",
            back_label="К списку задач",
            page="tasks",
        )
    if not task:
        return _error_page(
            request,
            title="Задача не найдена",
            message=f"Задачи {task_key} нет в текущем каталоге.",
            status_code=404,
            back_url="/tasks",
            back_label="К списку задач",
            page="tasks",
        )
    return templates.TemplateResponse(
        request=request,
        name="task_detail.html",
        context={
            "request": request,
            "task": task,
            "page": "tasks",
            "ui_port": get_settings().UI_PORT,
            "current_phase_name": task.get("current_phase_name"),
            "progress_done": task.get("progress_done", 0),
            "progress_total": task.get("progress_total", 0),
            "cycles_done": task.get("completed_cycles", 0),
            "cycles_total": task.get("workflow_cycle_count", 0),
            "phase_history_blocks": task.get("phase_history_blocks", []),
            "step_history": task.get("step_history", []),
            **_theme_context(task.get("project")),
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
            "ui_port": get_settings().UI_PORT,
            "commands": _load_cli_reference(),
            **_theme_context(None),
        },
    )


async def agents_page(request: Request) -> HTMLResponse:
    """Список агентов."""
    agents = _app_state.agent_service().list_agents()
    return templates.TemplateResponse(
        request=request,
        name="agents.html",
        context={
            "request": request,
            "agents": agents,
            "page": "agents",
            "ui_port": get_settings().UI_PORT,
            **_theme_context(None),
        },
    )


async def instructions_page(
    request: Request,
    phase_id: int | None = Query(default=None),
) -> HTMLResponse:
    """Dedicated instructions editor page for a phase."""
    if phase_id is None:
        return _error_page(
            request,
            title="Фаза не выбрана",
            message="Откройте инструкции из карточки нужной фазы.",
            status_code=400,
            back_url="/phases",
            back_label="К фазам",
            page="phases",
        )
    phase = _load_phase_detail(phase_id)
    if not phase:
        return _error_page(
            request,
            title="Фаза не найдена",
            message="Инструкции для указанной фазы недоступны.",
            status_code=404,
            back_url="/phases",
            back_label="К фазам",
            page="phases",
        )
    instructions = phase.get("instructions", [])
    for instruction in instructions:
        instruction["skills"] = PhaseService.normalize_skills(instruction.get("skills"))
    instruction_groups = _group_instructions(instructions)
    return templates.TemplateResponse(
        request=request,
        name="instructions.html",
        context={
            "request": request,
            "page": "phases",
            "ui_port": get_settings().UI_PORT,
            "phase": phase,
            "instructions": instructions,
            "instruction_groups": instruction_groups,
            **_theme_context(None),
        },
    )
