"""HTML page routes for the workflow UI."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import Path, Request
from fastapi.responses import HTMLResponse

from project_workflow.application.phase_service import PhaseService
from project_workflow.config import get_settings
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import normalize_role_key
from project_workflow.interfaces.ui.platform_services import load_service_catalog
from project_workflow.interfaces.ui.services import (
    _build_parallel_phase_blocks,
    _get_task_detail,
    _load_cli_reference,
    _load_dashboard,
    _load_namespaces,
    _load_phase_detail,
    _load_tasks,
    _load_workflows,
)
from project_workflow.interfaces.ui.state import _app_state
from project_workflow.interfaces.ui.templates import _group_instructions, templates

NAMESPACE_COOKIE = "workflow_namespace_id"
PositivePathId = Annotated[int, Path(gt=0)]


def _theme_context(namespace: dict[str, Any] | None) -> dict[str, Any]:
    return {"theme_namespace": namespace}


def _parse_positive_int(raw: str | None) -> int | None:
    if raw is None or not raw.strip().isdecimal():
        return None
    value = int(raw.strip())
    return value if value > 0 else None


def _parse_query_namespace_id(raw: str | None) -> tuple[int | None, bool]:
    if raw is None:
        return None, False
    parsed = _parse_positive_int(raw)
    return parsed, parsed is None

def _namespace_context(
    request: Request,
    *,
    page: str,
    preferred_namespace_id: int | None = None,
) -> dict[str, Any]:
    namespaces = _load_namespaces()
    query_namespace_id, invalid_query_namespace_id = _parse_query_namespace_id(
        request.query_params.get("namespace_id")
    )
    cookie_namespace_id = _parse_positive_int(request.cookies.get(NAMESPACE_COOKIE))
    explicit_namespace_id = preferred_namespace_id if preferred_namespace_id is not None else query_namespace_id
    selected_id = (
        None
        if invalid_query_namespace_id and preferred_namespace_id is None
        else explicit_namespace_id
        if explicit_namespace_id is not None
        else cookie_namespace_id
    )
    selected_namespace = next((item for item in namespaces if item.get("id") == selected_id), None)
    missing_namespace_id = selected_id if explicit_namespace_id is not None and selected_namespace is None else None
    if selected_namespace is None and namespaces and missing_namespace_id is None and not invalid_query_namespace_id:
        selected_namespace = namespaces[0]
    catalog = load_service_catalog(
        get_settings().PLATFORM_SERVICES_URL,
        request_url=str(request.url),
    )
    return {
        "request": request,
        "page": page,
        "ui_port": get_settings().UI_PORT,
        "namespaces": namespaces,
        "selected_namespace": selected_namespace,
        "invalid_query_namespace_id": invalid_query_namespace_id,
        "missing_namespace_id": missing_namespace_id,
        "other_services": catalog.services,
        "services_source": catalog.source,
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


def http_error_page(
    request: Request,
    *,
    title: str,
    message: str,
    status_code: int,
    back_url: str = "/",
    back_label: str = "К дашборду",
) -> HTMLResponse:
    return _error_page(
        request,
        title=title,
        message=message,
        status_code=status_code,
        back_url=back_url,
        back_label=back_label,
        page="dashboard",
    )


def _namespace_error_page(request: Request, context: dict[str, Any], *, page: str) -> HTMLResponse | None:
    if context.get("invalid_query_namespace_id") is True:
        context = {
            **context,
            "page": page,
            "title": "Некорректный namespace_id",
            "message": "Некорректный namespace_id: ожидается положительное целое число.",
            "status_code": 422,
            "back_url": "/namespaces",
            "back_label": "К неймспейсам",
        }
        return _template_response(
            request=request,
            name="error.html",
            status_code=422,
            context=context,
        )
    missing_namespace_id = context.get("missing_namespace_id")
    if not isinstance(missing_namespace_id, int):
        return None
    context = {
        **context,
        "page": page,
        "title": "Неймспейс не найден",
        "message": f"Неймспейс {missing_namespace_id} не найден.",
        "status_code": 404,
        "back_url": "/namespaces",
        "back_label": "К неймспейсам",
    }
    return _template_response(
        request=request,
        name="error.html",
        status_code=404,
        context=context,
    )


def _query_id_error_page(
    request: Request,
    context: dict[str, Any],
    *,
    field_name: str,
    back_url: str,
    back_label: str,
    page: str,
) -> HTMLResponse:
    context = {
        **context,
        "page": page,
        "title": f"Некорректный {field_name}",
        "message": f"Некорректный {field_name}: ожидается положительное целое число.",
        "status_code": 422,
        "back_url": back_url,
        "back_label": back_label,
    }
    return _template_response(
        request=request,
        name="error.html",
        status_code=422,
        context=context,
    )


def _workflow_error_page(request: Request, context: dict[str, Any], workflow_id: int, *, page: str) -> HTMLResponse:
    selected_namespace = context.get("selected_namespace")
    namespace_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
    back_url = f"/workflows?namespace_id={namespace_id}" if isinstance(namespace_id, int) else "/workflows"
    context = {
        **context,
        "page": page,
        "title": "Воркфлоу не найден",
        "message": f"Воркфлоу {workflow_id} не найден.",
        "status_code": 404,
        "back_url": back_url,
        "back_label": "К воркфлоу",
    }
    return _template_response(
        request=request,
        name="error.html",
        status_code=404,
        context=context,
    )


def _workflow_not_in_selected_namespace_page(request: Request, context: dict[str, Any]) -> HTMLResponse:
    selected_namespace = context.get("selected_namespace")
    namespace_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
    back_url = f"/phases?namespace_id={namespace_id}" if isinstance(namespace_id, int) else "/phases"
    context = {
        **context,
        "page": "phases",
        "title": "Воркфлоу не найден",
        "message": "Воркфлоу недоступен в выбранном неймспейсе.",
        "status_code": 404,
        "back_url": back_url,
        "back_label": "К фазам",
    }
    return _template_response(
        request=request,
        name="error.html",
        status_code=404,
        context=context,
    )


def _phase_not_in_selected_namespace_page(request: Request, context: dict[str, Any]) -> HTMLResponse:
    selected_namespace = context.get("selected_namespace")
    namespace_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
    back_url = f"/phases?namespace_id={namespace_id}" if isinstance(namespace_id, int) else "/phases"
    context = {
        **context,
        "page": "phases",
        "title": "Фаза не найдена",
        "message": "Фаза недоступна в выбранном воркфлоу.",
        "status_code": 404,
        "back_url": back_url,
        "back_label": "К фазам",
    }
    return _template_response(
        request=request,
        name="error.html",
        status_code=404,
        context=context,
    )


def _mode_not_in_selected_workflow_page(
    request: Request,
    context: dict[str, Any],
    *,
    workflow_id: int,
    mode_key: str,
) -> HTMLResponse:
    selected_namespace = context.get("selected_namespace")
    namespace_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
    back_url = f"/phases?workflow_id={workflow_id}"
    if isinstance(namespace_id, int):
        back_url += f"&namespace_id={namespace_id}"
    context = {
        **context,
        "page": "phases",
        "title": "Режим воркфлоу не найден",
        "message": f"Режим {mode_key!r} недоступен в выбранном воркфлоу.",
        "status_code": 404,
        "back_url": back_url,
        "back_label": "К фазам",
    }
    return _template_response(
        request=request,
        name="error.html",
        status_code=404,
        context=context,
    )


def _phase_not_in_selected_mode_page(request: Request, context: dict[str, Any]) -> HTMLResponse:
    selected_namespace = context.get("selected_namespace")
    namespace_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
    back_url = f"/phases?namespace_id={namespace_id}" if isinstance(namespace_id, int) else "/phases"
    context = {
        **context,
        "page": "phases",
        "title": "Фаза не найдена",
        "message": "Фаза недоступна в выбранном режиме воркфлоу.",
        "status_code": 404,
        "back_url": back_url,
        "back_label": "К фазам",
    }
    return _template_response(
        request=request,
        name="error.html",
        status_code=404,
        context=context,
    )


def _load_mode_phases(workflow_id: int, mode_id: int) -> list[dict[str, Any]]:
    """Load one mode's phases with the presentation fields used by the timeline."""
    agents = {agent["id"]: agent for agent in _app_state.agent_service().list_agents()}
    rows: list[dict[str, Any]] = []
    for phase in _app_state.phase_service().list_phases(workflow_id, mode_id=mode_id):
        agent = agents.get(phase.get("agent_id"))
        rows.append(
            {
                **phase,
                "phase_num": phase.get("phase_num", phase.get("phase_order", 0)),
                "agent_name": agent.get("name") if agent else None,
            }
        )
    return rows


