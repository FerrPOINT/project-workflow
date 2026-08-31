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
    _load_namespaces,
    _load_phase_detail,
    _load_phases,
    _load_tasks,
    _load_workflows,
)
from project_workflow.interfaces.ui.state import _app_state
from project_workflow.interfaces.ui.templates import _group_instructions, templates

NAMESPACE_COOKIE = "workflow_namespace_id"


def _theme_context(namespace: dict[str, Any] | None) -> dict[str, Any]:
    return {"theme_namespace": namespace, "theme_project": namespace}


def _parse_positive_int(raw: str | None) -> int | None:
    if raw is None or not raw.strip().isdecimal():
        return None
    value = int(raw.strip())
    return value if value > 0 else None


def _namespace_context(
    request: Request,
    *,
    page: str,
    preferred_namespace_id: int | None = None,
) -> dict[str, Any]:
    namespaces = _load_namespaces()
    query_namespace_id = _parse_positive_int(request.query_params.get("namespace_id"))
    cookie_namespace_id = _parse_positive_int(request.cookies.get(NAMESPACE_COOKIE))
    selected_id = preferred_namespace_id or query_namespace_id or cookie_namespace_id
    selected_namespace = next((item for item in namespaces if item.get("id") == selected_id), None)
    if selected_namespace is None and namespaces:
        selected_namespace = namespaces[0]
    return {
        "request": request,
        "page": page,
        "ui_port": get_settings().UI_PORT,
        "namespaces": namespaces,
        "projects": namespaces,
        "selected_namespace": selected_namespace,
        "selected_project": selected_namespace,
        **_theme_context(selected_namespace),
    }


def _template_response(
    *,
    request: Request,
    name: str,
    context: dict[str, Any],
    status_code: int = 200,
) -> HTMLResponse:
    response = templates.TemplateResponse(
        request=request,
        name=name,
        status_code=status_code,
        context=context,
    )
    selected_namespace = context.get("selected_namespace")
    selected_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
    if isinstance(selected_id, int):
        response.set_cookie(NAMESPACE_COOKIE, str(selected_id), samesite="lax")
    return response


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
    context = _namespace_context(request, page=page)
    context.update(
        {
            "title": title,
            "message": message,
            "status_code": status_code,
            "back_url": back_url,
            "back_label": back_label,
        }
    )
    return _template_response(
        request=request,
        name="error.html",
        status_code=status_code,
        context=context,
    )


async def index(request: Request) -> HTMLResponse:
    """Минимальный dashboard без заглушек."""
    context = _namespace_context(request, page="dashboard")
    selected_namespace = context.get("selected_namespace")
    namespace_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
    dashboard = _load_dashboard(namespace_id=namespace_id if isinstance(namespace_id, int) else None)
    context.update(dashboard)
    return _template_response(
        request=request,
        name="dashboard.html",
        context=context,
    )


