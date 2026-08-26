"""Pure UI helper functions (no CLI/DB dependencies)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from project_workflow.domain.phase_grouping import group_parallel_phases


def _run_to_dict(run: Any) -> dict[str, Any]:
    if isinstance(run, dict):
        return run
    if hasattr(run, "to_dict"):
        return run.to_dict()
    return dict(run)


def _build_parallel_phase_blocks(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build UI blocks with the same ``parallel_with`` semantics as Supervisor."""
    normalized = [dict(phase) for phase in phases]
    groups = group_parallel_phases(
        normalized,
        code_of=lambda phase: str(phase.get("code", "")),
        execution_type_of=lambda phase: str(phase.get("execution_type", "sync")),
        parallel_with_of=lambda phase: phase.get("parallel_with"),
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


def _resolve_task_phase(
    current_phase: str | None, _db: Any | None = None, workflow_id: int | None = None
) -> tuple[str, dict[str, Any] | None]:
    assert _db is not None
    if current_phase is not None and not isinstance(current_phase, str):
        raise TypeError("current_phase должен быть строковым кодом фазы")
    token = current_phase or ""
    wdb: Any = _db

    if not isinstance(workflow_id, int) or isinstance(workflow_id, bool) or workflow_id <= 0:
        return token, None
    workflow_phases = wdb.get_phases(workflow_id=workflow_id)
    for phase in workflow_phases:
        if str(phase.get("code")) == token:
            return token, phase
    return token, None


def _resolve_task_phase_local(
    current_phase: str | None,
    workflow_phases: Sequence[dict[str, Any]],
    workflow_id: int | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Resolve a phase token against a preloaded list of phases (no DB hits)."""
    if current_phase is not None and not isinstance(current_phase, str):
        raise TypeError("current_phase должен быть строковым кодом фазы")
    token = current_phase or ""

    for phase in workflow_phases:
        if str(phase.get("code")) == token:
            return token, phase
    return token, None
