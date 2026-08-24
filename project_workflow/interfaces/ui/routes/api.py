"""JSON API routes for the workflow UI."""

from __future__ import annotations

from typing import Any

from fastapi import Query, Response
from fastapi.responses import JSONResponse

from project_workflow.domain.exceptions import ConflictError, LastPhaseError, NotFoundError
from project_workflow.interfaces.ui.schemas import (
    AgentCreate,
    AgentUpdate,
    InstructionCreate,
    InstructionReorder,
    InstructionUpdate,
    PhaseCreate,
    PhaseOrderUpdate,
    PhaseUpdate,
    ProjectCreate,
    ProjectUpdate,
    WorkflowCreate,
    WorkflowUpdate,
)
from project_workflow.interfaces.ui.services import _load_phase_detail, _load_tasks
from project_workflow.interfaces.ui.state import _app_state


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _updates_from_payload(payload: Any, fields: list[str]) -> dict[str, Any]:
    """Build updates from explicitly supplied fields, preserving nullable clears."""
    return {key: getattr(payload, key) for key in fields if key in payload.model_fields_set}


async def api_settings_get() -> dict[str, Any] | JSONResponse:
    """Вернуть реестр CLI-команд для UI/интеграций."""
    from project_workflow.interfaces.ui.services import _load_cli_reference

    return {"ok": True, "commands": _load_cli_reference()}


async def api_phases(workflow_id: int | None = Query(default=None)) -> dict[str, Any] | JSONResponse:
    workflows = _app_state.workflow_service().list_workflows()
    selected_workflow = next((item for item in workflows if item["id"] == workflow_id), None)
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
                "parallel_with": phase.get("parallel_with"),
                "agent_name": agent["name"] if agent else None,
                "agent_id": phase.get("agent_id"),
                "hermes_profile": agent.get("hermes_profile") if agent else None,
            }
        )
    result: dict[str, Any] = {"ok": True, "phases": rows}
    if selected_workflow is not None:
        result["workflow"] = selected_workflow
    return result


async def api_tasks(workflow_id: int | None = Query(default=None)) -> dict[str, Any] | JSONResponse:
    tasks = _load_tasks()
    if workflow_id is not None:
        tasks = [t for t in tasks if t.get("workflow_id") == workflow_id]
    return {"ok": True, "tasks": tasks}


async def api_task_delete(task_key: str) -> Response:
    task = _app_state.task_service().get_task_by_key(task_key)
    if task is None:
        return _error(f"Задача {task_key!r} не найдена", 404)
    task_id = task.get("id")
    if not isinstance(task_id, int):
        return _error("Некорректный идентификатор задачи", 400)
    _app_state.task_service().delete_task(task_id)
    return Response(status_code=204)


async def api_projects() -> dict[str, Any] | JSONResponse:
    from project_workflow.interfaces.ui.services import _load_projects

    return {"ok": True, "projects": _load_projects()}


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
        "parallel_with": payload.parallel_with,
        "rollback_target": payload.rollback_target,
        "next_recommendation": payload.next_recommendation,
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
    except ValueError as exc:
        return _error(str(exc), 409)
    return {
        "ok": True,
        "phase_id": phase["id"],
        "phase_order": phase.get("phase_order", payload.phase_order),
        "phase": phase,
    }


async def api_phase_update(phase_id: int, payload: PhaseUpdate) -> dict[str, Any] | JSONResponse:
    srv = _app_state.get_service()
    existing = _load_phase_detail(phase_id)
    if not existing:
        return _error(f"Фаза {phase_id} не найдена", 404)
    resolved_phase_id = phase_id

    scalar_fields = {
        "name",
        "description",
        "parallel_with",
        "rollback_target",
        "next_recommendation",
        "agent_id",
        "execution_type",
    }
    selected_fields = scalar_fields.intersection(payload.model_fields_set)
    phase_data = {field: getattr(payload, field) for field in selected_fields}
    if phase_data:
        try:
            srv.update_phase(resolved_phase_id, phase_data, commit=False)
        except NotFoundError as exc:
            return _error(str(exc), 404)
        except ConflictError as exc:
            return _error(str(exc), 409)

    inst_ids: list[int] = []
    check_ids: list[int] = []
    ev_ids: list[int] = []
    if payload.instructions is not None:
        instructions = [item.model_dump() for item in payload.instructions]
        inst_ids = srv.save_instructions(resolved_phase_id, instructions, commit=False)
    if payload.checks is not None:
        checks = [item.model_dump() for item in payload.checks]
        check_ids = srv.save_checks(resolved_phase_id, checks, commit=False)
    if payload.evidence is not None:
        evidence = [item.model_dump() for item in payload.evidence]
        ev_ids = srv.save_evidence(resolved_phase_id, evidence, commit=False)

    if phase_data or payload.instructions is not None or payload.checks is not None or payload.evidence is not None:
        _app_state.get_uow().commit()

    return {"ok": True, "ids": {"instructions": inst_ids, "checks": check_ids, "evidence": ev_ids}}


async def api_phase_delete(phase_id: int) -> dict[str, Any] | JSONResponse:
    if _app_state.phase_service().get_phase(phase_id) is None:
        return _error(f"Фаза {phase_id} не найдена", 404)
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
        return _error(str(exc), 409)
    return {"ok": True, "updated": updated}


async def api_workflow_create(payload: WorkflowCreate) -> dict[str, Any] | JSONResponse:
    service = _app_state.workflow_service()
    workflow = service.create_workflow({"name": payload.name, "description": payload.description or ""})
    workflow_id = workflow["id"]
    return {"ok": True, "workflow_id": workflow_id, "workflow": service.get_workflow(workflow_id)}


