"""Strict, non-prompt execution selection for Business/adapter callers."""

from __future__ import annotations

from dataclasses import dataclass

from project_workflow.domain.exceptions import ConflictError, NotFoundError
from project_workflow.domain.repositories import UnitOfWork


@dataclass(frozen=True)
class ExecutionSelection:
    mode_id: int
    mode_key: str
    cycle_number: int


def resolve_execution_selection(
    uow: UnitOfWork,
    workflow_id: int,
    *,
    mode_key: str | None = None,
    cycle_number: int | None = None,
) -> ExecutionSelection:
    """Resolve a persisted/default technical selection; never inspect process env."""
    selected_key = mode_key or "default"
    mode = uow.workflows.get_mode_by_key(workflow_id, selected_key)
    if mode is None or mode.id is None:
        raise ConflictError(f"Режим {selected_key!r} не найден в воркфлоу {workflow_id}")
    raw_cycle = cycle_number if cycle_number is not None else 0
    if isinstance(raw_cycle, bool):
        raise ValueError("cycle_number должен содержать целое число >= 0")
    try:
        resolved_cycle = int(raw_cycle)
    except (TypeError, ValueError) as exc:
        raise ValueError("cycle_number должен содержать целое число >= 0") from exc
    if resolved_cycle < 0 or isinstance(resolved_cycle, bool):
        raise ValueError("cycle_number должен содержать целое число >= 0")
    return ExecutionSelection(int(mode.id), mode.key, resolved_cycle)


def assert_phase_in_selection(uow: UnitOfWork, phase_id: int, selection: ExecutionSelection, workflow_id: int) -> None:
    phase = uow.phases.get_by_id(phase_id)
    if phase is None:
        raise NotFoundError(f"Фаза {phase_id} не найдена")
    if phase.workflow_id != workflow_id or phase.mode_id != selection.mode_id:
        raise ConflictError("Фаза не принадлежит выбранному режиму воркфлоу")
