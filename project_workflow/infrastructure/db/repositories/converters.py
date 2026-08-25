"""Row-to-domain converters shared by repositories."""

from __future__ import annotations

import datetime as _dt
import json
from typing import Any

from project_workflow.domain import Agent, Phase, Project, SupervisorRun, Task, Workflow
from project_workflow.infrastructure.db import models as m


def _iso(value: _dt.datetime | str | None) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    return str(value)


def _row_to_phase(row: m.Phase) -> Phase:
    return Phase(
        id=row.id,
        workflow_id=row.workflow_id,
        code=row.code,
        name=row.name,
        description=row.description,
        min_time_min=row.min_time_min or 0,
        is_blocker=bool(row.is_blocker),
        is_delegated=bool(row.is_delegated),
        is_critic=bool(row.is_critic),
        phase_order=row.phase_order,
        agent_id=row.agent_id,
        next_recommendation=row.next_recommendation,
        parallel_with=row.parallel_with,
        rollback_target=row.rollback_target,
        execution_type=row.execution_type or "sync",
        is_seed_managed=bool(row.is_seed_managed),
        workflow_name=row.workflow.name if row.workflow else None,
    )


def _row_to_workflow(row: m.Workflow) -> Workflow:
    return Workflow(
        id=row.id,
        name=row.name,
        description=row.description or "",
        is_default=bool(row.is_default),
    )


def _row_to_project(row: m.Project) -> Project:
    raw = row.key_prefixes
    if not isinstance(raw, str):
        raise ValueError("Persisted project key_prefixes must be a JSON string array")
    try:
        prefixes = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Persisted project key_prefixes contain invalid JSON") from exc
    if not isinstance(prefixes, list) or not all(isinstance(prefix, str) for prefix in prefixes):
        raise ValueError("Persisted project key_prefixes must be a JSON string array")
    return Project(
        id=row.id,
        workflow_id=row.workflow_id,
        code=row.code,
        name=row.name,
        description=row.description,
        key_prefixes=[str(p) for p in prefixes],
        workflow_name=row.workflow.name if row.workflow else None,
    )


def _row_to_task(row: m.Task) -> Task:
    current_phase = row.current_phase
    phase_name = None
    try:
        if current_phase:
            phase = next(
                (p for p in row.workflow.phases if p.code == current_phase),
                None,
            )
            phase_name = phase.name if phase else current_phase
    except (AttributeError, TypeError):
        phase_name = current_phase
    return Task(
        id=getattr(row, "id", None),
        project_id=row.project_id,
        workflow_id=row.workflow_id,
        task_key=row.task_key,
        title=row.title or "",
        description=row.description or "",
        current_phase=current_phase,
        current_phase_name=phase_name or "",
        status=row.status or "active",
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


def _row_to_agent(row: m.Agent) -> Agent:
    return Agent(
        id=row.id,
        name=row.name,
        description=row.description or "",
        hermes_profile=row.hermes_profile or None,
    )


def _row_to_supervisor_run(row: m.SupervisorRun) -> SupervisorRun:
    def _parse(raw: str | None) -> list[str]:
        if not isinstance(raw, str):
            raise ValueError("Persisted supervisor list field must be a JSON string array")
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Persisted supervisor list field contains invalid JSON") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise ValueError("Persisted supervisor list field must be a JSON string array")
        return parsed

    def _parse_obj(raw: str | None) -> dict[str, Any]:
        if not isinstance(raw, str):
            raise ValueError("Persisted supervisor object field must be a JSON object")
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Persisted supervisor object field contains invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Persisted supervisor object field must be a JSON object")
        return parsed

    return SupervisorRun(
        id=row.id,
        task_id=row.task_id,
        phase_id=row.phase_id,
        verdict=row.verdict,
        report=row.report or "",
        covered=_parse(row.covered),
        missing=_parse(row.missing),
        blockers=_parse(row.blockers),
        next_phase_id=row.next_phase_id,
        rollback_phase_id=row.rollback_phase_id,
        report_fingerprint=row.report_fingerprint,
        context_snapshot=_parse_obj(row.context_snapshot),
        response=_parse_obj(row.response),
        created_at=_iso(row.created_at),
    )
