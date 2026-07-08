"""Pure UI helper functions (no CLI/DB dependencies)."""

from __future__ import annotations

from typing import Any

from ... import config
from .templates import env as _templates_env


def _parse_optional_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _group_instructions(instructions: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Группирует инструкции по runs: parallel примыкает к предыдущей sync и идёт с ней рядом."""
    if not instructions:
        return []
    groups: list[list[dict[str, Any]]] = []
    current = [instructions[0]]
    for instruction in instructions[1:]:
        if instruction.get("execution_type") == "parallel":
            current.append(instruction)
        else:
            groups.append(current)
            current = [instruction]
    groups.append(current)
    return groups


_templates_env.filters["group_instructions"] = _group_instructions


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
    """Группирует фазы по execution_type-run: parallel примыкает к текущему sync-run."""
    if not phases:
        return []

    runs: list[list[dict[str, Any]]] = []
    current_run: list[dict[str, Any]] = []
    for phase in phases:
        if not current_run:
            current_run.append(dict(phase))
        elif phase.get("execution_type") == "parallel":
            current_run.append(dict(phase))
        else:
            runs.append(current_run)
            current_run = [dict(phase)]
    if current_run:
        runs.append(current_run)

    blocks: list[dict[str, Any]] = []
    for idx, run in enumerate(runs):
        group_key = str(run[0].get("code", idx))
        if len(run) > 1:
            for phase in run:
                phase["parallel_group"] = group_key
            blocks.append({"kind": "parallel", "phases": run})
        else:
            run[0]["parallel_group"] = None
            blocks.append({"kind": "single", "phases": run})

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
        if str(phase.get("id")) == token:
            return token, phase

    found_phase = wdb.get_phase(token)
    if found_phase:
        return token, dict(found_phase)

    redirected = config.LEGACY_PHASE_REDIRECTS.get(token)
    if redirected:
        for phase in workflow_phases:
            if str(phase.get("code", phase.get("id"))) == redirected:
                return redirected, dict(phase)
        redirected_phase = wdb.get_phase(redirected)
        if redirected_phase:
            return redirected, dict(redirected_phase)

    try:
        numeric = int(token)
    except (TypeError, ValueError):
        return token, None
    numeric_phase = wdb.get_phase(numeric)
    return token, dict(numeric_phase) if numeric_phase else None


def _resolve_task_phase_local(
    current_phase: Any, workflow_phases: list[dict[str, Any]], workflow_id: int | None = None
) -> tuple[str, dict[str, Any] | None]:
    """Resolve a phase token against a preloaded list of phases (no DB hits)."""
    token = str(current_phase if current_phase is not None else "-1")

    for phase in workflow_phases:
        if str(phase.get("code", phase.get("id"))) == token:
            return token, phase
        if str(phase.get("id")) == token:
            return token, phase

    redirected = config.LEGACY_PHASE_REDIRECTS.get(token)
    if redirected:
        for phase in workflow_phases:
            if str(phase.get("code", phase.get("id"))) == redirected:
                return redirected, dict(phase)

    try:
        numeric = int(token)
    except (TypeError, ValueError):
        return token, None

    for phase in workflow_phases:
        if phase.get("id") == numeric:
            return token, dict(phase)
    return token, None
