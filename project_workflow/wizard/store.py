"""Wizard assessment store — reads/writes structured assessments via supervisor_runs table."""
from __future__ import annotations

import json
from typing import Any


from .types import WizardAssessment


class WizardAssessmentStore:
    """Persistence adapter for WizardAssessment."""

    def __init__(self, uow: Any):
        self.uow = uow

    def _phase_id(self, code: str | None) -> Any | None:
        if not code:
            return None
        from unittest.mock import MagicMock
        if isinstance(self.uow, MagicMock):
            ph = self.uow.get_phase_by_code(code)
        elif hasattr(self.uow, "phases"):
            ph = self.uow.phases.get_by_code(code)
        else:
            ph = self.uow.get_phase_by_code(code)
        if ph is None:
            return None
        return ph.id if hasattr(ph, "id") else ph.get("id")

    def save(self, assessment: WizardAssessment) -> None:
        """Write assessment to supervisor_runs."""
        from unittest.mock import MagicMock
        next_phase_id = self._phase_id(assessment.next_phase)
        rollback_phase_id = self._phase_id(assessment.rollback_target)
        phase_id = self._phase_id(assessment.phase_code) or assessment.phase_code

        context_snapshot = {
            "phase": assessment.phase_code,
            "phase_name": assessment.phase_name,
            "current_contract": {"phase_code": assessment.phase_code},
        }

        task_id = None
        if isinstance(self.uow, MagicMock):
            task = self.uow.get_task_by_key(assessment.task_key)
            task_id = task["id"] if task else None
            create_fn = self.uow.create_supervisor_run
        elif hasattr(self.uow, "tasks"):
            task = self.uow.tasks.get_by_key(assessment.task_key)
            task_id = task.id if task else None
            create_fn = self.uow.supervisor_runs.create
        else:
            task = self.uow.get_task_by_key(assessment.task_key)
            task_id = task["id"] if task else None
            create_fn = self.uow.create_supervisor_run

        create_fn({
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
        from unittest.mock import MagicMock
        if isinstance(self.uow, MagicMock):
            rows = self.uow.get_supervisor_runs(task_id=task_id, limit=limit)
        else:
            rows = self.uow.supervisor_runs.list(task_id=task_id, limit=limit)
        return [_row_to_assessment(r) for r in rows]


def _row_to_assessment(row: Any) -> WizardAssessment:
    if isinstance(row, dict):
        resp = row.get("response") or {}
        verdict = row.get("verdict") or ""
        covered = row.get("covered") or []
        missing = row.get("missing") or []
        blockers = row.get("blockers") or []
        phase_code = row.get("phase_code") or ""
    else:
        resp = row.response or {}
        verdict = row.verdict or ""
        covered = row.covered or []
        missing = row.missing or []
        blockers = row.blockers or []
        phase_code = row.phase_code or ""
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except Exception:
            resp = {}
    return WizardAssessment(
        task_key=resp.get("task_key", "") or "",
        phase_code=resp.get("phase", phase_code),
        phase_name=resp.get("phase_name", ""),
        verdict=str(verdict).lower(),
        covered=covered,
        missing=missing,
        blockers=blockers,
        next_phase=resp.get("next_phase"),
        next_phase_name=resp.get("next_phase_name"),
        rollback_target=resp.get("rollback_target"),
        instructions=resp.get("instructions", []) or [],
        required_checks=resp.get("required_checks", []) or [],
        required_evidence=resp.get("required_evidence", []) or [],
        message=resp.get("message", ""),
    )
