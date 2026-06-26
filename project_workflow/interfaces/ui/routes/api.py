"""JSON API routes for the workflow UI."""
from __future__ import annotations

from typing import Any

from fastapi import Query
from fastapi.responses import JSONResponse

from project_workflow.infrastructure.db.schema import persist_phase_order_to_seed, persist_phase_update_to_seed
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
from project_workflow.interfaces.ui.seed import _update_config_phase_order
from project_workflow.interfaces.ui.services import _coerce_phase_db_id, _load_phase_detail, _load_tasks
from project_workflow.interfaces.ui.skills import _load_skills_catalog as _load_skills_catalog_direct
from project_workflow.interfaces.ui.state import _app_state


def _error(message: str, status: int) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


async def api_settings_get() -> dict[str, Any] | JSONResponse:
    """Вернуть реестр CLI-команд для UI/интеграций."""
    from project_workflow.interfaces.ui.services import _load_cli_reference

    return {"ok": True, "commands": _load_cli_reference()}


async def api_skills(refresh: int = Query(default=0)) -> dict[str, Any] | JSONResponse:
    return {"ok": True, "skills": _load_skills_catalog_direct(refresh=bool(refresh))}


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


async def api_task_detail(task_key: str) -> dict[str, Any] | JSONResponse:
    from project_workflow.interfaces.ui.services import _get_task_detail

    task = _get_task_detail(task_key)
    if task is None:
        return _error(f"Задача {task_key!r} не найдена", 404)
    return {"ok": True, "task": task}


async def api_task_delete(task_key: str) -> JSONResponse:
    task = _app_state.task_service().get_task_by_key(task_key)
    if task is None:
        return _error(f"Задача {task_key!r} не найдена", 404)
    task_id = task.get("id")
    if not isinstance(task_id, int):
        return _error("Некорректный идентификатор задачи", 400)
    _app_state.task_service().delete_task(task_id)
    return JSONResponse({}, status_code=204)


async def api_projects() -> dict[str, Any] | JSONResponse:
    from project_workflow.interfaces.ui.services import _load_projects

    return {"ok": True, "projects": _load_projects()}


async def api_workflows() -> dict[str, Any] | JSONResponse:
    from project_workflow.interfaces.ui.services import _load_workflows

    return {"ok": True, "workflows": _load_workflows()}


async def api_agents() -> dict[str, Any] | JSONResponse:
    rows = _app_state.agent_service().list_agents()
    return {"ok": True, "agents": [{**agent, "description": agent.get("description", "")} for agent in rows]}


async def api_phase_create(payload: PhaseCreate) -> dict[str, Any] | JSONResponse:
    uow = _app_state.get_db()
    workflow_id = payload.workflow_id
    if workflow_id is None:
        return _error("workflow_id обязателен", 400)
    if payload.phase_order is None:
        return _error("phase_order обязателен", 400)

    resolved_workflow_id: int | None = None
    if isinstance(workflow_id, str) and not workflow_id.isdigit():
        workflow_row = _app_state.workflow_service().get_workflow(int(workflow_id))
        if not workflow_row:
            return _error(f"Workflow {workflow_id!r} не найден", 400)
        resolved_workflow_id = int(workflow_row["id"])
    else:
        resolved_workflow_id = int(workflow_id)
    if resolved_workflow_id is None or not _app_state.workflow_service().get_workflow(resolved_workflow_id):
        return _error(f"Workflow {resolved_workflow_id} не найден", 400)
    workflow_id = resolved_workflow_id

    workflow_phases = _app_state.phase_service().list_phases(workflow_id)
    order_list = sorted([p["phase_order"] for p in workflow_phases if isinstance(p.get("phase_order"), int)])
    new_order = payload.phase_order
    if new_order > (max(order_list, default=0) + 1):
        new_order = (max(order_list, default=0)) + 1

    for p in workflow_phases:
        if isinstance(p.get("phase_order"), int) and p["phase_order"] >= new_order:
            _app_state.phase_service().update_phase(
                p["id"],
                {"phase_order": p["phase_order"] + 1},
            )
    data = {
        "name": payload.name,
        "description": payload.description or "",
        "workflow_id": workflow_id,
        "phase_order": new_order,
        "execution_type": payload.execution_type or "sync",
        "parallel_with": payload.parallel_with,
        "agent_id": payload.agent_id,
    }
    if payload.code:
        data["code"] = payload.code
    phase = _app_state.phase_service().create_phase(data)
    _update_config_phase_order(uow)
    return {"ok": True, "phase_id": phase["id"], "phase_order": new_order, "phase": phase}