def _workflow_mode_ui_state(mode: dict[str, Any]) -> dict[str, Any]:
    """Expose backend-owned dispatch policy without making UI routing decisions."""
    key = mode.get("key")
    role_key = mode.get("role_key")
    execution_scope = mode.get("execution_scope")
    tech_workspace_policy = mode.get("tech_workspace_policy")
    role_is_valid = False
    try:
        role_is_valid = normalize_role_key(role_key) == role_key
    except ValueError:
        pass
    policy_is_complete = (
        role_is_valid
        and execution_scope in {"business", "delivery", "aggregate"}
        and tech_workspace_policy in {"forbidden", "required"}
    )
    policy_is_consistent = (
        execution_scope == "business" and tech_workspace_policy == "forbidden"
    ) or (
        execution_scope in {"delivery", "aggregate"}
        and tech_workspace_policy == "required"
    )
    is_legacy_default = key == "default"
    is_dispatchable = not is_legacy_default and policy_is_complete and policy_is_consistent
    if is_legacy_default:
        status_label = "Legacy compatibility · только чтение"
        status_message = (
            "Default mode сохранён только для совместимости. Назначение и изменение фаз отключены."
        )
    elif not policy_is_complete:
        status_label = "Конфигурация неполна · только чтение"
        status_message = (
            "Режим нельзя назначать: требуется полная backend-политика role, scope и Tech workspace. "
            "Редактор доступен только для чтения."
        )
    elif not policy_is_consistent:
        status_label = "Конфигурация некорректна · только чтение"
        status_message = (
            "Режим нельзя назначать: Business scope запрещает Tech workspace, а delivery/aggregate "
            "требуют его. Редактор доступен только для чтения."
        )
    else:
        status_label = f"{role_key} · {execution_scope}"
        status_message = "Режим полностью настроен и доступен для backend assignment."
    return {
        **mode,
        "is_legacy_default": is_legacy_default,
        "is_dispatchable": is_dispatchable,
        "is_read_only": not is_dispatchable,
        "status_label": status_label,
        "status_message": status_message,
    }


