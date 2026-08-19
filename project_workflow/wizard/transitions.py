"""Atomic transition recording for the five evaluator verdicts."""

from __future__ import annotations

from ..domain.exceptions import ConcurrentTransitionError
from .models import Phase

_VERDICTS = {"pass", "partial", "blocked", "rollback", "delegate"}


def _validate_verdict(verdict: str) -> None:
    if verdict not in _VERDICTS:
        raise ValueError(f"Unsupported verdict: {verdict}")


def _update_task(db, task: dict, data: dict) -> None:
    updated = db.tasks.update_if_state(
        int(task["id"]),
        str(task.get("current_phase") or ""),
        str(task.get("status") or "active"),
        data,
    )
    if not updated:
        raise ConcurrentTransitionError("Task phase or status changed during Wizard evaluation")


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
    if not task:
        return
    task_id = int(task["id"])
    add_history = db.tasks.add_history
    next_phase_obj = phase_map.get(next_phase) if next_phase else None
    next_phase_id = next_phase_obj.id if next_phase_obj else None

    if verdict == "pass":
        _update_task(
            db,
            task,
            {
                "current_phase": next_phase if next_phase_id else phase.code,
                "status": "active" if next_phase_id else "done",
            },
        )
        add_history(task_id, phase.id, "done")
        if next_phase_id:
            add_history(task_id, next_phase_id, "pending")
    elif verdict == "blocked":
        _update_task(db, task, {"current_phase": phase.code, "status": "blocked"})
        add_history(task_id, phase.id, "blocked")
    elif verdict == "rollback":
        target_phase = phase_map.get(rollback_target) if rollback_target else None
        target_id = target_phase.id if target_phase else phase.id
        _update_task(db, task, {"current_phase": rollback_target or phase.code, "status": "active"})
        add_history(task_id, phase.id, "rollback")
        add_history(task_id, target_id, "pending")
    elif verdict == "delegate":
        _update_task(db, task, {"current_phase": phase.code, "status": "active"})
        add_history(task_id, phase.id, "delegated")
    else:
        _update_task(db, task, {"current_phase": phase.code, "status": "active"})
        add_history(task_id, phase.id, "partial")

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
    if not task:
        return
    task_id = int(task["id"])
    add_history = db.tasks.add_history

    if verdict == "pass":
        target_code = next_phase or group[-1].code
        _update_task(db, task, {"current_phase": target_code, "status": "active" if next_phase else "done"})
        for phase in group:
            add_history(task_id, phase.id, "done")
        if next_phase:
            next_phase_obj = phase_map.get(next_phase)
            if next_phase_obj and next_phase_obj.id:
                add_history(task_id, next_phase_obj.id, "pending")
    elif verdict == "blocked":
        _update_task(db, task, {"current_phase": group[0].code, "status": "blocked"})
        for phase in group:
            add_history(task_id, phase.id, "blocked")
    elif verdict == "rollback":
        for phase in group:
            add_history(task_id, phase.id, "rollback")
        target_phase = phase_map.get(rollback_target) if rollback_target else None
        target_code = target_phase.code if target_phase else group[0].code
        _update_task(db, task, {"current_phase": target_code, "status": "active"})
        if target_phase and target_phase.id:
            add_history(task_id, target_phase.id, "pending")
    elif verdict == "delegate":
        _update_task(db, task, {"current_phase": group[0].code, "status": "active"})
        for phase in group:
            add_history(task_id, phase.id, "delegated")
    else:
        _update_task(db, task, {"current_phase": group[0].code, "status": "active"})
        for phase in group:
            add_history(task_id, phase.id, "partial")

    if commit:
        db.commit()
