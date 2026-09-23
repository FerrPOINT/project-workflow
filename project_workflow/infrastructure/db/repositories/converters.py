"""Row-to-domain converters shared by repositories."""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from project_workflow.domain import (
    Agent,
    Phase,
    Project,
    Task,
    TaskPhaseEvent,
    TaskRuntimeAssignment,
    TaskStepHistoryEntry,
    Workflow,
    WorkflowMode,
)
from project_workflow.domain.project_theme import normalize_theme_color, normalize_theme_icon
from project_workflow.infrastructure.db import models as m


def _iso(value: _dt.datetime | str | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    return str(value)


def _row_to_phase(row: m.Phase) -> Phase:
    return Phase(
        id=row.id,
        workflow_id=row.workflow_id,
        mode_id=row.mode_id,
        mode_key=row.mode.key if row.mode else None,
        code=row.code,
        name=row.name,
        description=row.description,
        phase_order=row.phase_order,
        agent_id=row.agent_id,
        parallel_with_phase_id=row.parallel_with_phase_id,
        rollback_target_phase_id=row.rollback_target_phase_id,
        execution_type=row.execution_type or "sync",
        workflow_name=row.workflow.name if row.workflow else None,
    )


def _row_to_workflow(row: m.Workflow) -> Workflow:
    return Workflow(
        id=row.id,
        name=row.name,
        description=row.description or "",
        is_default=bool(row.is_default),
        modes=[_row_to_mode(mode) for mode in sorted(row.modes, key=lambda item: item.mode_order)]
    )


def _row_to_mode(row: m.WorkflowMode) -> WorkflowMode:
    return WorkflowMode(
        id=row.id,
        workflow_id=row.workflow_id,
        key=row.key,
        name=row.name,
        mode_order=row.mode_order,
        role_key=row.role_key,
        execution_scope=row.execution_scope,
        tech_workspace_policy=row.tech_workspace_policy,
    )


def _row_to_project(row: m.Project) -> Project:
    raw = row.key_prefixes
    if not isinstance(raw, str):
        raise ValueError("Сохранённое key_prefixes должно быть JSON-массивом строк")
    try:
        prefixes = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Сохранённое key_prefixes содержит некорректный JSON") from exc
    if not isinstance(prefixes, list) or not all(isinstance(prefix, str) for prefix in prefixes):
        raise ValueError("Сохранённое key_prefixes должно быть JSON-массивом строк")
    return Project(
        id=row.id,
        workflow_id=row.workflow_id,
        code=row.code,
        name=row.name,
        description=row.description,
        theme_icon=normalize_theme_icon(row.theme_icon),
        theme_color=normalize_theme_color(row.theme_color),
        cli_command=getattr(row, "cli_command", "") or "",
        key_prefixes=list(prefixes),
        workflow_name=row.workflow.name if row.workflow else None,
    )


def _row_to_task(row: m.Task) -> Task:
    workflow = row.workflow
    if workflow is None:
        raise ValueError(f"Для задачи {row.task_key!r} не найден связанный воркфлоу")
    phase = next((item for item in workflow.phases if item.id == row.current_phase_id), None)
    if phase is None:
        raise ValueError(f"Для задачи {row.task_key!r} не найдена текущая фаза {row.current_phase_id}")
    return Task(
        id=getattr(row, "id", None),
        project_id=row.project_id,
        workflow_id=row.workflow_id,
        mode_id=row.mode_id,
        mode_key=next((item.key for item in workflow.modes if item.id == row.mode_id), "default"),
        cycle_number=row.cycle_number,
        assignment_operation_key=row.assignment_operation_key,
        assignment_revision=row.assignment_revision,
        task_key=row.task_key,
        title=row.title or "",
        description=row.description or "",
        current_phase_id=row.current_phase_id,
        current_phase_code=phase.code,
        current_phase_name=phase.name,
        status=row.status or "active",
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _row_to_runtime_assignment(row: m.TaskRuntimeAssignment) -> TaskRuntimeAssignment:
    try:
        payload = json.loads(row.payload)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Сохранённый payload runtime assignment содержит некорректный JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Сохранённый payload runtime assignment должен быть JSON-объектом")
    try:
        exact_input_refs = json.loads(row.exact_input_refs) if row.exact_input_refs is not None else []
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Сохранённый exact_input_refs runtime assignment содержит некорректный JSON") from exc
    if not isinstance(exact_input_refs, list) or not all(isinstance(item, dict) for item in exact_input_refs):
        raise ValueError("Сохранённый exact_input_refs runtime assignment должен быть JSON-массивом объектов")
    return TaskRuntimeAssignment(
        id=row.id,
        operation_key=row.operation_key,
        task_id=row.task_id,
        project_id=row.project_id,
        workflow_id=row.workflow_id,
        mode_id=row.mode_id,
        mode_key=row.mode.key if row.mode else "default",
        cycle_number=row.cycle_number,
        assignment_revision=row.assignment_revision,
        role_key=row.role_key,
        execution_scope=row.execution_scope,
        business_task_ref=row.business_task_ref,
        root_task_ref=row.root_task_ref,
        work_item_ref=row.work_item_ref,
        task_workspace_ref=row.task_workspace_ref,
        tech_execution_workspace_ref=row.tech_execution_workspace_ref,
        tech_execution_attempt_ref=row.tech_execution_attempt_ref,
        decomposition_revision_ref=row.decomposition_revision_ref,
        stage_revision=row.stage_revision,
        assignment_ref=row.assignment_ref,
        binding_ref=row.binding_ref,
        hermes_run_ref=row.hermes_run_ref,
        workspace_generation=row.workspace_generation,
        lease_generation=row.lease_generation,
        exact_input_refs=exact_input_refs,
        payload=payload,
        created_at=_iso(row.created_at),
    )


def _row_to_agent(row: m.Agent) -> Agent:
    return Agent(
        id=row.id,
        name=row.name,
        description=row.description or "",
        hermes_profile=row.hermes_profile or None,
    )


def _row_to_step_history(row: m.TaskStepHistoryEntry) -> TaskStepHistoryEntry:
    mode = getattr(row, "mode", None)

    def _parse(raw: str | None) -> list[str]:
        if not isinstance(raw, str):
            raise ValueError("Сохранённое поле-список Supervisor должно быть JSON-массивом строк")
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Сохранённое поле-список Supervisor содержит некорректный JSON") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError("Сохранённое поле-список Supervisor должно быть JSON-массивом строк")
        return parsed

    def _parse_obj(raw: str | None) -> dict[str, Any]:
        if not isinstance(raw, str):
            raise ValueError("Сохранённое поле-объект Supervisor должно быть JSON-объектом")
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Сохранённое поле-объект Supervisor содержит некорректный JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Сохранённое поле-объект Supervisor должно быть JSON-объектом")
        return parsed

    return TaskStepHistoryEntry(
        id=row.id,
        task_id=row.task_id,
        workflow_id=row.workflow_id,
        mode_id=row.mode_id,
        mode_key=mode.key if mode is not None else "default",
        cycle_number=row.cycle_number,
        phase_id=row.phase_id,
        verdict=row.verdict,
        worker_report=row.worker_report or "",
        covered_item_ids=_parse(row.covered_item_ids),
        missing_item_ids=_parse(row.missing_item_ids),
        blocker_messages=_parse(row.blocker_messages),
        next_phase_id=row.next_phase_id,
        rollback_phase_id=row.rollback_phase_id,
        replay_fingerprint=row.replay_fingerprint,
        evaluation_snapshot=_parse_obj(row.evaluation_snapshot),
        supervisor_response=_parse_obj(row.supervisor_response),
        created_at=_iso(row.created_at),
    )


def _row_to_phase_event(row: m.TaskPhaseEvent) -> TaskPhaseEvent:
    mode = getattr(row, "mode", None)
    return TaskPhaseEvent(
        id=row.id,
        task_id=row.task_id,
        workflow_id=row.workflow_id,
        mode_id=row.mode_id,
        mode_key=mode.key if mode is not None else "default",
        cycle_number=row.cycle_number,
        phase_id=row.phase_id,
        step_history_id=row.step_history_id,
        event_type=row.event_type,
        occurred_at=_iso(row.occurred_at),
    )
