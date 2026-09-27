"""Atomic task snapshot and append-only phase-event transitions."""

from __future__ import annotations

from ..domain.exceptions import ConcurrentTransitionError
from ..domain.runtime_assignment import RuntimeStepFence
from .models import Phase

_VERDICTS = {"pass", "partial", "blocked", "rollback", "delegate"}


def _validate_verdict(verdict: str) -> None:
    if verdict not in _VERDICTS:
        raise ValueError(f"Неподдерживаемый вердикт: {verdict}")


def _task_state(
    task: dict | None, runtime_fence: RuntimeStepFence | None = None
) -> tuple[int, int, str]:
    if not task:
        raise ConcurrentTransitionError("Задача отсутствует во время оценки Supervisor")
    if runtime_fence is not None:
        try:
            runtime_fence.assert_task(task)
        except ValueError as exc:
            raise ConcurrentTransitionError(str(exc)) from exc
    task_id = task.get("id")
    current_phase_id = task.get("current_phase_id")
    status = task.get("status")
    if (
        not isinstance(task_id, int)
        or isinstance(task_id, bool)
        or task_id <= 0
        or not isinstance(current_phase_id, int)
        or isinstance(current_phase_id, bool)
        or current_phase_id <= 0
        or not isinstance(status, str)
        or not status
    ):
        raise ConcurrentTransitionError("Состояние задачи изменилось во время оценки Supervisor")
    return task_id, current_phase_id, status


def _phase_id(phase: Phase | None, *, role: str) -> int:
    phase_id = phase.id if phase is not None else None
    if not isinstance(phase_id, int) or isinstance(phase_id, bool) or phase_id <= 0:
        raise ConcurrentTransitionError(f"{role} отсутствует в актуальном каталоге")
    return phase_id


def _update_task(
    db,
    task_state: tuple[int, int, str],
    data: dict,
    runtime_fence: RuntimeStepFence | None = None,
) -> None:
    task_id, current_phase_id, status = task_state
    fence_kwargs = {}
    if runtime_fence is not None:
        fence_kwargs = {
            "expected_assignment_revision": runtime_fence.assignment_revision,
            "expected_assignment_operation_key": runtime_fence.assignment_operation_key,
            "expected_mode_id": runtime_fence.mode_id,
            "expected_cycle_number": runtime_fence.cycle_number,
        }
    if not db.tasks.update_if_state(
        task_id, current_phase_id, status, data, **fence_kwargs
    ):
        raise ConcurrentTransitionError("Фаза или статус задачи изменились во время оценки Supervisor")


def _record_resume_events(
    db, task_state: tuple[int, int, str], phase_ids: list[int], step_history_id: int
) -> None:
    if task_state[2] != "blocked":
        return
    for phase_id in phase_ids:
        db.tasks.record_phase_event(
            task_state[0], phase_id, "resumed", step_history_id=step_history_id
        )


