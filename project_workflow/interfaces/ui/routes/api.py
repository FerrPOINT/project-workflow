"""JSON API routes for the workflow UI."""

from __future__ import annotations

from typing import Any

from fastapi import Query
from fastapi.responses import JSONResponse

from project_workflow.domain.exceptions import ConflictError, LastPhaseError, NotFoundError
from project_workflow.domain.namespace import legacy_code_from_cli_command
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.routes.runtime_api import execute_namespace_step
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
    ProjectCreate,
    ProjectUpdate,
    UiTaskStepRequest,
    WorkflowCreate,
    WorkflowUpdate,
)
from project_workflow.interfaces.ui.services import (
    _is_agent_visible,
    _is_namespace_visible,
    _is_phase_visible,
    _is_workflow_visible,
    _load_agents,
    _load_phase_detail,
    _load_phases,
    _load_tasks,
    _load_workflows,
    _visibility_is_restricted,
)
from project_workflow.interfaces.ui.state import _app_state


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _namespace_is_hidden(namespace_id: int) -> bool:
    return _visibility_is_restricted() and not _is_namespace_visible(namespace_id)


def _workflow_is_hidden(workflow_id: int) -> bool:
    return _visibility_is_restricted() and not _is_workflow_visible(workflow_id)


def _phase_is_hidden(phase_id: int) -> bool:
    return _visibility_is_restricted() and not _is_phase_visible(phase_id)


def _agent_is_hidden(agent_id: int) -> bool:
    return _visibility_is_restricted() and not _is_agent_visible(agent_id)


def _deny_restricted_catalog_write() -> JSONResponse | None:
    if not _visibility_is_restricted():
        return None
    return _error("Каталог недоступен для изменения в ограниченном интерфейсе", 403)


def _updates_from_payload(payload: Any, fields: list[str]) -> dict[str, Any]:
    """Build updates from explicitly supplied fields, preserving nullable clears."""
    return {key: getattr(payload, key) for key in fields if key in payload.model_fields_set}


def _with_namespace_aliases(item: dict[str, Any]) -> dict[str, Any]:
    """Expose canonical namespace keys while preserving legacy aliases."""
    namespace = dict(item)
    namespace["namespace_id"] = namespace.get("id")
    namespace["namespace_code"] = namespace.get("code")
    namespace["namespace_name"] = namespace.get("name")
    namespace["namespace_theme_icon"] = namespace.get("theme_icon")
    namespace["namespace_theme_color"] = namespace.get("theme_color")
    namespace["namespace_cli_command"] = namespace.get("cli_command")
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


async def api_settings_get() -> dict[str, Any] | JSONResponse:
    """Вернуть реестр CLI-команд для UI/интеграций."""
    from project_workflow.interfaces.ui.services import _load_cli_reference

    return {"ok": True, "commands": _load_cli_reference()}


async def api_phases(workflow_id: int | None = Query(default=None)) -> dict[str, Any] | JSONResponse:
    workflows = _load_workflows()
    selected_workflow = next((item for item in workflows if item["id"] == workflow_id), None)
    if workflow_id is not None and selected_workflow is None:
        return _error(f"Воркфлоу {workflow_id} не найден", 404)
    if selected_workflow is None and workflow_id is None and workflows:
        selected_workflow = workflows[0]
    selected_workflow_id = selected_workflow["id"] if selected_workflow else workflow_id
    phases = _load_phases(selected_workflow_id) if selected_workflow_id is not None else []
    agents = {a["id"]: a for a in _load_agents()}

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
    workflow_id: int | None = Query(default=None),
    namespace_id: int | None = Query(default=None),
) -> dict[str, Any] | JSONResponse:
    if namespace_id is not None and _namespace_is_hidden(namespace_id):
        return _error("Namespace не найден", 404)
    if workflow_id is not None and _workflow_is_hidden(workflow_id):
        return _error(f"Воркфлоу {workflow_id} не найден", 404)
    tasks = _load_tasks(namespace_id=namespace_id)
    if workflow_id is not None:
        tasks = [t for t in tasks if t.get("workflow_id") == workflow_id]
    return {"ok": True, "tasks": tasks}


async def api_task_step(payload: UiTaskStepRequest) -> dict[str, Any] | JSONResponse:
    """Create/read or advance one workflow task from the private UI."""
    if _namespace_is_hidden(payload.namespace_id):
        return _error("Namespace не найден", 404)
    try:
        with SAUnitOfWork() as uow:
            if uow.projects.get_by_id(payload.namespace_id) is None:
                return _error("Namespace не найден", 404)
            return execute_namespace_step(
                uow,
                namespace_id=payload.namespace_id,
                task=payload.task,
                report=payload.report,
                title=payload.title,
            )
    except (ConflictError, RuntimeError, ValueError) as exc:
        return _error(str(exc), 409)


