"""JSON API routes for the workflow UI."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import Path, Query
from fastapi.responses import JSONResponse

from project_workflow.domain.exceptions import ConflictError, LastPhaseError, NotFoundError
from project_workflow.domain.namespace import legacy_code_from_cli_command
from project_workflow.domain.project_theme import normalize_theme_color, normalize_theme_icon
from project_workflow.interfaces.ui.helpers import _select_workflow_mode
from project_workflow.interfaces.ui.schemas import (
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
PositiveQueryId = Annotated[int | None, Query(gt=0)]


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
        "launch_profile": item.get("launch_profile"),
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


def _phase_namespace_scope_error(phase_id: int, namespace_id: int | None) -> JSONResponse | None:
    if namespace_id is None:
        return None
    namespace = _app_state.project_service().get_project(namespace_id)
    if namespace is None:
        return _error(f"Профессия {namespace_id} не найдена", 404)
    phase = _app_state.phase_service().get_phase(phase_id)
    if phase is None:
        return _error(f"Фаза {phase_id} не найдена", 404)
    if not _app_state.workflow_service().belongs_to_profession(phase["workflow_id"], namespace_id):
        return _error("Фаза недоступна в выбранной профессии", 409)
    return None


def _instruction_namespace_scope_error(instruction_id: int, namespace_id: int | None) -> JSONResponse | None:
    if namespace_id is None:
        return None
    namespace = _app_state.project_service().get_project(namespace_id)
    if namespace is None:
        return _error(f"Профессия {namespace_id} не найдена", 404)
    instruction = _app_state.instruction_service().get_instruction(instruction_id)
    if instruction is None:
        return _error(f"Инструкция {instruction_id} не найдена", 404)
    phase_id = instruction.get("phase_id")
    if not isinstance(phase_id, int) or isinstance(phase_id, bool):
        return _error(f"Инструкция {instruction_id} не найдена", 404)
    phase = _app_state.phase_service().get_phase(phase_id)
    if phase is None:
        return _error(f"Фаза {phase_id} не найдена", 404)
    if not _app_state.workflow_service().belongs_to_profession(phase["workflow_id"], namespace_id):
        return _error("Фаза недоступна в выбранной профессии", 409)
    return None


def _effective_phase_view(phase: dict[str, Any], namespace_id: int | None) -> dict[str, Any] | None:
    """Expose the actual sealed phase only for a verified installed binding."""
    from project_workflow.infrastructure.db.schema import load_phases_from_db
    from project_workflow.infrastructure.db.single_task_catalog import observe_installation

    if namespace_id is None:
        return None
    uow = _app_state.get_uow()
    workflow = uow.workflows.get_by_id(phase["workflow_id"])
    if workflow is None or workflow.key != "single-task-v1:project_manager":
        return None
    # A workflow key is only a hint. The sealed binding and mode membership are authority.
    installation = observe_installation(uow)
    binding = next((item for item in installation.bindings
                    if item.role_key == "project_manager" and int(item.namespace_id) == namespace_id
                    and int(item.workflow_id) == phase["workflow_id"]), None)
    mode = uow.workflows.get_mode(phase["mode_id"], workflow.id) if binding else None
    if mode is None or mode.key != "draft":
        raise ValueError("Configured PM phase is outside the installed namespace/mode")
    from project_workflow.application.catalog_publication import read_revision

    read_revision(uow, workflow, mode.catalog_version)
    projected = load_phases_from_db(
        uow, workflow_id=phase["workflow_id"], mode_id=mode.id,
        profession_settings=_app_state.project_service().get_project(namespace_id),
    )
    effective = next((item for item in projected if item.id == phase["id"]), None)
    if effective is None:
        raise ValueError("Configured PM phase is unavailable")
    return {"interaction_protocol": "configured-cli-v1", "namespace_id": namespace_id,
            "read_only": True, "phase": asdict(effective)}


def _pm_workflow_write_error(workflow_id: int) -> JSONResponse | None:
    workflow = _app_state.get_uow().workflows.get_by_id(workflow_id)
    if workflow is not None and isinstance(workflow.key, str) and workflow.key.startswith("single-task-v1:"):
        # Refuse even if the catalog already drifted; a raw save is not a publisher.
        message = ("Configured PM catalog is historical/read-only" if workflow.key == "single-task-v1:project_manager"
                   else "Configured catalog is historical/read-only; use explicit revision publication")
        return _error(message, 409)
    return None


def _pm_phase_write_error(phase_id: int) -> JSONResponse | None:
    phase = _app_state.phase_service().get_phase(phase_id)
    return _pm_workflow_write_error(phase["workflow_id"]) if phase else None


def _pm_instruction_write_error(instruction_id: int) -> JSONResponse | None:
    instruction = _app_state.instruction_service().get_instruction(instruction_id)
    return _pm_phase_write_error(instruction["phase_id"]) if instruction else None


def api_settings_get(namespace_id: int | None = Query(default=None, gt=0)) -> dict[str, Any] | JSONResponse:
    """Вернуть реестр CLI-команд для UI/интеграций."""
    from project_workflow.interfaces.ui.services import _load_cli_reference

    entrypoint = None
    if namespace_id is not None:
        namespace = _app_state.project_service().get_project(namespace_id)
        if namespace is None:
            return _error(f"Профессия {namespace_id} не найдена", 404)
        entrypoint = namespace.get("cli_command")
    return {"ok": True, "commands": _load_cli_reference(entrypoint=entrypoint)}


def api_phases(
    workflow_id: int | None = Query(default=None, gt=0),
    mode_id: int | None = Query(default=None, gt=0),
    namespace_id: int | None = Query(default=None, gt=0),
) -> dict[str, Any] | JSONResponse:
    namespace = _app_state.project_service().get_project(namespace_id) if namespace_id is not None else None
    if namespace_id is not None and namespace is None:
        return _error(f"Профессия {namespace_id} не найдена", 404)
    service = _app_state.workflow_service()
    if namespace_id is not None and workflow_id is not None:
        if error := _workflow_profession_scope_error(workflow_id, namespace_id):
            return error
    workflows = service.list_workflows(namespace_id)
    if namespace_id is not None and not workflows:
        return {"ok": True, "phases": []}
    selected_workflow = next((item for item in workflows if item["id"] == workflow_id), None)
    if workflow_id is not None and selected_workflow is None:
        return _error(f"Воркфлоу {workflow_id} не найден", 404)
    if selected_workflow is None and workflow_id is None and workflows:
        selected_workflow = workflows[0]
    selected_workflow_id = selected_workflow["id"] if selected_workflow else workflow_id
    modes, selected_mode = _select_workflow_mode(selected_workflow, mode_id)
    if mode_id is not None and selected_mode is None:
        return _error("Режим не найден в выбранном воркфлоу", 404)
    if selected_workflow is not None and selected_mode is None:
        return _error("В выбранном воркфлоу не настроен ни один режим", 409)
    selected_mode_id = selected_mode.get("id") if selected_mode else None
    phases = _app_state.phase_service().list_phases(selected_workflow_id, mode_id=selected_mode_id)

    rows = []
    for phase in phases:
        rows.append(
            {
                "id": phase["id"],
                "name": phase["name"],
                "description": phase.get("description", ""),
                "code": phase.get("code", ""),
                "workflow_id": phase.get("workflow_id"),
                "mode_id": phase.get("mode_id"),
                "mode_key": phase.get("mode_key"),
                "phase_num": phase.get("phase_num", phase.get("phase_order", 0)),
                "phase_order": phase.get("phase_order", 0),
                "execution_type": phase.get("execution_type", "sync"),
            }
        )
    result: dict[str, Any] = {"ok": True, "phases": rows}
    if selected_workflow is not None:
        result["workflow"] = selected_workflow
        result["modes"] = modes
        result["mode"] = selected_mode
    return result


def api_tasks(
    workflow_id: int | None = Query(default=None, gt=0),
    namespace_id: int | None = Query(default=None, gt=0),
) -> dict[str, Any] | JSONResponse:
    namespace = _app_state.project_service().get_project(namespace_id) if namespace_id is not None else None
    if namespace_id is not None and namespace is None:
        return _error(f"Профессия {namespace_id} не найдена", 404)
    workflow = _app_state.workflow_service().get_workflow(workflow_id) if workflow_id is not None else None
    if workflow_id is not None and workflow is None:
        return _error(f"Воркфлоу {workflow_id} не найден", 404)
    if namespace is not None and workflow_id is not None and namespace.get("workflow_id") != workflow_id:
        return _error("workflow_id не совпадает с владельцем профессии", 409)
    try:
        tasks = _load_tasks(namespace_id=namespace_id)
    except ValueError as exc:
        return _error(str(exc), 409)
    if workflow_id is not None:
        tasks = [t for t in tasks if t.get("workflow_id") == workflow_id]
    return {"ok": True, "tasks": tasks}


def api_namespaces() -> dict[str, Any] | JSONResponse:
    from project_workflow.interfaces.ui.services import _load_namespaces

    namespaces = [_with_namespace_aliases(item) for item in _load_namespaces()]
    return {"ok": True, "namespaces": namespaces}


def api_namespace_get(namespace_id: PositivePathId) -> dict[str, Any] | JSONResponse:
    namespace = _app_state.project_service().get_project(namespace_id)
    if namespace is None:
        return _error(f"Профессия {namespace_id} не найдена", 404)
    payload = _with_namespace_aliases(namespace)
    return {"ok": True, "namespace": payload}

def api_workflows(namespace_id: PositiveQueryId = None) -> dict[str, Any] | JSONResponse:
    from project_workflow.interfaces.ui.services import _load_workflows

    if namespace_id is not None and _app_state.project_service().get_project(namespace_id) is None:
        return _error(f"Профессия {namespace_id} не найдена", 404)
    return {"ok": True, "workflows": _load_workflows(namespace_id)}


def api_phase_create(payload: PhaseCreate) -> dict[str, Any] | JSONResponse:
    workflow_id = payload.workflow_id
    if error := _pm_workflow_write_error(workflow_id):
        return error
    assert payload.phase_order is not None
    data = {
        "name": payload.name,
        "description": payload.description,
        "workflow_id": workflow_id,
        "mode_id": payload.mode_id,
        "phase_order": payload.phase_order,
        "execution_type": payload.execution_type,
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


def api_phase_update(
    phase_id: PositivePathId,
    payload: PhaseUpdate,
    namespace_id: PositiveQueryId = None,
) -> dict[str, Any] | JSONResponse:
    if error := _phase_namespace_scope_error(phase_id, namespace_id):
        return error
    if error := _pm_phase_write_error(phase_id):
        return error
    srv = _app_state.get_service()
    scalar_fields = {
        "name",
        "description",
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


def api_phase_delete(
    phase_id: PositivePathId,
    namespace_id: PositiveQueryId = None,
) -> dict[str, Any] | JSONResponse:
    if error := _phase_namespace_scope_error(phase_id, namespace_id):
        return error
    if error := _pm_phase_write_error(phase_id):
        return error
    try:
        _app_state.phase_service().delete_phase(phase_id)
    except NotFoundError:
        return _error(f"Фаза {phase_id} не найдена", 404)
    except (ConflictError, LastPhaseError) as exc:
        return _error(str(exc), 409)
    return {"ok": True}


def api_phase_batch_order(payload: PhaseOrderUpdate) -> dict[str, Any] | JSONResponse:
    batch: list[tuple[int, int]] = []
    for item in payload.orders:
        resolved_phase_id = item.phase_id
        if error := _pm_phase_write_error(resolved_phase_id):
            return error
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


def api_workflow_create(
    payload: WorkflowCreate, namespace_id: PositiveQueryId = None,
) -> dict[str, Any] | JSONResponse:
    service = _app_state.workflow_service()
    try:
        workflow = service.create_workflow({
            "name": payload.name, "description": payload.description or "", "profession_id": namespace_id,
        })
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except ValueError as exc:
        return _error(str(exc), 422)
    workflow_id = workflow["id"]
    return {"ok": True, "workflow_id": workflow_id, "workflow": service.get_workflow(workflow_id)}


def _workflow_profession_scope_error(workflow_id: int, namespace_id: int | None) -> JSONResponse | None:
    if namespace_id is None:
        return None
    if _app_state.project_service().get_project(namespace_id) is None:
        return _error(f"Профессия {namespace_id} не найдена", 404)
    if _app_state.workflow_service().get_workflow(workflow_id) is None:
        return _error(f"Воркфлоу {workflow_id} не найден", 404)
    if not _app_state.workflow_service().belongs_to_profession(workflow_id, namespace_id):
        return _error("Воркфлоу не принадлежит выбранной профессии", 409)
    return None


def api_workflow_update(
    workflow_id: PositivePathId, payload: WorkflowUpdate, namespace_id: PositiveQueryId = None,
) -> dict[str, Any] | JSONResponse:
    if error := _workflow_profession_scope_error(workflow_id, namespace_id):
        return error
    if error := _pm_workflow_write_error(workflow_id):
        return error
    service = _app_state.workflow_service()
    updates = _updates_from_payload(payload, ["name", "description"])
    try:
        service.update_workflow(workflow_id, updates)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except ValueError as exc:
        return _error(str(exc), 422)
    return {"ok": True, "workflow": service.get_workflow(workflow_id)}


def api_workflow_delete(
    workflow_id: PositivePathId, namespace_id: PositiveQueryId = None,
) -> dict[str, Any] | JSONResponse:
    if error := _workflow_profession_scope_error(workflow_id, namespace_id):
        return error
    if error := _pm_workflow_write_error(workflow_id):
        return error
    service = _app_state.workflow_service()
    try:
        service.delete_workflow(workflow_id)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return {"ok": True}


def api_namespace_create(payload: NamespaceCreate) -> dict[str, Any] | JSONResponse:
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
                "launch_profile": payload.launch_profile,
                **({"workflow_id": payload.workflow_id} if "workflow_id" in payload.model_fields_set else {}),
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


def api_namespace_update(namespace_id: PositivePathId, payload: NamespaceUpdate) -> dict[str, Any] | JSONResponse:
    service = _app_state.project_service()
    updates = _updates_from_payload(
        payload,
        ["name", "description", "workflow_id", "theme_icon", "theme_color", "cli_command",
         "launch_profile"],
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


def api_namespace_delete(namespace_id: PositivePathId) -> dict[str, Any] | JSONResponse:
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


def api_phase_detail(
    phase_id: PositivePathId,
    namespace_id: PositiveQueryId = None,
) -> dict[str, Any] | JSONResponse:
    if error := _phase_namespace_scope_error(phase_id, namespace_id):
        return error
    phase = _load_phase_detail(phase_id)
    if not phase:
        return _error(f"Фаза {phase_id} не найдена", 404)
    try:
        effective = _effective_phase_view(phase, namespace_id)
    except ValueError:
        return _error("Configured PM catalog validation failed", 409)
    return {"ok": True, "phase": phase, **({"effective_view": effective} if effective is not None else {})}


def api_instructions_list(
    phase_id: PositivePathId,
    namespace_id: PositiveQueryId = None,
) -> dict[str, Any] | JSONResponse:
    if error := _phase_namespace_scope_error(phase_id, namespace_id):
        return error
    phase = _app_state.phase_service().get_phase(phase_id)
    if phase is None:
        return _error(f"Фаза {phase_id} не найдена", 404)
    instructions = _app_state.instruction_service().list_instructions(phase_id)
    try:
        effective = _effective_phase_view(phase, namespace_id)
    except ValueError:
        return _error("Configured PM catalog validation failed", 409)
    return {"ok": True, "phase": phase, "instructions": instructions,
            **({"effective_view": effective} if effective is not None else {})}


def api_instruction_create(
    payload: InstructionCreate,
    namespace_id: PositiveQueryId = None,
) -> dict[str, Any] | JSONResponse:
    if error := _phase_namespace_scope_error(payload.phase_id, namespace_id):
        return error
    if error := _pm_phase_write_error(payload.phase_id):
        return error
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


def api_instruction_update(
    instruction_id: PositivePathId,
    payload: InstructionUpdate,
    namespace_id: PositiveQueryId = None,
) -> dict[str, Any] | JSONResponse:
    if error := _instruction_namespace_scope_error(instruction_id, namespace_id):
        return error
    if error := _pm_instruction_write_error(instruction_id):
        return error
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


def api_instruction_delete(
    instruction_id: PositivePathId,
    namespace_id: PositiveQueryId = None,
) -> dict[str, Any] | JSONResponse:
    if error := _instruction_namespace_scope_error(instruction_id, namespace_id):
        return error
    if error := _pm_instruction_write_error(instruction_id):
        return error
    try:
        _app_state.instruction_service().delete_instruction(instruction_id)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    return {"ok": True}


def api_instructions_reorder(
    phase_id: PositivePathId,
    payload: InstructionReorder,
    namespace_id: PositiveQueryId = None,
) -> dict[str, Any] | JSONResponse:
    if error := _phase_namespace_scope_error(phase_id, namespace_id):
        return error
    if error := _pm_phase_write_error(phase_id):
        return error
    try:
        _app_state.instruction_service().reorder_instructions(phase_id, payload.instruction_ids)
    except NotFoundError as exc:
        return _error(str(exc), 404)
    except ConflictError as exc:
        return _error(str(exc), 409)
    except (TypeError, ValueError) as exc:
        return _error(str(exc), 422)
    return {"ok": True}