async def api_phase_update(phase_id: int, payload: PhaseUpdate) -> dict[str, Any] | JSONResponse:
    srv = _app_state.get_service()
    existing = _load_phase_detail(phase_id)
    if not existing:
        return _error(f"Фаза {phase_id} не найдена", 404)
    resolved_phase_id = _coerce_phase_db_id(phase_id)
    if resolved_phase_id is None:
        return _error(f"Фаза {phase_id} не найдена", 404)

    if payload.phase_num is not None:
        return _error("Редактирование phase_num запрещено", 400)
    if payload.code is not None or payload.phase_order is not None:
        return _error("Редактирование identity/order фазы запрещено", 400)

    phase_data: dict[str, Any] = {}
    for key in (
        "name",
        "description",
        "delegate_agent",
        "delegate_timeout",
        "parallel_with",
        "rollback_target",
        "next_recommendation",
        "agent_id",
        "execution_type",
    ):
        value = getattr(payload, key, None)
        if value is not None:
            phase_data[key] = value
    if phase_data:
        srv.update_phase(resolved_phase_id, phase_data)

    inst_ids: list[int] = []
    check_ids: list[int] = []
    ev_ids: list[int] = []
    if payload.instructions is not None:
        inst_ids = srv.save_instructions(resolved_phase_id, payload.instructions)
    if payload.checks is not None:
        check_ids = srv.save_checks(resolved_phase_id, payload.checks)
    if payload.evidence is not None:
        ev_ids = srv.save_evidence(resolved_phase_id, payload.evidence)

    uow = _app_state.get_db()
    phase = _app_state.phase_service().get_phase(resolved_phase_id)
    if phase:
        persist_phase_update_to_seed(uow, phase["code"], payload.model_dump(exclude_unset=True))

    return {"ok": True, "ids": {"instructions": inst_ids, "checks": check_ids, "evidence": ev_ids}}


async def api_phase_delete(phase_id: int) -> dict[str, Any] | JSONResponse:
    phase = _app_state.phase_service().get_phase(phase_id)
    if not phase:
        return _error(f"Фаза {phase_id} не найдена", 404)
    workflow_id = phase.get("workflow_id")
    workflow_phases = _app_state.phase_service().list_phases(workflow_id)
    if len(workflow_phases) <= 1:
        return _error("Нельзя удалить единственную фазу workflow", 409)
    _app_state.phase_service().delete_phase(phase_id)
    _update_config_phase_order(_app_state.get_db())
    return {"ok": True}


async def api_phase_batch_order(payload: PhaseOrderUpdate) -> dict[str, Any] | JSONResponse:
    uow = _app_state.get_db()
    if not payload.orders:
        return _error("Список order пуст", 400)

    workflow_id: int | None = None
    for item in payload.orders:
        if item.workflow_id is not None:
            workflow_id = item.workflow_id
            break
    if workflow_id is None:
        # Try to infer from the first phase.
        first_id = _coerce_phase_db_id(payload.orders[0].phase_id)
        if first_id is not None:
            phase = _app_state.phase_service().get_phase(first_id)
            if phase:
                workflow_id = phase.get("workflow_id")

    batch: list[tuple[int, int]] = []
    ordered_phase_ids: list[int] = []
    for item in payload.orders:
        resolved_phase_id = _coerce_phase_db_id(item.phase_id)
        if resolved_phase_id is None:
            return _error(f"Некорректный phase_id: {item.phase_id!r}", 400)
        batch.append((resolved_phase_id, item.phase_order))
        ordered_phase_ids.append(resolved_phase_id)

    workflow_phases = _app_state.phase_service().list_phases(workflow_id)
    for phase in workflow_phases:
        if phase["id"] not in ordered_phase_ids:
            batch.append((phase["id"], phase.get("phase_order", 0)))

    for phase_id, new_order in batch:
        _app_state.phase_service().update_phase(phase_id, {"phase_order": new_order})

    if workflow_id is not None:
        ordered_phase_ids = [phase_id for phase_id, _ in batch]
        ordered_phases = []
        for phase_id in ordered_phase_ids:
            phase = _app_state.phase_service().get_phase(phase_id)
            if phase:
                ordered_phases.append(phase)
        persist_phase_order_to_seed(uow, [p["code"] for p in ordered_phases])
    _update_config_phase_order(uow)
    return {"ok": True, "updated": len(payload.orders)}


