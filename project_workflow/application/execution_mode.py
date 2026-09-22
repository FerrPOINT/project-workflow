"""Strict, non-prompt execution selection for Business/adapter callers."""

from __future__ import annotations

import os
from dataclasses import dataclass

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork

MODE_ENV = "PROJECT_WORKFLOW_MODE_KEY"
CYCLE_ENV = "PROJECT_WORKFLOW_CYCLE_NUMBER"


@dataclass(frozen=True)
class ExecutionSelection:
    mode_id: int
    mode_key: str
    cycle_number: int


def resolve_execution_selection(uow: UnitOfWork, workflow_id: int, *, mode_key: str | None = None,
                                cycle_number: int | None = None, use_environment: bool = True) -> ExecutionSelection:
    """Resolve the exact Business-provided mode, with default only when omitted."""
    env_mode = os.environ.get(MODE_ENV) if use_environment else None
    if env_mode is not None and not env_mode.strip():
        raise ValueError(f"{MODE_ENV} не может быть пустым")
    normalized_env_mode = env_mode.strip() if env_mode is not None else None
    if mode_key is not None and normalized_env_mode is not None and mode_key != normalized_env_mode:
        raise ConflictError("Явный mode_key не совпадает с Business selection в PROJECT_WORKFLOW_MODE_KEY")
    selected_key = mode_key if mode_key is not None else (normalized_env_mode or "default")
    if not selected_key:
        raise ValueError(f"{MODE_ENV} не может быть пустым")
    mode = uow.workflows.get_mode_by_key(workflow_id, selected_key)
    if mode is None or mode.id is None:
        raise ConflictError(f"Режим {selected_key!r} не найден в воркфлоу {workflow_id}")
    env_cycle = os.environ.get(CYCLE_ENV) if use_environment else None
    if env_cycle is not None and not env_cycle.strip():
        raise ValueError(f"{CYCLE_ENV} должен содержать целое число >= 0")
    normalized_env_cycle = env_cycle.strip() if env_cycle is not None else None
    if cycle_number is not None and normalized_env_cycle is not None and str(cycle_number) != normalized_env_cycle:
        raise ConflictError("Явный cycle_number не совпадает с Business selection в PROJECT_WORKFLOW_CYCLE_NUMBER")
    raw_cycle = cycle_number if cycle_number is not None else (normalized_env_cycle or "0")
    if isinstance(raw_cycle, bool):
        raise ValueError(f"{CYCLE_ENV} должен содержать целое число >= 0")
    try:
        resolved_cycle = int(raw_cycle)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{CYCLE_ENV} должен содержать целое число >= 0") from exc
    if resolved_cycle < 0 or isinstance(resolved_cycle, bool):
        raise ValueError(f"{CYCLE_ENV} должен содержать целое число >= 0")
    return ExecutionSelection(int(mode.id), mode.key, resolved_cycle)


def assert_phase_in_selection(uow: UnitOfWork, phase_id: int, selection: ExecutionSelection, workflow_id: int) -> None:
    phase = uow.phases.get_by_id(phase_id)
    if phase is None:
        raise NotFoundError(f"Фаза {phase_id} не найдена")
    if phase.workflow_id != workflow_id or phase.mode_id != selection.mode_id:
        raise ConflictError("Фаза не принадлежит выбранному режиму воркфлоу")
