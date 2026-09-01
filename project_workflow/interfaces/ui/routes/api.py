"""JSON API routes for the workflow UI."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Path, Query
from fastapi.responses import JSONResponse

from project_workflow.domain.exceptions import ConflictError, LastPhaseError, NotFoundError
from project_workflow.domain.namespace import legacy_code_from_cli_command
from project_workflow.domain.project_theme import normalize_theme_color, normalize_theme_icon
from project_workflow.interfaces.ui.schemas import (
    AgentCreate,
    AgentUpdate,
    InstructionCreate,
    InstructionReorder,
    InstructionUpdate,
    NamespaceCreate,
    NamespaceUpdate,
    PhaseCreate,
    PhaseOrderUpdate,
    PhaseUpdate,
    WorkflowCreate,
    WorkflowUpdate,
)
from project_workflow.interfaces.ui.services import _load_phase_detail, _load_tasks
from project_workflow.interfaces.ui.state import _app_state

PositivePathId = Annotated[int, Path(gt=0)]


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _updates_from_payload(payload: Any, fields: list[str]) -> dict[str, Any]:
    """Build updates from explicitly supplied fields, preserving nullable clears."""
    return {key: getattr(payload, key) for key in fields if key in payload.model_fields_set}


def _with_namespace_aliases(item: dict[str, Any]) -> dict[str, Any]:
    """Expose canonical namespace keys."""
    theme_icon = normalize_theme_icon(item.get("theme_icon"))
    theme_color = normalize_theme_color(item.get("theme_color"))
    namespace = {
        "id": item.get("id"),
        "namespace_id": item.get("id"),
        "name": item.get("name"),
        "namespace_name": item.get("name"),
        "description": item.get("description", ""),
        "workflow_id": item.get("workflow_id"),
        "workflow_name": item.get("workflow_name"),
        "theme_icon": theme_icon,
        "namespace_theme_icon": theme_icon,
        "theme_color": theme_color,
        "namespace_theme_color": theme_color,
        "cli_command": item.get("cli_command"),
        "namespace_cli_command": item.get("cli_command"),
        "task_count": item.get("task_count", 0),
    }
    return namespace


def _unique_legacy_code(command: str, existing: list[dict[str, Any]]) -> str:
    desired = legacy_code_from_cli_command(command)
    used = {str(item.get("code") or "").upper() for item in existing}
    if desired not in used:
        return desired
    suffix = 2
    base = desired[:28]
    while True:
        candidate = f"{base}{suffix}"
        if candidate not in used:
            return candidate
        suffix += 1


async def api_settings_get(namespace_id: int | None = Query(default=None, gt=0)) -> dict[str, Any] | JSONResponse:
    """Вернуть реестр CLI-команд для UI/интеграций."""
    from project_workflow.interfaces.ui.services import _load_cli_reference

    entrypoint = None
    if namespace_id is not None:
        namespace = _app_state.project_service().get_project(namespace_id)
        if namespace is None:
            return _error(f"Неймспейс {namespace_id} не найден", 404)
        entrypoint = namespace.get("cli_command")
    return {"ok": True, "commands": _load_cli_reference(entrypoint=entrypoint)}


async def api_phases(workflow_id: int | None = Query(default=None, gt=0)) -> dict[str, Any] | JSONResponse:
    workflows = _app_state.workflow_service().list_workflows()
    selected_workflow = next((item for item in workflows if item["id"] == workflow_id), None)
    if workflow_id is not None and selected_workflow is None:
        return _error(f"Воркфлоу {workflow_id} не найден", 404)
    if selected_workflow is None and workflow_id is None and workflows:
        selected_workflow = workflows[0]
    selected_workflow_id = selected_workflow["id"] if selected_workflow else workflow_id
    phases = _app_state.phase_service().list_phases(selected_workflow_id)
    agents = {a["id"]: a for a in _app_state.agent_service().list_agents()}

    rows = []
    for phase in phases:
        agent = agents.get(phase.get("agent_id"))
        rows.append(
            {
                "id": phase["id"],
                "name": phase["name"],
                "description": phase.get("description", ""),
                "code": phase.get("code", ""),
                "workflow_id": phase.get("workflow_id"),
                "phase_num": phase.get("phase_num", phase.get("phase_order", 0)),
                "phase_order": phase.get("phase_order", 0),
                "execution_type": phase.get("execution_type", "sync"),
                "parallel_with_phase_id": phase.get("parallel_with_phase_id"),
                "rollback_target_phase_id": phase.get("rollback_target_phase_id"),
                "agent_name": agent["name"] if agent else None,
                "agent_id": phase.get("agent_id"),
                "hermes_profile": agent.get("hermes_profile") if agent else None,
            }
        )
    result: dict[str, Any] = {"ok": True, "phases": rows}
    if selected_workflow is not None:
        result["workflow"] = selected_workflow
    return result


async def api_tasks(
    workflow_id: int | None = Query(default=None, gt=0),
    namespace_id: int | None = Query(default=None, gt=0),
) -> dict[str, Any] | JSONResponse:
    if namespace_id is not None and _app_state.project_service().get_project(namespace_id) is None:
        return _error(f"Неймспейс {namespace_id} не найден", 404)
    if workflow_id is not None and _app_state.workflow_service().get_workflow(workflow_id) is None:
        return _error(f"Воркфлоу {workflow_id} не найден", 404)
    tasks = _load_tasks(namespace_id=namespace_id)
    if workflow_id is not None:
        tasks = [t for t in tasks if t.get("workflow_id") == workflow_id]
    return {"ok": True, "tasks": tasks}


async def api_namespaces() -> dict[str, Any] | JSONResponse:
    from project_workflow.interfaces.ui.services import _load_namespaces

    namespaces = [_with_namespace_aliases(item) for item in _load_namespaces()]
    return {"ok": True, "namespaces": namespaces}


async def api_namespace_get(namespace_id: PositivePathId) -> dict[str, Any] | JSONResponse:
    namespace = _app_state.project_service().get_project(namespace_id)
    if namespace is None:
        return _error(f"Неймспейс {namespace_id} не найден", 404)
    payload = _with_namespace_aliases(namespace)
    return {"ok": True, "namespace": payload}

async def api_workflows() -> dict[str, Any] | JSONResponse:
    from project_workflow.interfaces.ui.services import _load_workflows

    return {"ok": True, "workflows": _load_workflows()}


async def api_agents() -> dict[str, Any] | JSONResponse:
    rows = _app_state.agent_service().list_agents()
    return {
        "ok": True,
        "agents": [
            {
                **agent,
                "description": agent.get("description", ""),
                "hermes_profile": agent.get("hermes_profile"),
            }
            for agent in rows
        ],
    }


async def api_phase_create(payload: PhaseCreate) -> dict[str, Any] | JSONResponse:
    workflow_id = payload.workflow_id
    assert payload.phase_order is not None
    data = {
        "name": payload.name,
        "description": payload.description,
        "workflow_id": workflow_id,
        "phase_order": payload.phase_order,
        "execution_type": payload.execution_type,
        "parallel_with_phase_id": payload.parallel_with_phase_id,
        "rollback_target_phase_id": payload.rollback_target_phase_id,
        "agent_id": payload.agent_id,
    }
    if payload.code:
        data["code"] = payload.code
    try:
        phase = _app_state.phase_service().create_phase(data)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except (TypeError, ValueError) as exc:
        return _error(str(exc), 422)
    return {
        "ok": True,
        "phase_id": phase["id"],
        "phase_order": phase.get("phase_order", payload.phase_order),
        "phase": phase,
    }


async def api_phase_update(phase_id: PositivePathId, payload: PhaseUpdate) -> dict[str, Any] | JSONResponse:
    srv = _app_state.get_service()
    scalar_fields = {
        "name",
        "description",
        "parallel_with_phase_id",
        "rollback_target_phase_id",
        "agent_id",
        "execution_type",
    }
    selected_fields = scalar_fields.intersection(payload.model_fields_set)
    aggregate = {field: getattr(payload, field) for field in selected_fields}
    for field in ("instructions", "checks", "evidence"):
        if field in payload.model_fields_set:
            items = getattr(payload, field)
            assert items is not None
            aggregate[field] = [item.model_dump() for item in items]
    try:
        ids = srv.update_phase_detail(phase_id, aggregate)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except (TypeError, ValueError) as exc:
        return _error(str(exc), 422)
    return {"ok": True, "ids": ids}


async def api_phase_delete(phase_id: PositivePathId) -> dict[str, Any] | JSONResponse:
    try:
        _app_state.phase_service().delete_phase(phase_id)
    except NotFoundError:
        return _error(f"Фаза {phase_id} не найдена", 404)
    except (ConflictError, LastPhaseError) as exc:
        return _error(str(exc), 409)
    return {"ok": True}


async def api_phase_batch_order(payload: PhaseOrderUpdate) -> dict[str, Any] | JSONResponse:
    batch: list[tuple[int, int]] = []
    for item in payload.orders:
        resolved_phase_id = item.phase_id
        if item.workflow_id is not None:
            phase = _app_state.phase_service().get_phase(resolved_phase_id)
            if phase is None:
                return _error(f"Фаза {resolved_phase_id} не найдена", 404)
            if phase.get("workflow_id") != item.workflow_id:
                return _error("workflow_id не совпадает с владельцем фазы", 409)
        batch.append((resolved_phase_id, item.phase_order))
    try:
        updated = _app_state.phase_service().reorder_phases(batch)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except ValueError as exc:
        return _error(str(exc), 422)
    return {"ok": True, "updated": updated}


async def api_workflow_create(payload: WorkflowCreate) -> dict[str, Any] | JSONResponse:
    service = _app_state.workflow_service()
    workflow = service.create_workflow({"name": payload.name, "description": payload.description or ""})
    workflow_id = workflow["id"]
    return {"ok": True, "workflow_id": workflow_id, "workflow": service.get_workflow(workflow_id)}


async def api_workflow_update(workflow_id: PositivePathId, payload: WorkflowUpdate) -> dict[str, Any] | JSONResponse:
    service = _app_state.workflow_service()
    updates = _updates_from_payload(payload, ["name", "description"])
    try:
        service.update_workflow(workflow_id, updates)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return {"ok": True, "workflow": service.get_workflow(workflow_id)}


async def api_workflow_delete(workflow_id: PositivePathId) -> dict[str, Any] | JSONResponse:
    service = _app_state.workflow_service()
    try:
        service.delete_workflow(workflow_id)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return {"ok": True}


async def api_namespace_create(payload: NamespaceCreate) -> dict[str, Any] | JSONResponse:
    if "description" in payload.model_fields_set and payload.description is None:
        return _error("description не может быть null", 422)
    service = _app_state.project_service()
    existing = service.list_projects()
    try:
        namespace = service.create_project(
            {
                "code": _unique_legacy_code(payload.cli_command, existing),
                "name": payload.name,
                "description": payload.description or "",
                "theme_icon": payload.theme_icon,
                "theme_color": payload.theme_color,
                "cli_command": payload.cli_command,
                "key_prefixes": [],
                "workflow_id": payload.workflow_id,
            }
        )
    except ConflictError as exc:
        return _error(str(exc), 409)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ValueError as exc:
        return _error(str(exc), 422)
    namespace_id = namespace["id"]
    context = _with_namespace_aliases(service.get_project(namespace_id) or namespace)
    return {
        "ok": True,
        "namespace_id": namespace_id,
        "namespace": context,
    }


async def api_namespace_update(namespace_id: PositivePathId, payload: NamespaceUpdate) -> dict[str, Any] | JSONResponse:
    service = _app_state.project_service()
    updates = _updates_from_payload(
        payload,
        ["name", "description", "workflow_id", "theme_icon", "theme_color", "cli_command"],
    )
    try:
        service.update_project(namespace_id, updates)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ValueError as exc:
        return _error(str(exc), 422)
    context = _with_namespace_aliases(service.get_project(namespace_id) or {})
    return {"ok": True, "namespace": context}


async def api_namespace_delete(namespace_id: PositivePathId) -> dict[str, Any] | JSONResponse:
    service = _app_state.project_service()
    try:
        service.delete_project(namespace_id)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except ValueError as exc:
        return _error(str(exc), 422)
    return {"ok": True}

async def api_agent_create(payload: AgentCreate) -> dict[str, Any] | JSONResponse:
    service = _app_state.agent_service()
    try:
        agent_id = service.create_agent(
            {
                "name": payload.name,
                "description": payload.description or "",
                "hermes_profile": payload.hermes_profile,
            }
        )["id"]
    except ConflictError as exc:
        return _error(str(exc), 409)
    except ValueError as exc:
        return _error(str(exc), 422)
    return {"ok": True, "agent_id": agent_id, "agent": service.get_agent(agent_id)}


async def api_agent_update(agent_id: PositivePathId, payload: AgentUpdate) -> dict[str, Any] | JSONResponse:
    service = _app_state.agent_service()
    updates = _updates_from_payload(payload, ["name", "description"])
    if "hermes_profile" in payload.model_fields_set:
        updates["hermes_profile"] = payload.hermes_profile
    try:
        service.update_agent(agent_id, updates)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except ValueError as exc:
        return _error(str(exc), 422)
    return {"ok": True, "agent": service.get_agent(agent_id)}


async def api_agent_delete(agent_id: PositivePathId) -> dict[str, Any] | JSONResponse:
    service = _app_state.agent_service()
    try:
        service.delete_agent(agent_id)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return {"ok": True}


async def api_phase_detail(phase_id: PositivePathId) -> dict[str, Any] | JSONResponse:
    phase = _load_phase_detail(phase_id)
    if not phase:
        return _error(f"Фаза {phase_id} не найдена", 404)
    return {"ok": True, "phase": phase}


async def api_instructions_list(phase_id: PositivePathId) -> dict[str, Any] | JSONResponse:
    phase = _app_state.phase_service().get_phase(phase_id)
    if phase is None:
        return _error(f"Фаза {phase_id} не найдена", 404)
    instructions = _app_state.instruction_service().list_instructions(phase_id)
    return {"ok": True, "phase": phase, "instructions": instructions}


async def api_instruction_create(payload: InstructionCreate) -> dict[str, Any] | JSONResponse:
    try:
        item = _app_state.instruction_service().create_instruction(
            payload.phase_id,
            {
                "description": payload.description,
                "execution_type": payload.execution_type,
                "skills": payload.skills,
                "step_num": payload.step_num,
            },
        )
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except ValueError as exc:
        return _error(str(exc), 422)
    return {"ok": True, "instruction": item}


async def api_instruction_update(
    instruction_id: PositivePathId,
    payload: InstructionUpdate,
) -> dict[str, Any] | JSONResponse:
    updates = _updates_from_payload(payload, ["description", "execution_type"])
    if "skills" in payload.model_fields_set:
        updates["skills"] = payload.skills
    try:
        _app_state.instruction_service().update_instruction(instruction_id, updates)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except (TypeError, ValueError) as exc:
        return _error(str(exc), 422)
    return {"ok": True, "instruction": _app_state.instruction_service().get_instruction(instruction_id)}


async def api_instruction_delete(instruction_id: PositivePathId) -> dict[str, Any] | JSONResponse:
    try:
        _app_state.instruction_service().delete_instruction(instruction_id)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return {"ok": True}


async def api_instructions_reorder(
    phase_id: PositivePathId,
    payload: InstructionReorder,
) -> dict[str, Any] | JSONResponse:
    try:
        _app_state.instruction_service().reorder_instructions(phase_id, payload.instruction_ids)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except (TypeError, ValueError) as exc:
        return _error(str(exc), 422)
    return {"ok": True}