async def api_workflow_create(payload: WorkflowCreate) -> dict[str, Any] | JSONResponse:
    if not payload.name or not str(payload.name).strip():
        return _error("name required", 400)
    if payload.code:
        return _error("Workflow code field is no longer supported", 400)
    service = _app_state.workflow_service()
    workflow = service.create_workflow({"name": payload.name, "description": payload.description or ""})
    workflow_id = workflow["id"]
    _update_config_phase_order(_app_state.get_db())
    return {"ok": True, "workflow_id": workflow_id, "workflow": service.get_workflow(workflow_id)}


async def api_workflow_update(workflow_id: int, payload: WorkflowUpdate) -> dict[str, Any] | JSONResponse:
    service = _app_state.workflow_service()
    existing = service.get_workflow(workflow_id)
    if not existing:
        return _error(f"Workflow {workflow_id} не найден", 404)
    if payload.code is not None and payload.code != existing.get("code"):
        return _error("Workflow code field is no longer supported", 400)
    updates: dict[str, Any] = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.description is not None:
        updates["description"] = payload.description
    service.update_workflow(workflow_id, updates)
    return {"ok": True, "workflow": service.get_workflow(workflow_id)}


async def api_workflow_delete(workflow_id: int) -> dict[str, Any] | JSONResponse:
    service = _app_state.workflow_service()
    existing = service.get_workflow(workflow_id)
    if not existing:
        return _error(f"Workflow {workflow_id} не найден", 404)
    phases = _app_state.phase_service().list_phases(workflow_id)
    projects = [p for p in _app_state.project_service().list_projects() if p.get("workflow_id") == workflow_id]
    starter_code = f"wf-{workflow_id}-default"
    non_starter_phases = [p for p in phases if p.get("code") != starter_code]
    if non_starter_phases or projects:
        return _error("Нельзя удалить workflow, содержащий проекты или фазы", 409)
    if existing.get("is_default"):
        return _error("Нельзя удалить workflow по умолчанию", 400)
    service.delete_workflow(workflow_id)
    return {"ok": True}


async def api_project_create(payload: ProjectCreate) -> dict[str, Any] | JSONResponse:
    service = _app_state.project_service()
    project = service.create_project(
        {
            "code": payload.code,
            "name": payload.name,
            "description": payload.description or "",
            "key_prefixes": list(payload.key_prefixes) if payload.key_prefixes else [],
            "workflow_id": payload.workflow_id,
        }
    )
    project_id = project["id"]
    return {"ok": True, "project_id": project_id, "project": service.get_project(project_id)}


async def api_project_update(project_id: int, payload: ProjectUpdate) -> dict[str, Any] | JSONResponse:
    service = _app_state.project_service()
    existing = service.get_project(project_id)
    if not existing:
        return _error(f"Проект {project_id} не найден", 404)
    updates: dict[str, Any] = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.description is not None:
        updates["description"] = payload.description
    if payload.key_prefixes is not None:
        updates["key_prefixes"] = list(payload.key_prefixes)
    if payload.workflow_id is not None:
        updates["workflow_id"] = payload.workflow_id
    service.update_project(project_id, updates)
    return {"ok": True, "project": service.get_project(project_id)}


