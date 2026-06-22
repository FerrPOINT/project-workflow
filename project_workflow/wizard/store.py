"""Wizard assessment store — reads/writes structured assessments via supervisor_runs table."""
from __future__ import annotations

import json
from typing import Any

from ..db import WorkflowDB
from .types import WizardAssessment


class WizardAssessmentStore:
    """Persistence adapter for WizardAssessment."""

    def __init__(self, db: WorkflowDB):
        self.db = db

    def save(self, assessment: WizardAssessment) -> None:
        """Write assessment to supervisor_runs."""
        next_phase_id = None
        rollback_phase_id = None
        if assessment.next_phase:
            ph = self.db.get_phase_by_code(assessment.next_phase)
            if ph:
                next_phase_id = ph["id"]
        if assessment.rollback_target:
            ph = self.db.get_phase_by_code(assessment.rollback_target)
            if ph:
                rollback_phase_id = ph["id"]

        phase_id = None
        ph = self.db.get_phase_by_code(assessment.phase_code)
        if ph:
            phase_id = ph["id"]

        context_snapshot = {
            "phase": assessment.phase_code,
            "phase_name": assessment.phase_name,
            "current_contract": {"phase_code": assessment.phase_code},
        }

        task = self.db.get_task_by_key(assessment.task_key)
        task_id = task["id"] if task else None

        self.db.create_supervisor_run({
            "task_id": task_id,
            "phase_id": phase_id or assessment.phase_code,
            "verdict": assessment.verdict,
            "report": "",  # caller fills separately if needed
            "covered": assessment.covered,
            "missing": assessment.missing,
            "blockers": assessment.blockers,
            "next_phase_id": next_phase_id,
            "rollback_phase_id": rollback_phase_id,
            "context_snapshot": context_snapshot,
            "response": assessment.to_result_dict(),
        })

    def get_latest(self, task_id: int, limit: int = 1) -> list[WizardAssessment]:
        """Read latest assessments for a task."""
        rows = self.db.get_supervisor_runs(task_id=task_id, limit=limit)
        return [_row_to_assessment(r) for r in rows]


def _row_to_assessment(row: dict[str, Any]) -> WizardAssessment:
    resp = row.get("response") or {}
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except Exception:
            resp = {}
    return WizardAssessment(
        task_key=resp.get("task_key", "") or "",
        phase_code=resp.get("phase", row.get("phase_code", "")),
        phase_name=resp.get("phase_name", ""),
        verdict=str(row.get("verdict", "")).lower(),
        covered=row.get("covered", []) or [],
        missing=row.get("missing", []) or [],
        blockers=row.get("blockers", []) or [],
        next_phase=resp.get("next_phase"),
        next_phase_name=resp.get("next_phase_name"),
        rollback_target=resp.get("rollback_target"),
        instructions=resp.get("instructions", []) or [],
        required_checks=resp.get("required_checks", []) or [],
        required_evidence=resp.get("required_evidence", []) or [],
        message=resp.get("message", ""),
    )