async def api_namespaces() -> dict[str, Any] | JSONResponse:
    from project_workflow.interfaces.ui.services import _load_namespaces

    namespaces = [_with_namespace_aliases(item) for item in _load_namespaces()]
    return {"ok": True, "namespaces": namespaces}


async def api_namespace_get(namespace_id: int) -> dict[str, Any] | JSONResponse:
    if _namespace_is_hidden(namespace_id):
        return _error(f"Запись {namespace_id} не найдена", 404)
    namespace = _app_state.project_service().get_project(namespace_id)
    if namespace is None:
        return _error(f"Запись {namespace_id} не найдена", 404)
    payload = _with_namespace_aliases(namespace)
    return {"ok": True, "namespace": payload}


async def api_projects() -> dict[str, Any] | JSONResponse:
    from project_workflow.interfaces.ui.services import _load_namespaces

    contexts = [_with_namespace_aliases(item) for item in _load_namespaces()]
    return {"ok": True, "namespaces": contexts, "contexts": contexts, "projects": contexts}


async def api_workflows() -> dict[str, Any] | JSONResponse:
    return {"ok": True, "workflows": _load_workflows()}


async def api_agents() -> dict[str, Any] | JSONResponse:
    rows = _load_agents()
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
    if denied := _deny_restricted_catalog_write():
        return denied
    workflow_id = payload.workflow_id
    if _workflow_is_hidden(workflow_id):
        return _error(f"Воркфлоу {workflow_id} не найден", 404)
    if payload.agent_id is not None and _agent_is_hidden(payload.agent_id):
        return _error(f"Агент {payload.agent_id} не найден", 404)
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


async def api_phase_update(phase_id: int, payload: PhaseUpdate) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _phase_is_hidden(phase_id):
        return _error(f"Фаза {phase_id} не найдена", 404)
    if payload.agent_id is not None and _agent_is_hidden(payload.agent_id):
        return _error(f"Агент {payload.agent_id} не найден", 404)
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


async def api_phase_delete(phase_id: int) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _phase_is_hidden(phase_id):
        return _error(f"Фаза {phase_id} не найдена", 404)
    try:
        _app_state.phase_service().delete_phase(phase_id)
    except NotFoundError:
        return _error(f"Фаза {phase_id} не найдена", 404)
    except (ConflictError, LastPhaseError) as exc:
        return _error(str(exc), 409)
    return {"ok": True}


async def api_phase_batch_order(payload: PhaseOrderUpdate) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    batch: list[tuple[int, int]] = []
    for item in payload.orders:
        resolved_phase_id = item.phase_id
        if _phase_is_hidden(resolved_phase_id):
            return _error(f"Фаза {resolved_phase_id} не найдена", 404)
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
    if denied := _deny_restricted_catalog_write():
        return denied
    service = _app_state.workflow_service()
    workflow = service.create_workflow({"name": payload.name, "description": payload.description or ""})
    workflow_id = workflow["id"]
    return {"ok": True, "workflow_id": workflow_id, "workflow": service.get_workflow(workflow_id)}


async def api_workflow_update(workflow_id: int, payload: WorkflowUpdate) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _workflow_is_hidden(workflow_id):
        return _error(f"Воркфлоу {workflow_id} не найден", 404)
    service = _app_state.workflow_service()
    updates = _updates_from_payload(payload, ["name", "description"])
    try:
        service.update_workflow(workflow_id, updates)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return {"ok": True, "workflow": service.get_workflow(workflow_id)}


async def api_workflow_delete(workflow_id: int) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _workflow_is_hidden(workflow_id):
        return _error(f"Воркфлоу {workflow_id} не найден", 404)
    service = _app_state.workflow_service()
    try:
        service.delete_workflow(workflow_id)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return {"ok": True}


async def api_namespace_create(payload: NamespaceCreate) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _workflow_is_hidden(payload.workflow_id):
        return _error(f"Воркфлоу {payload.workflow_id} не найден", 404)
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
                "key_prefixes": list(payload.key_prefixes),
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
        "context_id": namespace_id,
        "context": context,
        "project_id": namespace_id,
        "project": context,
    }


async def api_namespace_update(namespace_id: int, payload: NamespaceUpdate) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _namespace_is_hidden(namespace_id):
        return _error(f"Запись {namespace_id} не найдена", 404)
    if payload.workflow_id is not None and _workflow_is_hidden(payload.workflow_id):
        return _error(f"Воркфлоу {payload.workflow_id} не найден", 404)
    service = _app_state.project_service()
    updates = _updates_from_payload(
        payload,
        ["name", "description", "workflow_id", "theme_icon", "theme_color", "cli_command"],
    )
    if payload.key_prefixes is not None:
        updates["key_prefixes"] = list(payload.key_prefixes)
    try:
        service.update_project(namespace_id, updates)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ValueError as exc:
        return _error(str(exc), 422)
    context = _with_namespace_aliases(service.get_project(namespace_id) or {})
    return {"ok": True, "namespace": context, "context": context, "project": context}


