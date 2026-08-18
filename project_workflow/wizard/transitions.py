"""FSM-based transition recording for wizard phase evaluation."""

from __future__ import annotations

from ..domain.fsm import PhaseFSM
from .models import Phase


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
    """Record a single-phase FSM transition in the DB.

    ``db`` is the engine's ``.db`` UoW accessor (accepts both real UoW and test mocks).
    """
    fsm = PhaseFSM(initial="in_progress")
    fsm.apply_verdict(verdict)
    new_state = fsm.state
    if not task:
        return
    task_id = int(task["id"])
    add_history = db.add_task_history if commit else db.tasks.add_history

    # Resolve str phase codes to int ids for FK columns
    next_phase_obj = phase_map.get(next_phase) if next_phase and next_phase in phase_map else None
    next_phase_id = next_phase_obj.id if next_phase_obj else None

    if new_state == "done":
        add_history(task_id, phase.id, "done")
        if next_phase_id:
            add_history(task_id, next_phase_id, "pending")
            db.update_task(task_id, {"current_phase": next_phase, "status": "active"})
        else:
            db.update_task(task_id, {"current_phase": phase.code, "status": "done"})
        if commit:
            db.commit()
        return
    if new_state == "blocked":
        add_history(task_id, phase.id, "blocked")
        db.update_task(task_id, {"current_phase": phase.code, "status": "blocked"})
        if commit:
            db.commit()
        return
    if new_state == "rollback":
        target_phase = phase_map.get(rollback_target) if rollback_target else None
        target_id = target_phase.id if target_phase else phase.id
        add_history(task_id, phase.id, "rollback")
        add_history(task_id, target_id, "pending")
        db.update_task(task_id, {"current_phase": rollback_target or phase.code, "status": "active"})
        if commit:
            db.commit()
        return
    if new_state == "delegated":
        add_history(task_id, phase.id, "delegated")
        db.update_task(task_id, {"current_phase": phase.code, "status": "active"})
        if commit:
            db.commit()
        return
    # partial or in_progress
    add_history(task_id, phase.id, "partial")
    db.update_task(task_id, {"current_phase": phase.code, "status": "active"})
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
    """Record a parallel-group FSM transition in the DB."""
    fsm = PhaseFSM(initial="in_progress")
    fsm.apply_verdict(verdict)
    new_state = fsm.state
    if not task:
        return
    task_id = int(task["id"])
    add_history = db.add_task_history if commit else db.tasks.add_history

    if new_state == "done":
        for phase in group:
            add_history(task_id, phase.id, "done")
        if next_phase:
            next_phase_obj = phase_map.get(next_phase)
            next_phase_id = next_phase_obj.id if next_phase_obj else None
            if next_phase_id:
                add_history(task_id, next_phase_id, "pending")
            db.update_task(task_id, {"current_phase": next_phase, "status": "active"})
        else:
            db.update_task(task_id, {"current_phase": group[-1].code, "status": "done"})
        if commit:
            db.commit()
        return
    if new_state == "blocked":
        for phase in group:
            add_history(task_id, phase.id, "blocked")
        db.update_task(task_id, {"current_phase": group[0].code, "status": "blocked"})
        if commit:
            db.commit()
        return
    if new_state == "rollback":
        for phase in group:
            add_history(task_id, phase.id, "rollback")
        target_phase = phase_map.get(rollback_target) if rollback_target else None
        target_code = target_phase.code if target_phase else group[0].code
        if target_phase:
            add_history(task_id, target_phase.id, "pending")
        db.update_task(task_id, {"current_phase": target_code, "status": "active"})
        if commit:
            db.commit()
        return
    if new_state == "delegated":
        for phase in group:
            add_history(task_id, phase.id, "delegated")
        db.update_task(task_id, {"current_phase": group[0].code, "status": "active"})
        if commit:
            db.commit()
        return
    for phase in group:
        add_history(task_id, phase.id, "partial")
    db.update_task(task_id, {"current_phase": group[0].code, "status": "active"})
    if commit:
        db.commit()