async def phases_page(request: Request, workflow_id: int | None = Query(default=None)) -> HTMLResponse:
    context = _namespace_context(request, page="phases")
    selected_namespace = context.get("selected_namespace")
    if workflow_id is None and isinstance(selected_namespace, dict):
        workflow_id = selected_namespace.get("workflow_id")
    workflows = _load_workflows()
    selected_workflow = next((item for item in workflows if item["id"] == workflow_id), None)
    if selected_workflow is None and workflows:
        selected_workflow = workflows[0]
    selected_workflow_id = selected_workflow["id"] if selected_workflow else None
    phases = _load_phases(int(selected_workflow_id)) if selected_workflow_id is not None else []
    phase_blocks = _build_parallel_phase_blocks(phases)
    context.update(
        {
            "phases": phases,
            "phase_blocks": phase_blocks,
            "phase_count": len(phases),
            "workflows": workflows,
            "selected_workflow": selected_workflow,
            "selected_workflow_id": selected_workflow_id,
        }
    )
    return _template_response(
        request=request,
        name="phases.html",
        context=context,
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
    context = _namespace_context(request, page="phases")
    context.update(
        {
            "phase": phase,
            "agents": agents,
            "workflow_phases": workflow_phases,
            "parallel_candidates": parallel_candidates,
            "rollback_target_phase": rollback_target_phase,
        }
    )
    return _template_response(
        request=request,
        name="phase_detail.html",
        context=context,
    )


async def tasks_page(request: Request) -> HTMLResponse:
    """Список задач workflow."""
    context = _namespace_context(request, page="tasks")
    selected_namespace = context.get("selected_namespace")
    namespace_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
    tasks = _load_tasks(namespace_id=namespace_id if isinstance(namespace_id, int) else None)
    context.update({"tasks": tasks})
    return _template_response(
        request=request,
        name="tasks.html",
        context=context,
    )


async def namespace_page(request: Request) -> HTMLResponse:
    """CRUD page for namespaces and their task key prefixes."""
    context = _namespace_context(request, page="namespace")
    namespaces = context["namespaces"]
    workflows = _load_workflows()
    selected_namespace = context.get("selected_namespace")
    context.update(
        {
            "projects": namespaces,
            "workflows": workflows,
            "selected_project": selected_namespace,
            "create_mode": False,
        }
    )
    return _template_response(
        request=request,
        name="projects.html",
        context=context,
    )


async def namespace_new_page(request: Request) -> HTMLResponse:
    """Create page for a new namespace."""
    context = _namespace_context(request, page="namespace")
    context.update(
        {
            "projects": context["namespaces"],
            "workflows": _load_workflows(),
            "selected_project": None,
            "create_mode": True,
        }
    )
    return _template_response(request=request, name="projects.html", context=context)


async def projects_page(request: Request) -> HTMLResponse:
    """Compatibility alias for legacy context/project pages."""
    return await namespace_page(request)


async def workflows_page(request: Request) -> HTMLResponse:
    context = _namespace_context(request, page="workflows")
    workflows = _load_workflows()
    context.update({"workflows": workflows, "selected_workflow": workflows[0] if workflows else None})
    return _template_response(
        request=request,
        name="workflows.html",
        context=context,
    )


async def task_detail_page(
    request: Request,
    task_key: str,
    namespace_id: int | None = Query(default=None),
    context_id: int | None = Query(default=None),
    project_id: int | None = Query(default=None, include_in_schema=False),
) -> HTMLResponse:
    """Деталка задачи — линейная история фаз."""
    selected_context_id = (
        namespace_id
        if namespace_id is not None
        else context_id
        if context_id is not None
        else project_id
    )
    context = _namespace_context(
        request,
        page="tasks",
        preferred_namespace_id=selected_context_id,
    )
    selected_namespace = context.get("selected_namespace")
    selected_namespace_id = (
        selected_namespace.get("id")
        if isinstance(selected_namespace, dict)
        else selected_context_id
    )
    try:
        task = _get_task_detail(
            task_key,
            project_id=selected_namespace_id if isinstance(selected_namespace_id, int) else None,
        )
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
    context.update(
        {
            "task": task,
            "current_phase_name": task.get("current_phase_name"),
            "progress_done": task.get("progress_done", 0),
            "progress_total": task.get("progress_total", 0),
            "cycles_done": task.get("completed_cycles", 0),
            "cycles_total": task.get("workflow_cycle_count", 0),
            "phase_history_blocks": task.get("phase_history_blocks", []),
            "step_history": task.get("step_history", []),
            **_theme_context(task.get("namespace") or task.get("project")),
        }
    )
    return _template_response(
        request=request,
        name="task_detail.html",
        context=context,
    )


async def settings_page(request: Request) -> HTMLResponse:
    """Read-only справка по реальным CLI-командам workflow."""
    context = _namespace_context(request, page="settings")
    context.update({"commands": _load_cli_reference()})
    return _template_response(
        request=request,
        name="settings.html",
        context=context,
    )


async def agents_page(request: Request) -> HTMLResponse:
    """Список агентов."""
    agents = _app_state.agent_service().list_agents()
    context = _namespace_context(request, page="agents")
    context.update({"agents": agents})
    return _template_response(
        request=request,
        name="agents.html",
        context=context,
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
    context = _namespace_context(request, page="phases")
    context.update(
        {
            "phase": phase,
            "instructions": instructions,
            "instruction_groups": instruction_groups,
        }
    )
    return _template_response(
        request=request,
        name="instructions.html",
        context=context,
    )
