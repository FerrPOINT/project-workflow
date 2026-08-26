"""Pure UI helper functions (no CLI/DB dependencies)."""

from __future__ import annotations

from typing import Any

from project_workflow.domain.phase_grouping import group_parallel_phases


def _run_to_dict(run: Any) -> dict[str, Any]:
    if isinstance(run, dict):
        return run
    if hasattr(run, "to_dict"):
        return run.to_dict()
    return dict(run)


def _build_parallel_phase_blocks(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build UI blocks with the same phase-link semantics as Supervisor."""
    normalized = [dict(phase) for phase in phases]
    groups = group_parallel_phases(
        normalized,
        code_of=lambda phase: str(phase.get("code", "")),
        id_of=lambda phase: int(phase["id"]),
        execution_type_of=lambda phase: str(phase.get("execution_type", "sync")),
        parallel_with_phase_id_of=lambda phase: phase.get("parallel_with_phase_id"),
    )
    blocks: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        group_key = str(group[0].get("code", index))
        if len(group) > 1:
            for phase in group:
                phase["parallel_group"] = group_key
            statuses = {str(phase.get("status", "wait")) for phase in group}
            block_status = "current" if "current" in statuses else ("done" if statuses == {"done"} else "wait")
            blocks.append({"kind": "parallel", "status": block_status, "phases": group})
        else:
            group[0]["parallel_group"] = None
            blocks.append(
                {"kind": "single", "status": str(group[0].get("status", "wait")), "phases": group}
            )

    return blocks


def _resolve_task_phase_id(
    current_phase_id: int, workflow_phases: list[dict[str, Any]]
) -> dict[str, Any]:
    """Resolve the persisted FK inside the owning workflow or fail closed."""
    if not isinstance(current_phase_id, int) or isinstance(current_phase_id, bool) or current_phase_id <= 0:
        raise ValueError("current_phase_id задачи должен быть положительным целым числом")
    phase = next((item for item in workflow_phases if item.get("id") == current_phase_id), None)
    if phase is None:
        raise ValueError(f"Текущая фаза {current_phase_id} отсутствует в воркфлоу задачи")
    return phase
