"""Rollback engine — возврат к ранней фазе с очисткой checkpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import schema, state


class RollbackError(Exception):
    """Rollback невозможен."""
    pass


def get_phases_between(start_phase: str, end_phase: str) -> List[str]:
    """Получить список фаз между start (включительно) и end (включительно)."""
    order = schema.get_phase_order()
    try:
        start_idx = order.index(start_phase)
        end_idx = order.index(end_phase)
    except ValueError:
        return []

    if start_idx > end_idx:
        return []

    return order[start_idx:end_idx + 1]


def get_rollback_plan(phase_id: str) -> Tuple[Optional[str], List[str]]:
    """Получить план rollback: target фаза + список фаз для очистки.

    Returns:
        (target_phase_id, phases_to_clear)
    """
    phase = schema.get_phase(phase_id)
    if not phase:
        return None, []

    target = phase.rollback_target
    if not target:
        return None, []

    phases_to_clear = get_phases_between(target, phase_id)
    return target, phases_to_clear


def perform_rollback(repo: str, task_key: str, from_phase: str, reason: str) -> Dict[str, any]:
    """Выполнить rollback от from_phase к rollback_target.

    Чистит:
    - phases_completed в state (все между target и from)
    - current_phase → target
    - job status для очищенных фаз → reset
    - добавляет rollback entry в state
    """
    target, phases_to_clear = get_rollback_plan(from_phase)
    if not target:
        raise RollbackError(f"Фаза {from_phase} не имеет rollback_target")

    st = state.load_state(repo, task_key)
    if not st:
        raise RollbackError("Задача не инициализирована")

    # Очистить completed phases
    completed = st.get("phases_completed", [])
    new_completed = [p for p in completed if p not in phases_to_clear]

    # Обновить progress.json в task dir
    _clear_progress_phases(repo, task_key, phases_to_clear)

    # Save new state
    st["current_phase"] = target
    st["phases_completed"] = new_completed
    st["rollback_count"] = st.get("rollback_count", 0) + 1
    st["last_rollback"] = {
        "from_phase": from_phase,
        "to_phase": target,
        "reason": reason,
        "cleared_phases": phases_to_clear,
    }

    state_dir = Path(f"{state.WARTZ_DIR}/state")
    with open(state_dir / f"{task_key}.json", "w") as f:
        json.dump(st, f, indent=2, ensure_ascii=False)

    return {
        "from_phase": from_phase,
        "to_phase": target,
        "cleared_phases": phases_to_clear,
        "remaining_completed": new_completed,
        "rollback_count": st["rollback_count"],
    }


def _clear_progress_phases(repo: str, task_key: str, phases_to_clear: List[str]) -> None:
    """Очистить фазы в progress.json task dir."""
    info_dir = Path(f"{repo}/info")
    if not info_dir.exists():
        return
    for sprint_dir in info_dir.iterdir():
        if sprint_dir.is_dir() and sprint_dir.name.startswith("sprint"):
            for task_dir in sprint_dir.iterdir():
                if task_dir.is_dir():
                    progress_file = task_dir / "progress.json"
                    if progress_file.exists():
                        try:
                            with open(progress_file) as f:
                                data = json.load(f)
                            if data.get("task_key") == task_key:
                                for p in data.get("phases", []):
                                    if p.get("phase") in phases_to_clear:
                                        p["status"] = "pending"
                                        p.pop("completed_at", None)
                                        p.pop("evidence", None)
                                        p["gate_passed"] = False
                                with open(progress_file, "w") as f:
                                    json.dump(data, f, indent=2, ensure_ascii=False)
                                return
                        except Exception:
                            pass


def can_rollback(phase_id: str) -> bool:
    """Проверить можно ли откатиться от данной фазы."""
    phase = schema.get_phase(phase_id)
    return bool(phase and phase.rollback_target)


def get_cycle_info(task_key: str) -> Dict[str, any]:
    """Получить информацию о текущем цикле retry."""
    st = state.load_state(None, task_key)  # repo не нужен, state по task_key
    if not st:
        return {"cycles": 0, "max_cycles": 3, "remaining": 3, "last_rollback": None}

    rollbacks = st.get("rollback_count", 0)
    remaining = max(0, 3 - rollbacks)
    return {
        "cycles": rollbacks,
        "max_cycles": 3,
        "remaining": remaining,
        "last_rollback": st.get("last_rollback"),
    }
