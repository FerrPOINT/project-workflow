"""Pure UI helper functions (no CLI/DB dependencies)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from project_workflow.domain.phase_grouping import group_parallel_phases


def _parse_optional_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _parse_key_prefixes(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(item).strip().upper() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [line.strip().upper() for line in raw.splitlines() if line.strip()]
    return []


def _run_to_dict(run: Any) -> dict[str, Any]:
    if isinstance(run, dict):
        return run
    if hasattr(run, "to_dict"):
        return run.to_dict()
    return dict(run)


def _build_parallel_phase_blocks(phases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build UI blocks with the same ``parallel_with`` semantics as Wizard."""
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
    current_phase: Any, _db: Any | None = None, workflow_id: int | None = None
) -> tuple[str, dict[str, Any] | None]:
    assert _db is not None
    token = str(current_phase if current_phase is not None else "-1")
    wdb: Any = _db

    workflow_phases = wdb.get_phases(workflow_id=workflow_id) if workflow_id is not None else wdb.get_phases()
    for phase in workflow_phases:
        if str(phase.get("code", phase.get("id"))) == token:
            return token, phase

    for phase in workflow_phases:
        if str(phase.get("id")) == token:
            return token, phase

    found_phase = wdb.get_phase(token)
    if found_phase:
        return token, dict(found_phase)

    try:
        numeric = int(token)
    except (TypeError, ValueError):
        return token, None
    numeric_phase = wdb.get_phase(numeric)
    return token, dict(numeric_phase) if numeric_phase else None


def _resolve_task_phase_local(
    current_phase: Any, workflow_phases: Sequence[dict[str, Any]], workflow_id: int | None = None
) -> tuple[str, dict[str, Any] | None]:
    """Resolve a phase token against a preloaded list of phases (no DB hits)."""
    token = str(current_phase if current_phase is not None else "-1")

    for phase in workflow_phases:
        if str(phase.get("code", phase.get("id"))) == token:
            return token, phase

    for phase in workflow_phases:
        if str(phase.get("id")) == token:
            return token, phase

    try:
        numeric = int(token)
    except (TypeError, ValueError):
        return token, None

    for phase in workflow_phases:
        if phase.get("id") == numeric:
            return token, dict(phase)
    return token, None