def _workflow_mode_sort_key(mode: dict[str, Any]) -> tuple[int, int, str]:
    raw_order = mode.get("mode_order")
    order = raw_order if isinstance(raw_order, int) and not isinstance(raw_order, bool) else 2**31
    raw_id = mode.get("id")
    mode_id = raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else 2**31
    return order, mode_id, str(mode.get("key") or "")


def _workflow_mode_context(
    raw_modes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    modes = sorted((_workflow_mode_ui_state(mode) for mode in raw_modes), key=_workflow_mode_sort_key)
    configured_modes = [mode for mode in modes if not mode["is_legacy_default"]]
    legacy_mode = next((mode for mode in modes if mode["is_legacy_default"]), None)
    return modes, configured_modes, legacy_mode


def _resolve_phase_mode(
    request: Request,
    phase: dict[str, Any],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]] | HTMLResponse:
    workflow_id = phase.get("workflow_id")
    mode_id = phase.get("mode_id")
    if not isinstance(workflow_id, int) or not isinstance(mode_id, int):
        return _phase_not_in_selected_mode_page(request, context)
    modes, _, _ = _workflow_mode_context(_app_state.workflow_service().list_modes(workflow_id))
    owning_mode = next((mode for mode in modes if mode.get("id") == mode_id), None)
    if owning_mode is None:
        return _phase_not_in_selected_mode_page(request, context)
    requested_mode_key = request.query_params.get("mode")
    if requested_mode_key is not None and requested_mode_key != owning_mode.get("key"):
        return _phase_not_in_selected_mode_page(request, context)
    return modes, owning_mode


def _tasks_back_url(context: dict[str, Any]) -> str:
    selected_namespace = context.get("selected_namespace")
    namespace_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
    return f"/tasks?namespace_id={namespace_id}" if isinstance(namespace_id, int) else "/tasks"


def _task_data_error_page(
    request: Request,
    context: dict[str, Any],
    *,
    title: str,
    message: str,
) -> HTMLResponse:
    context = {
        **context,
        "page": "tasks",
        "title": title,
        "message": message,
        "status_code": 409,
        "back_url": _tasks_back_url(context),
        "back_label": "К списку задач",
    }
    return _template_response(
        request=request,
        name="error.html",
        status_code=409,
        context=context,
    )


