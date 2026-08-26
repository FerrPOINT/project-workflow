"""Atomic transition recording for the five evaluator verdicts."""

from __future__ import annotations

from ..domain.exceptions import ConcurrentTransitionError
from .models import Phase

_VERDICTS = {"pass", "partial", "blocked", "rollback", "delegate"}


def _validate_verdict(verdict: str) -> None:
    if verdict not in _VERDICTS:
        raise ValueError(f"Неподдерживаемый вердикт: {verdict}")


def _task_state(task: dict | None) -> tuple[int, str, str]:
    if not task:
        raise ConcurrentTransitionError("Задача была удалена во время оценки Supervisor")
    task_id = task.get("id")
    current_phase = task.get("current_phase")
    status = task.get("status")
    if (
        not isinstance(task_id, int)
        or isinstance(task_id, bool)
        or task_id <= 0
        or not isinstance(current_phase, str)
        or not current_phase
        or not isinstance(status, str)
        or not status
    ):
        raise ConcurrentTransitionError("Состояние задачи изменилось во время оценки Supervisor")
    return task_id, current_phase, status


def _phase_id(phase: Phase, *, role: str) -> int:
    if not isinstance(phase.id, int) or isinstance(phase.id, bool) or phase.id <= 0:
        raise ConcurrentTransitionError(f"{role} отсутствует в актуальном каталоге")
    return phase.id


def _update_task(db, task_state: tuple[int, str, str], data: dict) -> None:
    task_id, current_phase, status = task_state
    updated = db.tasks.update_if_state(
        task_id,
        current_phase,
        status,
        data,
    )
    if not updated:
        raise ConcurrentTransitionError("Фаза или статус задачи изменились во время оценки Supervisor")


def record_transition(
    *,
    db,
    task,
    phase: Phase,
    verdict: str,
    next_phase: str | None,
    rollback_target: str | None,
    phase_map: dict[str, Phase],
    commit: bool = True,
) -> None:
    """Record a single-phase transition in the DB."""
    _validate_verdict(verdict)
    task_state = _task_state(task)
    task_id = task_state[0]
    phase_id = _phase_id(phase, role="Текущая фаза")
    add_history = db.tasks.add_history
    next_phase_obj = phase_map.get(next_phase) if next_phase else None
    next_phase_id = _phase_id(next_phase_obj, role="Следующая фаза") if next_phase_obj else None
    if next_phase is not None and next_phase_id is None:
        raise ConcurrentTransitionError("Следующая фаза отсутствует в актуальном каталоге")

    if verdict == "pass":
        _update_task(
            db,
            task_state,
            {
                "current_phase": next_phase if next_phase_id else phase.code,
                "status": "active" if next_phase_id else "done",
            },
        )
        add_history(task_id, phase_id, "done")
        if next_phase_id:
            add_history(task_id, next_phase_id, "pending")
    elif verdict == "blocked":
        _update_task(db, task_state, {"current_phase": phase.code, "status": "blocked"})
        add_history(task_id, phase_id, "blocked")
    elif verdict == "rollback":
        target_phase = phase_map.get(rollback_target) if rollback_target else None
        if target_phase is None:
            raise ConcurrentTransitionError("Цель отката отсутствует в актуальном каталоге")
        target_phase_id = _phase_id(target_phase, role="Цель отката")
        _update_task(db, task_state, {"current_phase": target_phase.code, "status": "active"})
        add_history(task_id, phase_id, "rollback")
        add_history(task_id, target_phase_id, "pending")
    elif verdict == "delegate":
        _update_task(db, task_state, {"current_phase": phase.code, "status": "active"})
        add_history(task_id, phase_id, "delegated")
    else:
        _update_task(db, task_state, {"current_phase": phase.code, "status": "active"})
        add_history(task_id, phase_id, "partial")

    if commit:
        db.commit()


def record_parallel_transition(
    *,
    db,
    task,
    group: list[Phase],
    phase_map: dict[str, Phase],
    verdict: str,
    next_phase: str | None,
    rollback_target: str | None = None,
    commit: bool = True,
) -> None:
    """Record a parallel-group transition in the DB."""
    _validate_verdict(verdict)
    task_state = _task_state(task)
    task_id = task_state[0]
    if not group:
        raise ConcurrentTransitionError("Параллельная группа отсутствует в актуальном каталоге")
    group_phase_ids = [_phase_id(phase, role="Фаза параллельной группы") for phase in group]
    add_history = db.tasks.add_history

    if verdict == "pass":
        next_phase_obj = phase_map.get(next_phase) if next_phase else None
        next_phase_id = _phase_id(next_phase_obj, role="Следующая фаза") if next_phase_obj else None
        if next_phase is not None and next_phase_id is None:
            raise ConcurrentTransitionError("Следующая фаза отсутствует в актуальном каталоге")
        target_code = next_phase_obj.code if next_phase_obj else group[-1].code
        _update_task(db, task_state, {"current_phase": target_code, "status": "active" if next_phase else "done"})
        for phase_id in group_phase_ids:
            add_history(task_id, phase_id, "done")
        if next_phase_obj is not None:
            add_history(task_id, next_phase_id, "pending")
    elif verdict == "blocked":
        _update_task(db, task_state, {"current_phase": group[0].code, "status": "blocked"})
        for phase_id in group_phase_ids:
            add_history(task_id, phase_id, "blocked")
    elif verdict == "rollback":
        target_phase = phase_map.get(rollback_target) if rollback_target else None
        if target_phase is None:
            raise ConcurrentTransitionError("Цель отката отсутствует в актуальном каталоге")
        target_phase_id = _phase_id(target_phase, role="Цель отката")
        _update_task(db, task_state, {"current_phase": target_phase.code, "status": "active"})
        for phase_id in group_phase_ids:
            add_history(task_id, phase_id, "rollback")
        add_history(task_id, target_phase_id, "pending")
    elif verdict == "delegate":
        _update_task(db, task_state, {"current_phase": group[0].code, "status": "active"})
        for phase_id in group_phase_ids:
            add_history(task_id, phase_id, "delegated")
    else:
        _update_task(db, task_state, {"current_phase": group[0].code, "status": "active"})
        for phase_id in group_phase_ids:
            add_history(task_id, phase_id, "partial")

    if commit:
        db.commit()