def record_transition(
    *,
    db,
    task,
    phase: Phase,
    verdict: str,
    next_phase_code: str | None,
    rollback_phase_code: str | None,
    phase_map: dict[str, Phase],
    step_history_id: int,
    runtime_fence: RuntimeStepFence | None = None,
    commit: bool = True,
) -> None:
    """Persist one evaluated phase, its event(s), and the task snapshot."""
    _validate_verdict(verdict)
    task_state = _task_state(task, runtime_fence)
    task_id = task_state[0]
    phase_id = _phase_id(phase, role="Текущая фаза")
    next_phase = phase_map.get(next_phase_code) if next_phase_code else None
    if next_phase_code is not None and next_phase is None:
        raise ConcurrentTransitionError("Следующая фаза отсутствует в актуальном каталоге")
    next_phase_id = _phase_id(next_phase, role="Следующая фаза") if next_phase else None

    if verdict != "blocked":
        _record_resume_events(db, task_state, [phase_id], step_history_id)

    if verdict == "pass":
        _update_task(
            db,
            task_state,
            {
                "current_phase_id": next_phase_id or phase_id,
                "status": "active" if next_phase_id else "done",
            },
            runtime_fence,
        )
        db.tasks.record_phase_event(task_id, phase_id, "completed", step_history_id)
        if next_phase_id is not None:
            db.tasks.record_phase_event(task_id, next_phase_id, "entered", step_history_id)
    elif verdict == "blocked":
        _update_task(
            db,
            task_state,
            {"current_phase_id": phase_id, "status": "blocked"},
            runtime_fence,
        )
        db.tasks.record_phase_event(task_id, phase_id, "blocked", step_history_id)
    elif verdict == "rollback":
        rollback_phase = phase_map.get(rollback_phase_code) if rollback_phase_code else None
        rollback_phase_id = _phase_id(rollback_phase, role="Цель отката")
        _update_task(
            db,
            task_state,
            {"current_phase_id": rollback_phase_id, "status": "active"},
            runtime_fence,
        )
        db.tasks.record_phase_event(task_id, phase_id, "rolled_back", step_history_id)
        db.tasks.record_phase_event(task_id, rollback_phase_id, "entered", step_history_id)
    else:
        _update_task(
            db,
            task_state,
            {"current_phase_id": phase_id, "status": "active"},
            runtime_fence,
        )

    if commit:
        db.commit()


def record_parallel_transition(
    *,
    db,
    task,
    group: list[Phase],
    phase_map: dict[str, Phase],
    verdict: str,
    next_phase_code: str | None,
    rollback_phase_code: str | None = None,
    step_history_id: int,
    runtime_fence: RuntimeStepFence | None = None,
    commit: bool = True,
) -> None:
    """Persist one evaluated parallel group and its append-only events."""
    _validate_verdict(verdict)
    if not group:
        raise ConcurrentTransitionError("Параллельная группа отсутствует в актуальном каталоге")
    task_state = _task_state(task, runtime_fence)
    task_id = task_state[0]
    group_phase_ids = [_phase_id(phase, role="Фаза параллельной группы") for phase in group]
    representative_phase_id = group_phase_ids[0]

    if verdict != "blocked":
        _record_resume_events(db, task_state, group_phase_ids, step_history_id)

    if verdict == "pass":
        next_phase = phase_map.get(next_phase_code) if next_phase_code else None
        if next_phase_code is not None and next_phase is None:
            raise ConcurrentTransitionError("Следующая фаза отсутствует в актуальном каталоге")
        next_phase_id = _phase_id(next_phase, role="Следующая фаза") if next_phase else None
        _update_task(
            db,
            task_state,
            {
                "current_phase_id": next_phase_id or representative_phase_id,
                "status": "active" if next_phase_id else "done",
            },
            runtime_fence,
        )
        for phase_id in group_phase_ids:
            db.tasks.record_phase_event(task_id, phase_id, "completed", step_history_id)
        if next_phase_id is not None:
            db.tasks.record_phase_event(task_id, next_phase_id, "entered", step_history_id)
    elif verdict == "blocked":
        _update_task(
            db,
            task_state,
            {"current_phase_id": representative_phase_id, "status": "blocked"},
            runtime_fence,
        )
        for phase_id in group_phase_ids:
            db.tasks.record_phase_event(task_id, phase_id, "blocked", step_history_id)
    elif verdict == "rollback":
        rollback_phase = phase_map.get(rollback_phase_code) if rollback_phase_code else None
        rollback_phase_id = _phase_id(rollback_phase, role="Цель отката")
        _update_task(
            db,
            task_state,
            {"current_phase_id": rollback_phase_id, "status": "active"},
            runtime_fence,
        )
        for phase_id in group_phase_ids:
            db.tasks.record_phase_event(task_id, phase_id, "rolled_back", step_history_id)
        db.tasks.record_phase_event(task_id, rollback_phase_id, "entered", step_history_id)
    else:
        _update_task(
            db,
            task_state,
            {"current_phase_id": representative_phase_id, "status": "active"},
            runtime_fence,
        )

    if commit:
        db.commit()