async def api_workflow_update(workflow_id: int, payload: WorkflowUpdate) -> dict[str, Any] | JSONResponse:
    service = _app_state.workflow_service()
    updates = _updates_from_payload(payload, ["name", "description"])
    try:
        service.update_workflow(workflow_id, updates)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    return {"ok": True, "workflow": service.get_workflow(workflow_id)}


async def api_workflow_delete(workflow_id: int) -> dict[str, Any] | JSONResponse:
    service = _app_state.workflow_service()
    try:
        service.delete_workflow(workflow_id)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return {"ok": True}


async def api_project_create(payload: ProjectCreate) -> dict[str, Any] | JSONResponse:
    if "workflow_id" in payload.model_fields_set and payload.workflow_id is None:
        return _error("workflow_id cannot be null", 422)
    if "description" in payload.model_fields_set and payload.description is None:
        return _error("description cannot be null", 422)
    service = _app_state.project_service()
    try:
        project = service.create_project(
            {
                "code": payload.code,
                "name": payload.name,
                "description": payload.description or "",
                "key_prefixes": list(payload.key_prefixes),
                "workflow_id": payload.workflow_id,
            }
        )
    except ConflictError as exc:
        return _error(str(exc), 409)
    except (NotFoundError, ValueError) as exc:
        return _error(str(exc), 404)
    project_id = project["id"]
    return {"ok": True, "project_id": project_id, "project": service.get_project(project_id)}


async def api_project_update(project_id: int, payload: ProjectUpdate) -> dict[str, Any] | JSONResponse:
    service = _app_state.project_service()
    updates = _updates_from_payload(payload, ["code", "name", "description", "workflow_id"])
    if payload.key_prefixes is not None:
        updates["key_prefixes"] = list(payload.key_prefixes)
    try:
        service.update_project(project_id, updates)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except (NotFoundError, ValueError) as exc:
        return _error(str(exc), 404)
    return {"ok": True, "project": service.get_project(project_id)}


async def api_project_delete(project_id: int) -> dict[str, Any] | JSONResponse:
    service = _app_state.project_service()
    try:
        service.delete_project(project_id)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
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
    return {"ok": True, "agent_id": agent_id, "agent": service.get_agent(agent_id)}


async def api_agent_update(agent_id: int, payload: AgentUpdate) -> dict[str, Any] | JSONResponse:
    service = _app_state.agent_service()
    existing = service.get_agent(agent_id)
    if not existing:
        return _error(f"Агент {agent_id} не найден", 404)
    updates = _updates_from_payload(payload, ["name", "description"])
    if "hermes_profile" in payload.model_fields_set:
        updates["hermes_profile"] = payload.hermes_profile
    if updates:
        try:
            service.update_agent(agent_id, updates)
        except ConflictError as exc:
            return _error(str(exc), 409)
    return {"ok": True, "agent": service.get_agent(agent_id)}


async def api_agent_delete(agent_id: int) -> dict[str, Any] | JSONResponse:
    service = _app_state.agent_service()
    existing = service.get_agent(agent_id)
    if not existing:
        return _error(f"Агент {agent_id} не найден", 404)
    phases = _app_state.phase_service().list_phases(None)
    if any(phase.get("agent_id") == agent_id for phase in phases):
        return _error("Нельзя удалить агента, назначенного на фазу", 409)
    service.delete_agent(agent_id)
    return {"ok": True}


async def api_phase_detail(phase_id: int) -> dict[str, Any] | JSONResponse:
    phase = _load_phase_detail(phase_id)
    if not phase:
        return _error(f"Фаза {phase_id} не найдена", 404)
    return {"ok": True, "phase": phase}


async def api_instructions_list(phase_id: int) -> dict[str, Any] | JSONResponse:
    phase = _app_state.phase_service().get_phase(phase_id)
    if phase is None:
        return _error(f"Фаза {phase_id} не найдена", 404)
    instructions = _app_state.instruction_service().list_instructions(phase_id)
    return {"ok": True, "phase": phase, "instructions": instructions}


async def api_instruction_create(payload: InstructionCreate) -> dict[str, Any] | JSONResponse:
    phase = _app_state.phase_service().get_phase(payload.phase_id)
    if phase is None:
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
    except ValueError as exc:
        return _error(str(exc), 422)
    return {"ok": True, "instruction": item}


async def api_instruction_update(instruction_id: int, payload: InstructionUpdate) -> dict[str, Any] | JSONResponse:
    existing = _app_state.instruction_service().get_instruction(instruction_id)
    if existing is None:
        return _error(f"Инструкция {instruction_id} не найдена", 404)
    updates = _updates_from_payload(payload, ["description", "execution_type"])
    if "skills" in payload.model_fields_set:
        updates["skills"] = payload.skills
    if updates:
        _app_state.instruction_service().update_instruction(instruction_id, updates)
    return {"ok": True, "instruction": _app_state.instruction_service().get_instruction(instruction_id)}


async def api_instruction_delete(instruction_id: int) -> dict[str, Any] | JSONResponse:
    existing = _app_state.instruction_service().get_instruction(instruction_id)
    if existing is None:
        return _error(f"Инструкция {instruction_id} не найдена", 404)
    _app_state.instruction_service().delete_instruction(instruction_id)
    return {"ok": True}


async def api_instructions_reorder(phase_id: int, payload: InstructionReorder) -> dict[str, Any] | JSONResponse:
    phase = _app_state.phase_service().get_phase(phase_id)
    if phase is None:
        return _error(f"Фаза {phase_id} не найдена", 404)
    _app_state.instruction_service().reorder_instructions(phase_id, payload.instruction_ids)
    return {"ok": True}


# Alias used by app wiring for the /api/phases/order endpoint.
api_update_order = api_phase_batch_order