async def api_project_delete(project_id: int) -> dict[str, Any] | JSONResponse:
    tasks = _app_state.task_service().list_tasks()
    if any(t.get("project_id") == project_id for t in tasks):
        return _error("Нельзя удалить проект с задачами", 409)
    service = _app_state.project_service()
    existing = service.get_project(project_id)
    if not existing:
        return _error(f"Проект {project_id} не найден", 404)
    service.delete_project(project_id)
    return {"ok": True}


async def api_agent_create(payload: AgentCreate) -> dict[str, Any] | JSONResponse:
    service = _app_state.agent_service()
    agent_id = service.create_agent({"name": payload.name, "description": payload.description or ""})["id"]
    return {"ok": True, "agent_id": agent_id, "agent": service.get_agent(agent_id)}


async def api_agent_update(agent_id: int, payload: AgentUpdate) -> dict[str, Any] | JSONResponse:
    service = _app_state.agent_service()
    existing = service.get_agent(agent_id)
    if not existing:
        return _error(f"Агент {agent_id} не найден", 404)
    updates: dict[str, Any] = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.description is not None:
        updates["description"] = payload.description
    service.update_agent(agent_id, updates)
    return {"ok": True, "agent": service.get_agent(agent_id)}


async def api_agent_delete(agent_id: int) -> dict[str, Any] | JSONResponse:
    service = _app_state.agent_service()
    existing = service.get_agent(agent_id)
    if not existing:
        return _error(f"Агент {agent_id} не найден", 404)
    phases = _app_state.phase_service().list_phases(None)
    if any(phase.get("agent_id") == agent_id for phase in phases):
        return _error("Нельзя удалить агента, назначенного на фазу", 400)
    service.delete_agent(agent_id)
    return {"ok": True}


async def api_phase_detail(phase_id: str) -> dict[str, Any] | JSONResponse:
    try:
        phase_id_int = int(phase_id)
    except ValueError:
        return _error(f"Phase id {phase_id!r} не найдена", 404)
    phase = _load_phase_detail(phase_id_int)
    if not phase:
        return _error(f"Фаза {phase_id_int} не найдена", 404)
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
    item = _app_state.instruction_service().create_instruction(
        payload.phase_id,
        {
            "description": payload.description,
            "execution_type": payload.execution_type,
            "skills": payload.skills,
        },
    )
    return {"ok": True, "instruction": item}


async def api_instruction_update(instruction_id: int, payload: InstructionUpdate) -> dict[str, Any] | JSONResponse:
    existing = _app_state.instruction_service().get_instruction(instruction_id)
    if existing is None:
        return _error(f"Инструкция {instruction_id} не найдена", 404)
    updates: dict[str, Any] = {}
    if payload.description is not None:
        updates["description"] = payload.description
    if payload.execution_type is not None:
        updates["execution_type"] = payload.execution_type
    if payload.skills is not None:
        skills = payload.skills
        if isinstance(skills, str):
            skills = [s.strip() for s in skills.splitlines() if s.strip()]
        updates["skills"] = skills
    if payload.step_num is not None:
        updates["step_num"] = payload.step_num
    if updates:
        _app_state.instruction_service().update_instruction(instruction_id, updates)
    return {"ok": True, "instruction": _app_state.instruction_service().get_instruction(instruction_id)}


async def api_instruction_update_skills(
    instruction_id: int, payload: dict[str, Any]
) -> dict[str, Any] | JSONResponse:
    existing = _app_state.instruction_service().get_instruction(instruction_id)
    if existing is None:
        return _error(f"Инструкция {instruction_id} не найдена", 404)
    skills = payload.get("skills", [])
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.splitlines() if s.strip()]
    _app_state.instruction_service().update_instruction(instruction_id, {"skills": skills})
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


async def api_task_set_phase(task_key: str, payload: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    task = _app_state.task_service().get_task_by_key(task_key)
    if not task:
        return _error(f"Задача {task_key!r} не найдена", 404)
    phase_code = payload.get("phase")
    if phase_code is None:
        return _error("phase обязателен", 400)
    _app_state.task_service().update_task(task["id"], {"current_phase": str(phase_code)})
    return {"ok": True}
