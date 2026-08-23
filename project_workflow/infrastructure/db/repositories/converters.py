"""Row-to-domain converters shared by repositories."""

from __future__ import annotations

import datetime as _dt
import json
import logging
from typing import Any

from project_workflow.domain import Agent, Phase, Project, SupervisorRun, Task, Workflow
from project_workflow.infrastructure.db import models as m

logger = logging.getLogger(__name__)


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
    raw = row.key_prefixes or "[]"
    try:
        prefixes = json.loads(raw) if isinstance(raw, str) else []
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed to parse project key_prefixes: %s", exc)
        prefixes = []
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
    current_phase = row.current_phase or "-1"
    phase_name = None
    try:
        if current_phase and current_phase != "-1":
            phase = next(
                (p for p in row.project.workflow.phases if str(p.id) == current_phase or p.code == current_phase),
                None,
            )
            phase_name = phase.name if phase else current_phase
    except (AttributeError, TypeError) as exc:
        logger.warning("Failed to resolve task phase name: %s", exc)
        phase_name = current_phase
    return Task(
        id=getattr(row, "id", None),
        project_id=row.project_id,
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
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to parse supervisor list field: %s", exc)
            return []

    def _parse_obj(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Failed to parse supervisor object field: %s", exc)
            return {}

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