def _workflow_is_unassigned(workflow_id: Any) -> bool:
    if not isinstance(workflow_id, int):
        return False
    workflow = next((item for item in _load_workflows() if item.get("id") == workflow_id), None)
    if workflow is None:
        return False
    try:
        return int(workflow.get("namespace_count") or 0) == 0
    except (TypeError, ValueError):
        return False


def _phase_matches_selected_namespace(phase: dict[str, Any], context: dict[str, Any]) -> bool:
    selected_namespace = context.get("selected_namespace")
    selected_workflow_id = selected_namespace.get("workflow_id") if isinstance(selected_namespace, dict) else None
    phase_workflow_id = phase.get("workflow_id")
    return (
        not isinstance(selected_workflow_id, int)
        or phase_workflow_id == selected_workflow_id
        or _workflow_is_unassigned(phase_workflow_id)
    )


def validation_error_page(request: Request, errors: Sequence[Any]) -> HTMLResponse | None:
    """Render route validation failures as HTML for browser-facing pages."""
    path = request.url.path
    phase_id_failed = any("phase_id" in issue.get("loc", ()) for issue in errors)
    if path.startswith("/phase/") and phase_id_failed:
        context = _namespace_context(request, page="phases")
        return _query_id_error_page(
            request,
            context,
            field_name="phase_id",
            back_url="/phases",
            back_label="К фазам",
            page="phases",
        )
    return None


async def index(request: Request) -> HTMLResponse:
    """Минимальный dashboard без заглушек."""
    context = _namespace_context(request, page="dashboard")
    if error_response := _namespace_error_page(request, context, page="dashboard"):
        return error_response
    selected_namespace = context.get("selected_namespace")
    namespace_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
    try:
        dashboard = _load_dashboard(namespace_id=namespace_id if isinstance(namespace_id, int) else None)
    except ValueError as exc:
        return _task_data_error_page(
            request,
            context,
            title="Данные задач некорректны",
            message=str(exc),
        )
    context.update(dashboard)
    return _template_response(
        request=request,
        name="dashboard.html",
        context=context,
    )


async def phases_page(request: Request) -> HTMLResponse:
    context = _namespace_context(request, page="phases")
    if error_response := _namespace_error_page(request, context, page="phases"):
        return error_response
    raw_workflow_id = request.query_params.get("workflow_id")
    workflow_id = _parse_positive_int(raw_workflow_id)
    if raw_workflow_id is not None and workflow_id is None:
        return _query_id_error_page(
            request,
            context,
            field_name="workflow_id",
            back_url="/phases",
            back_label="К фазам",
            page="phases",
        )
    selected_namespace = context.get("selected_namespace")
    selected_namespace_workflow_id = (
        selected_namespace.get("workflow_id") if isinstance(selected_namespace, dict) else None
    )
    has_explicit_namespace = request.query_params.get("namespace_id") is not None
    cookie_namespace_id = _parse_positive_int(request.cookies.get(NAMESPACE_COOKIE))
    has_cookie_namespace = (
        request.query_params.get("namespace_id") is None
        and isinstance(cookie_namespace_id, int)
        and isinstance(selected_namespace, dict)
        and selected_namespace.get("id") == cookie_namespace_id
    )
    if workflow_id is None and isinstance(selected_namespace_workflow_id, int):
        workflow_id = selected_namespace_workflow_id
    workflows = _load_workflows()
    selected_workflow = next((item for item in workflows if item["id"] == workflow_id), None)
    if workflow_id is not None and selected_workflow is None:
        return _workflow_error_page(request, context, int(workflow_id), page="phases")
    selected_workflow_has_namespace = bool((selected_workflow or {}).get("namespace_count"))
    if (
        (has_explicit_namespace or (has_cookie_namespace and selected_workflow_has_namespace))
        and isinstance(selected_namespace_workflow_id, int)
        and workflow_id is not None
        and workflow_id != selected_namespace_workflow_id
    ):
        return _workflow_not_in_selected_namespace_page(request, context)
    if selected_workflow is None and workflows:
        selected_workflow = workflows[0]
    selected_workflow_id = selected_workflow["id"] if selected_workflow else None
    namespace_scoped_view = isinstance(selected_namespace, dict) and (
        raw_workflow_id is None or has_explicit_namespace or has_cookie_namespace
    )
    visible_workflows = [selected_workflow] if namespace_scoped_view and selected_workflow else workflows
    workflow_modes: list[dict[str, Any]] = []
    configured_modes: list[dict[str, Any]] = []
    legacy_mode: dict[str, Any] | None = None
    selected_mode: dict[str, Any] | None = None
    phases: list[dict[str, Any]] = []
    if selected_workflow_id is not None:
        workflow_modes, configured_modes, legacy_mode = _workflow_mode_context(
            _app_state.workflow_service().list_modes(int(selected_workflow_id))
        )
        requested_mode_key = request.query_params.get("mode")
        if requested_mode_key is not None:
            selected_mode_key = requested_mode_key
        else:
            first_dispatchable = next(
                (mode for mode in configured_modes if mode["is_dispatchable"]),
                None,
            )
            first_configured = configured_modes[0] if configured_modes else None
            fallback_mode = first_dispatchable or first_configured or legacy_mode
            selected_mode_key = str(fallback_mode.get("key")) if fallback_mode is not None else ""
        selected_mode = next(
            (mode for mode in workflow_modes if mode.get("key") == selected_mode_key),
            None,
        )
        if selected_mode is None:
            return _mode_not_in_selected_workflow_page(
                request,
                context,
                workflow_id=int(selected_workflow_id),
                mode_key=selected_mode_key,
            )
        selected_mode_id = selected_mode.get("id")
        if not isinstance(selected_mode_id, int):
            return _mode_not_in_selected_workflow_page(
                request,
                context,
                workflow_id=int(selected_workflow_id),
                mode_key=selected_mode_key,
            )
        phases = _load_mode_phases(int(selected_workflow_id), selected_mode_id)
    phase_blocks = _build_parallel_phase_blocks(phases)
    context.update(
        {
            "phases": phases,
            "phase_blocks": phase_blocks,
            "phase_count": len(phases),
            "workflows": visible_workflows,
            "selected_workflow": selected_workflow,
            "selected_workflow_id": selected_workflow_id,
            "workflow_modes": workflow_modes,
            "configured_modes": configured_modes,
            "legacy_mode": legacy_mode,
            "selected_mode": selected_mode,
            "mode_read_only": bool(selected_mode and selected_mode["is_read_only"]),
        }
    )
    return _template_response(
        request=request,
        name="phases.html",
        context=context,
    )