async def api_namespace_delete(namespace_id: int) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _namespace_is_hidden(namespace_id):
        return _error(f"Запись {namespace_id} не найдена", 404)
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


async def api_project_create(payload: ProjectCreate) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _workflow_is_hidden(payload.workflow_id):
        return _error(f"Воркфлоу {payload.workflow_id} не найден", 404)
    if "description" in payload.model_fields_set and payload.description is None:
        return _error("description не может быть null", 422)
    service = _app_state.project_service()
    try:
        project = service.create_project(
            {
                "code": payload.code,
                "name": payload.name,
                "description": payload.description or "",
                "theme_icon": payload.theme_icon,
                "theme_color": payload.theme_color,
                "cli_command": payload.cli_command,
                "key_prefixes": list(payload.key_prefixes),
                "workflow_id": payload.workflow_id,
            }
        )
    except ConflictError as exc:
        return _error(str(exc), 409)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ValueError as exc:
        return _error(str(exc), 422)
    project_id = project["id"]
    context = _with_namespace_aliases(service.get_project(project_id) or project)
    return {
        "ok": True,
        "namespace_id": project_id,
        "namespace": context,
        "context_id": project_id,
        "context": context,
        "project_id": project_id,
        "project": context,
    }


async def api_project_update(project_id: int, payload: ProjectUpdate) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _namespace_is_hidden(project_id):
        return _error(f"Запись {project_id} не найдена", 404)
    if payload.workflow_id is not None and _workflow_is_hidden(payload.workflow_id):
        return _error(f"Воркфлоу {payload.workflow_id} не найден", 404)
    service = _app_state.project_service()
    updates = _updates_from_payload(
        payload,
        ["code", "name", "description", "workflow_id", "theme_icon", "theme_color", "cli_command"],
    )
    if payload.key_prefixes is not None:
        updates["key_prefixes"] = list(payload.key_prefixes)
    try:
        service.update_project(project_id, updates)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ValueError as exc:
        return _error(str(exc), 422)
    context = _with_namespace_aliases(service.get_project(project_id) or {})
    return {"ok": True, "namespace": context, "context": context, "project": context}


async def api_project_delete(project_id: int) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    return await api_namespace_delete(project_id)


async def api_agent_create(payload: AgentCreate) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
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


async def api_agent_update(agent_id: int, payload: AgentUpdate) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _agent_is_hidden(agent_id):
        return _error(f"Агент {agent_id} не найден", 404)
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


async def api_agent_delete(agent_id: int) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _agent_is_hidden(agent_id):
        return _error(f"Агент {agent_id} не найден", 404)
    service = _app_state.agent_service()
    try:
        service.delete_agent(agent_id)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return {"ok": True}


async def api_phase_detail(phase_id: int) -> dict[str, Any] | JSONResponse:
    phase = _load_phase_detail(phase_id)
    if not phase:
        return _error(f"Фаза {phase_id} не найдена", 404)
    return {"ok": True, "phase": phase}


async def api_instructions_list(phase_id: int) -> dict[str, Any] | JSONResponse:
    if _phase_is_hidden(phase_id):
        return _error(f"Фаза {phase_id} не найдена", 404)
    phase = _app_state.phase_service().get_phase(phase_id)
    if phase is None:
        return _error(f"Фаза {phase_id} не найдена", 404)
    instructions = _app_state.instruction_service().list_instructions(phase_id)
    return {"ok": True, "phase": phase, "instructions": instructions}


async def api_instruction_create(payload: InstructionCreate) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _phase_is_hidden(payload.phase_id):
        return _error(f"Фаза {payload.phase_id} не найдена", 404)
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


async def api_instruction_update(instruction_id: int, payload: InstructionUpdate) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _visibility_is_restricted():
        current = _app_state.instruction_service().get_instruction(instruction_id)
        if current is None or _phase_is_hidden(int(current["phase_id"])):
            return _error(f"Инструкция {instruction_id} не найдена", 404)
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


async def api_instruction_delete(instruction_id: int) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _visibility_is_restricted():
        current = _app_state.instruction_service().get_instruction(instruction_id)
        if current is None or _phase_is_hidden(int(current["phase_id"])):
            return _error(f"Инструкция {instruction_id} не найдена", 404)
    try:
        _app_state.instruction_service().delete_instruction(instruction_id)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return {"ok": True}


async def api_instructions_reorder(phase_id: int, payload: InstructionReorder) -> dict[str, Any] | JSONResponse:
    if denied := _deny_restricted_catalog_write():
        return denied
    if _phase_is_hidden(phase_id):
        return _error(f"Фаза {phase_id} не найдена", 404)
    try:
        _app_state.instruction_service().reorder_instructions(phase_id, payload.instruction_ids)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except (TypeError, ValueError) as exc:
        return _error(str(exc), 422)
    return {"ok": True}