async def phase_detail(request: Request, phase_id: PositivePathId) -> HTMLResponse:
    context = _namespace_context(request, page="phases")
    if error_response := _namespace_error_page(request, context, page="phases"):
        return error_response
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
    if not _phase_matches_selected_namespace(phase, context):
        return _phase_not_in_selected_namespace_page(request, context)
    mode_context = _resolve_phase_mode(request, phase, context)
    if not isinstance(mode_context, tuple):
        return mode_context
    workflow_modes, selected_mode = mode_context
    agents = _app_state.agent_service().list_agents()
    workflow_phases = _app_state.phase_service().list_phases(
        phase.get("workflow_id"),
        mode_id=phase.get("mode_id"),
    )
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
    context.update(
        {
            "phase": phase,
            "agents": agents,
            "workflow_phases": workflow_phases,
            "parallel_candidates": parallel_candidates,
            "rollback_target_phase": rollback_target_phase,
            "workflow_modes": workflow_modes,
            "selected_mode": selected_mode,
            "mode_read_only": bool(selected_mode["is_read_only"]),
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
    if error_response := _namespace_error_page(request, context, page="tasks"):
        return error_response
    selected_namespace = context.get("selected_namespace")
    namespace_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
    try:
        tasks = _load_tasks(namespace_id=namespace_id if isinstance(namespace_id, int) else None)
    except ValueError as exc:
        return _task_data_error_page(
            request,
            context,
            title="Данные задач некорректны",
            message=str(exc),
        )
    context.update({"tasks": tasks})
    return _template_response(
        request=request,
        name="tasks.html",
        context=context,
    )


async def namespace_page(request: Request) -> HTMLResponse:
    """CRUD page for namespaces and style."""
    context = _namespace_context(request, page="namespace")
    if error_response := _namespace_error_page(request, context, page="namespace"):
        return error_response
    workflows = _load_workflows()
    selected_namespace = context.get("selected_namespace")
    context.update(
        {
            "workflows": workflows,
            "edited_namespace": selected_namespace,
            "create_mode": False,
        }
    )
    return _template_response(
        request=request,
        name="namespaces.html",
        context=context,
    )


async def namespace_new_page(request: Request) -> HTMLResponse:
    """Create page for a new namespace."""
    context = _namespace_context(request, page="namespace")
    if error_response := _namespace_error_page(request, context, page="namespace"):
        return error_response
    context.update(
        {
            "workflows": _load_workflows(),
            "edited_namespace": None,
            "create_mode": True,
        }
    )
    return _template_response(request=request, name="namespaces.html", context=context)


async def workflows_page(request: Request) -> HTMLResponse:
    context = _namespace_context(request, page="workflows")
    if error_response := _namespace_error_page(request, context, page="workflows"):
        return error_response
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
) -> HTMLResponse:
    """Деталка задачи — линейная история фаз."""
    context = _namespace_context(request, page="tasks")
    if error_response := _namespace_error_page(request, context, page="tasks"):
        return error_response
    selected_namespace = context.get("selected_namespace")
    selected_namespace_id = selected_namespace.get("id") if isinstance(selected_namespace, dict) else None
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
            back_url=_tasks_back_url(context),
            back_label="К списку задач",
            page="tasks",
        )
    except ValueError as exc:
        return _task_data_error_page(
            request,
            context,
            title="Состояние задачи некорректно",
            message=str(exc),
        )
    if not task:
        return _error_page(
            request,
            title="Задача не найдена",
            message=f"Задачи {task_key} нет в текущем каталоге.",
            status_code=404,
            back_url=_tasks_back_url(context),
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
            "phase_events_audit": task.get("phase_events_audit", []),
            "step_history_audit": task.get("step_history_audit", []),
            **_theme_context(task.get("namespace")),
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
    if error_response := _namespace_error_page(request, context, page="settings"):
        return error_response
    selected_namespace = context.get("selected_namespace")
    entrypoint = selected_namespace.get("cli_command") if isinstance(selected_namespace, dict) else None
    context.update({"commands": _load_cli_reference(entrypoint=entrypoint)})
    return _template_response(
        request=request,
        name="settings.html",
        context=context,
    )


async def agents_page(request: Request) -> HTMLResponse:
    """Список агентов."""
    context = _namespace_context(request, page="agents")
    if error_response := _namespace_error_page(request, context, page="agents"):
        return error_response
    agents = [
        {**agent, "launch_profile": agent.get("hermes_profile") or ""}
        for agent in _app_state.agent_service().list_agents()
    ]
    context.update({"agents": agents})
    return _template_response(
        request=request,
        name="agents.html",
        context=context,
    )


async def instructions_page(request: Request) -> HTMLResponse:
    """Dedicated instructions editor page for a phase."""
    context = _namespace_context(request, page="phases")
    if error_response := _namespace_error_page(request, context, page="phases"):
        return error_response
    raw_phase_id = request.query_params.get("phase_id")
    phase_id = _parse_positive_int(raw_phase_id)
    if raw_phase_id is not None and phase_id is None:
        return _query_id_error_page(
            request,
            context,
            field_name="phase_id",
            back_url="/phases",
            back_label="К фазам",
            page="phases",
        )
    if phase_id is None:
        context.update(
            {
                "title": "Выберите фазу",
                "message": "Инструкции открываются из карточки нужной фазы.",
                "back_url": "/phases",
                "back_label": "К фазам",
                "empty_state": True,
            }
        )
        return _template_response(request=request, name="error.html", context=context)
    phase = _load_phase_detail(phase_id)
    if not phase:
        context.update(
            {
                "title": "Фаза не найдена",
                "message": "Инструкции для указанной фазы недоступны.",
                "status_code": 404,
                "back_url": "/phases",
                "back_label": "К фазам",
            }
        )
        return _template_response(request=request, name="error.html", status_code=404, context=context)
    if not _phase_matches_selected_namespace(phase, context):
        return _phase_not_in_selected_namespace_page(request, context)
    mode_context = _resolve_phase_mode(request, phase, context)
    if not isinstance(mode_context, tuple):
        return mode_context
    workflow_modes, selected_mode = mode_context
    instructions = phase.get("instructions", [])
    for instruction in instructions:
        instruction["skills"] = PhaseService.normalize_skills(instruction.get("skills"))
    instruction_groups = _group_instructions(instructions)
    context.update(
        {
            "phase": phase,
            "instructions": instructions,
            "instruction_groups": instruction_groups,
            "workflow_modes": workflow_modes,
            "selected_mode": selected_mode,
            "mode_read_only": bool(selected_mode["is_read_only"]),
        }
    )
    return _template_response(
        request=request,
        name="instructions.html",
        context=context,
    )
